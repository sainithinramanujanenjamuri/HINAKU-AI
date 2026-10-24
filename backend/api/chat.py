import json
import time
import uuid
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.config import get_settings
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter
from backend.models.router import ModelRouter
from backend.persona import PersonaManager
from backend.history import ChatHistoryManager, trim_history
from backend.memory import MemoryStorage, MemoryExtractor, MemoryManager
from backend.quality import verify_reply
from backend.guards import (
    check_and_redact_sensitive_data,
    is_live_data_query,
    is_clock_query,
    get_clock_reply,
    get_system_clock_context
)
from backend.models.ollama_shared import log_ollama_call

logger = logging.getLogger("hinaku.chat")

router = APIRouter()
settings = get_settings()

history_manager = ChatHistoryManager(db_path=settings.sqlite_path)
persona_manager = PersonaManager(file_path=settings.persona_file)

local_adapter = OllamaAdapter(
    host=settings.local_host,
    default_model=settings.default_local_model,
    default_options=settings.local_options,
    default_think=settings.local_think,
    default_keep_alive=settings.local_keep_alive
)
adapter = local_adapter

api_adapter = ApiAdapter(
    provider=settings.api_provider,
    model=settings.api_model,
    base_url=settings.api_base_url,
    api_key=settings.get_api_key(),
    timeout=float(settings.api_timeout_seconds),
    max_tokens=settings.api_max_tokens
)

model_router = ModelRouter(
    local_adapter=local_adapter,
    api_adapter=api_adapter,
    mode=settings.router_mode,
    fallback_on_failure=settings.fallback_on_failure,
    max_prompt_tokens=settings.local_max_prompt_tokens,
    max_daily_api_requests=settings.api_max_requests_per_day,
    history_manager=history_manager
)

memory_storage = MemoryStorage(
    db_path=settings.sqlite_path,
    chroma_path=settings.chroma_path,
    embedding_model=settings.memory_embedding_model,
    embedding_dims=settings.memory_embedding_dims,
    query_prefix=settings.memory_query_prefix,
    document_prefix=settings.memory_document_prefix,
    ollama_host=settings.local_host
)

memory_extractor = MemoryExtractor(
    local_adapter=local_adapter,
    storage=memory_storage,
    never_store_categories=settings.memory_never_store,
    merge_threshold=settings.memory_merge_threshold
)

memory_manager = MemoryManager(
    storage=memory_storage,
    extractor=memory_extractor,
    enabled=settings.memory_enabled,
    learn_from_private_chats=settings.memory_learn_from_private_chats,
    retrieve_top_k=settings.memory_retrieve_top_k,
    min_similarity=settings.memory_min_similarity
)

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    stream: Optional[bool] = True
    is_private: Optional[bool] = None
    think_harder: Optional[bool] = False
    detailed: Optional[bool] = False

class ChatResponse(BaseModel):
    role: str
    content: str
    model: str
    backend: str
    conversation_id: str
    persona_fallback: bool = False
    notice: Optional[str] = None
    message_id: Optional[str] = None
    interaction_id: Optional[str] = None
    verified: bool = False
    think_harder_used: bool = False
    detailed_used: bool = False
    hit_token_limit: bool = False
    latency_breakdown: Optional[Dict[str, int]] = None

@router.get("/info")
async def get_info():
    health = await local_adapter.check_health()
    persona_state = persona_manager.get_persona()
    api_ready = bool(settings.get_api_key())
    daily_count = history_manager.get_daily_api_request_count()
    return {
        "app_name": settings.app_name,
        "default_model": settings.default_local_model,
        "allowed_models": settings.allowed_local_models,
        "hard_timeout_seconds": settings.hard_timeout_seconds,
        "provider": "ollama (local)",
        "ollama_status": health,
        "router": {
            "mode": settings.router_mode,
            "fallback_on_failure": settings.fallback_on_failure,
            "api_provider": settings.api_provider,
            "api_model": settings.api_model,
            "api_ready": api_ready,
            "api_logged_by_provider": settings.api_logged_by_provider,
            "daily_api_requests": daily_count,
            "max_daily_api_requests": settings.api_max_requests_per_day
        },
        "reduced_motion": settings.app.get("reduced_motion", False),
        "persona": {
            "is_fallback": persona_state.is_fallback,
            "notice": persona_state.notice,
            "file": str(settings.persona_file)
        }
    }

@router.get("/health/ollama")
async def get_ollama_health():
    health = await local_adapter.check_health()
    return health

@router.post("/chat")
async def chat_endpoint(req: ChatRequest, response: Response):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    persona_state = persona_manager.get_persona()

    # Determine or create conversation
    conv_id = req.conversation_id or str(uuid.uuid4())
    conv = history_manager.get_conversation(conv_id)
    if not conv:
        is_private = bool(req.is_private)
        history_manager.create_conversation(conv_id=conv_id, is_private=is_private)
    else:
        if req.is_private is not None:
            is_private = bool(req.is_private)
            history_manager.set_conversation_privacy(conv_id, is_private)
        else:
            is_private = bool(conv.get("is_private", False))

    # Identify latest user message
    latest_msg = req.messages[-1]
    latest_user_text = latest_msg.content if latest_msg.role == "user" else ""

    # GUARD 1: Sensitive-Data Guard (PIN, password, card number, bank account, government ID)
    is_sensitive, sanitized_user_text = check_and_redact_sensitive_data(latest_user_text)
    if is_sensitive and settings.guards_sensitive_data_enabled:
        log_ollama_call(
            call_type="guard_sensitive",
            model="none",
            num_ctx=None,
            keep_alive=None,
            options={},
            load_duration_ns=0,
            total_duration_ns=0,
            extra_info="regex refusal (no model called)"
        )
        if latest_msg.role == "user":
            history_manager.add_message(conv_id, "user", sanitized_user_text)
        reply_content = settings.guards_sensitive_data_reply
        ast_msg = history_manager.add_message(conv_id, "assistant", reply_content, model="sensitive-data guard", backend="guard")
        inter_id = history_manager.log_interaction(
            conv_id=conv_id,
            user_prompt=sanitized_user_text,
            answer=reply_content,
            model="sensitive-data guard",
            backend="guard",
            message_id=ast_msg["id"]
        )
        response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
        response.headers["X-Conversation-Id"] = conv_id

        if req.stream:
            async def sensitive_stream():
                init_meta = {
                    "type": "meta",
                    "conversation_id": conv_id,
                    "persona_fallback": persona_state.is_fallback,
                    "notice": None,
                    "is_private": is_private,
                    "logged_by_provider": False,
                    "message_id": ast_msg["id"],
                    "interaction_id": inter_id
                }
                yield f"data: {json.dumps(init_meta)}\n\n"
                chunk_data = {
                    "chunk": reply_content,
                    "backend": "guard",
                    "model": "sensitive-data guard",
                    "notice": None,
                    "message_id": ast_msg["id"],
                    "interaction_id": inter_id
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                sensitive_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Persona-Fallback": str(persona_state.is_fallback).lower(),
                    "X-Conversation-Id": conv_id
                }
            )
        else:
            return ChatResponse(
                role="assistant",
                content=reply_content,
                model="sensitive-data guard",
                backend="guard",
                conversation_id=conv_id,
                persona_fallback=persona_state.is_fallback,
                notice=None,
                message_id=ast_msg["id"],
                interaction_id=inter_id
            )

    # GUARD 2: Clock Guard (date, day of week, time answered directly from system clock)
    if is_clock_query(latest_user_text):
        clock_reply = get_clock_reply(latest_user_text)
        if clock_reply:
            log_ollama_call(
                call_type="guard_clock",
                model="none",
                num_ctx=None,
                keep_alive=None,
                options={},
                load_duration_ns=0,
                total_duration_ns=0,
                extra_info="system clock reply (no model called)"
            )
            if latest_msg.role == "user":
                history_manager.add_message(conv_id, "user", latest_user_text)
            ast_msg = history_manager.add_message(conv_id, "assistant", clock_reply, model="clock guard", backend="guard")
            inter_id = history_manager.log_interaction(
                conv_id=conv_id,
                user_prompt=latest_user_text,
                answer=clock_reply,
                model="clock guard",
                backend="guard",
                message_id=ast_msg["id"]
            )
            response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
            response.headers["X-Conversation-Id"] = conv_id

            if req.stream:
                async def clock_stream():
                    init_meta = {
                        "type": "meta",
                        "conversation_id": conv_id,
                        "persona_fallback": persona_state.is_fallback,
                        "notice": None,
                        "is_private": is_private,
                        "logged_by_provider": False,
                        "message_id": ast_msg["id"],
                        "interaction_id": inter_id
                    }
                    yield f"data: {json.dumps(init_meta)}\n\n"
                    chunk_data = {
                        "chunk": clock_reply,
                        "backend": "guard",
                        "model": "clock guard",
                        "notice": None,
                        "message_id": ast_msg["id"],
                        "interaction_id": inter_id
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    clock_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                        "X-Persona-Fallback": str(persona_state.is_fallback).lower(),
                        "X-Conversation-Id": conv_id
                    }
                )
            else:
                return ChatResponse(
                    role="assistant",
                    content=clock_reply,
                    model="clock guard",
                    backend="guard",
                    conversation_id=conv_id,
                    persona_fallback=persona_state.is_fallback,
                    notice=None,
                    message_id=ast_msg["id"],
                    interaction_id=inter_id
                )

    # GUARD 3: Live-Data Guard (real-time prices, weather, news, sports)
    is_live = is_live_data_query(latest_user_text, settings.guards_live_data_patterns)
    if is_live and settings.guards_live_data_enabled:
        log_ollama_call(
            call_type="guard_live_data",
            model="none",
            num_ctx=None,
            keep_alive=None,
            options={},
            load_duration_ns=0,
            total_duration_ns=0,
            extra_info="regex refusal (no model called)"
        )
        if latest_msg.role == "user":
            history_manager.add_message(conv_id, "user", latest_user_text)
        reply_content = settings.guards_live_data_reply
        ast_msg = history_manager.add_message(conv_id, "assistant", reply_content, model="live-data guard", backend="guard")
        inter_id = history_manager.log_interaction(
            conv_id=conv_id,
            user_prompt=latest_user_text,
            answer=reply_content,
            model="live-data guard",
            backend="guard",
            message_id=ast_msg["id"]
        )
        response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
        response.headers["X-Conversation-Id"] = conv_id

        if req.stream:
            async def live_stream():
                init_meta = {
                    "type": "meta",
                    "conversation_id": conv_id,
                    "persona_fallback": persona_state.is_fallback,
                    "notice": None,
                    "is_private": is_private,
                    "logged_by_provider": False,
                    "message_id": ast_msg["id"],
                    "interaction_id": inter_id
                }
                yield f"data: {json.dumps(init_meta)}\n\n"
                chunk_data = {
                    "chunk": reply_content,
                    "backend": "guard",
                    "model": "live-data guard",
                    "notice": None,
                    "message_id": ast_msg["id"],
                    "interaction_id": inter_id
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                live_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Persona-Fallback": str(persona_state.is_fallback).lower(),
                    "X-Conversation-Id": conv_id
                }
            )
        else:
            return ChatResponse(
                role="assistant",
                content=reply_content,
                model="live-data guard",
                backend="guard",
                conversation_id=conv_id,
                persona_fallback=persona_state.is_fallback,
                notice=None,
                message_id=ast_msg["id"],
                interaction_id=inter_id
            )

    # Save latest user message to SQLite history (clean of sensitive data)
    if latest_msg.role == "user":
        history_manager.add_message(conv_id, "user", latest_msg.content)

    # Load full conversation history from SQLite for robust context
    conv_data = history_manager.get_conversation(conv_id)
    db_messages = conv_data.get("messages", []) if conv_data else []

    # Identify previous assistant backend for router stickiness
    last_backend = None
    for m in reversed(db_messages[:-1] if db_messages else []):
        if m.get("role") == "assistant" and m.get("backend"):
            last_backend = m["backend"]
            break

    messages_to_trim = [{"role": m["role"], "content": m["content"]} for m in db_messages]
    if not messages_to_trim:
        messages_to_trim = [
            {"role": m.role, "content": m.content}
            for m in req.messages
            if m.role != "system"
        ]

    from backend.guards import is_detail_request, trim_to_last_complete_sentence

    is_detail = bool(req.detailed) or is_detail_request(latest_user_text)

    # Identify target backend for memory retrieval privacy rule
    router_decision = model_router.decide_backend(
        latest_user_text,
        is_private=is_private,
        last_backend=last_backend,
        is_detail=is_detail
    )
    is_api = (router_decision.target_backend == "api")

    # Retrieve memory context (only for local model requests per privacy rules)
    t_mem_start = time.perf_counter()
    memory_context = memory_manager.retrieve_context(
        latest_user_text,
        is_private=is_private,
        is_api_request=is_api,
        send_personal_context=settings.api_send_personal_context
    )
    memory_ms = int((time.perf_counter() - t_mem_start) * 1000)

    clock_context = get_system_clock_context()
    persona_text = persona_state.content
    if is_api and is_detail:
        persona_text += "\n\nKeep the explanation clear and well-organized, up to about 350 words maximum."
    system_parts = [persona_text, clock_context]
    if memory_context:
        system_parts.append(memory_context)
    system_content = "\n\n".join(system_parts)

    # Prepend persona system prompt (with memory context if applicable) and trim history
    full_messages = [{"role": "system", "content": system_content}] + messages_to_trim
    trimmed_messages = trim_history(full_messages, max_tokens=settings.max_context_tokens)

    # Re-read fresh API key if changed in environment
    api_adapter.api_key = settings.get_api_key()

    target_model = req.model if (req.model and req.model in settings.allowed_local_models) else settings.default_local_model
    target_opts = dict(settings.get_model_options(target_model))
    think_harder_used = False
    use_think = False

    if is_detail:
        target_opts["num_predict"] = max(target_opts.get("num_predict", 300), settings.detail_num_predict)

    if req.think_harder and target_model in settings.supports_think_models:
        use_think = True
        think_harder_used = True
        target_opts["num_predict"] = settings.think_num_predict

    response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
    response.headers["X-Conversation-Id"] = conv_id
    if persona_state.notice:
        response.headers["X-Persona-Notice"] = persona_state.notice

    if req.stream:
        async def event_generator():
            accumulated_chunks = []
            used_backend = "local"
            used_model = target_model
            stream_notice = persona_state.notice

            # Initial metadata payload
            init_meta = {
                "type": "meta",
                "conversation_id": conv_id,
                "persona_fallback": persona_state.is_fallback,
                "notice": persona_state.notice,
                "is_private": is_private,
                "logged_by_provider": settings.api_logged_by_provider,
                "think_harder_used": think_harder_used,
                "detailed_used": is_detail
            }
            yield f"data: {json.dumps(init_meta)}\n\n"

            t_gen_start = time.perf_counter()
            encountered_error = None
            async for event in model_router.stream_chat(
                trimmed_messages,
                user_prompt=latest_user_text,
                is_private=is_private,
                last_backend=last_backend,
                override_model=target_model,
                think=use_think,
                options=target_opts,
                is_detail=is_detail
            ):
                if event.get("type") == "error":
                    encountered_error = event
                    yield f"data: {json.dumps(event)}\n\n"
                    break

                used_backend = event["backend"]
                used_model = event["model"]
                if event.get("notice"):
                    stream_notice = event["notice"]

                chunk_payload = {
                    "type": "chunk",
                    "chunk": event["chunk"],
                    "backend": used_backend,
                    "model": used_model,
                    "conversation_id": conv_id,
                    "persona_fallback": persona_state.is_fallback,
                    "notice": stream_notice,
                    "logged_by_provider": settings.api_logged_by_provider
                }
                accumulated_chunks.append(event["chunk"])
                yield f"data: {json.dumps(chunk_payload)}\n\n"

            if encountered_error:
                # Do NOT save error to DB, do NOT log to interactions or datasets
                yield "data: [DONE]\n\n"
                return

            gen_ms = int((time.perf_counter() - t_gen_start) * 1000)
            draft_reply = "".join(accumulated_chunks)

            # If reply hit token limit (ends mid-sentence), cut back to last complete sentence
            trimmed_draft, was_cut = trim_to_last_complete_sentence(draft_reply)
            if was_cut:
                draft_reply = trimmed_draft
                yield f"data: {json.dumps({'type': 'correction', 'final_content': draft_reply, 'conversation_id': conv_id, 'hit_token_limit': True})}\n\n"

            final_reply = draft_reply
            was_verified = False
            verify_ms = 0
            verify_status = "not_verified"
            verify_reason = None

            # Fallback for empty reply: every stream must end cleanly with visible in-persona text
            if not final_reply.strip():
                final_reply = "I couldn't put an answer together that time. Ask again, or turn off Think harder."
                draft_reply = final_reply
                verify_status = "not_verified"
                verify_reason = "empty_reply"
                fallback_chunk = {
                    "type": "chunk",
                    "chunk": final_reply,
                    "backend": used_backend,
                    "model": used_model,
                    "conversation_id": conv_id,
                    "persona_fallback": persona_state.is_fallback,
                    "notice": stream_notice,
                    "logged_by_provider": settings.api_logged_by_provider
                }
                yield f"data: {json.dumps(fallback_chunk)}\n\n"
            elif used_backend == "local" and settings.quality_mode:
                final_reply, was_verified, verify_ms, verify_status, verify_reason = await verify_reply(
                    draft=draft_reply,
                    persona_rules=persona_state.content,
                    clock_ctx=clock_context,
                    memory_ctx=memory_context or "",
                    local_adapter=local_adapter,
                    model=used_model,
                    options=target_opts,
                    keep_alive=settings.local_keep_alive,
                    is_detail=is_detail
                )
                if final_reply != draft_reply:
                    corr_payload = {
                        "type": "correction",
                        "final_content": final_reply,
                        "conversation_id": conv_id
                    }
                    yield f"data: {json.dumps(corr_payload)}\n\n"
            elif used_backend != "local":
                verify_status = "not_verified"
                verify_reason = "api_backend"
            else:
                verify_status = "not_verified"
                verify_reason = "quality_mode_off"

            latency_breakdown = {
                "generation_ms": gen_ms,
                "verify_ms": verify_ms,
                "think_ms": 0,
                "memory_ms": memory_ms
            }

            if final_reply.strip():
                # Persist message with model & backend
                ast_msg = history_manager.add_message(
                    conv_id,
                    "assistant",
                    final_reply,
                    model=used_model,
                    backend=used_backend
                )
                # Log interaction
                inter_id = history_manager.log_interaction(
                    conv_id=conv_id,
                    user_prompt=latest_user_text,
                    answer=final_reply,
                    model=used_model,
                    backend=used_backend,
                    message_id=ast_msg["id"],
                    draft_reply=draft_reply,
                    verified=was_verified,
                    latency_ms=gen_ms + verify_ms,
                    verify_ms=verify_ms,
                    think_ms=0,
                    memory_ms=memory_ms
                )
                # Background memory extraction using LOCAL model (never API)
                if not is_private and settings.memory_enabled and settings.memory_extract_after_each_turn:
                    import asyncio
                    asyncio.create_task(
                        memory_manager.extract_and_store(
                            conversation_id=conv_id,
                            user_message=latest_user_text,
                            assistant_message=final_reply,
                            is_private=is_private
                        )
                    )

                done_payload = {
                    "type": "done",
                    "conversation_id": conv_id,
                    "message_id": ast_msg["id"],
                    "interaction_id": inter_id,
                    "backend": used_backend,
                    "model": used_model,
                    "verified": was_verified,
                    "verify_status": verify_status,
                    "verify_reason": verify_reason,
                    "think_harder_used": think_harder_used,
                    "detailed_used": is_detail,
                    "hit_token_limit": was_cut,
                    "latency_breakdown": latency_breakdown,
                    "final_reply": final_reply
                }
                yield f"data: {json.dumps(done_payload)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Persona-Fallback": str(persona_state.is_fallback).lower(),
                "X-Persona-Notice": persona_state.notice or "",
                "X-Conversation-Id": conv_id
            }
        )
    else:
        accumulated_chunks = []
        used_backend = "local"
        used_model = target_model
        used_notice = persona_state.notice

        t_gen_start = time.perf_counter()
        encountered_error = None
        async for event in model_router.stream_chat(
            trimmed_messages,
            user_prompt=latest_user_text,
            is_private=is_private,
            last_backend=last_backend,
            override_model=target_model,
            think=use_think,
            options=target_opts,
            is_detail=is_detail
        ):
            if event.get("type") == "error":
                encountered_error = event
                break
            accumulated_chunks.append(event["chunk"])
            used_backend = event["backend"]
            used_model = event["model"]
            if event.get("notice"):
                used_notice = event["notice"]

        if encountered_error:
            raise HTTPException(status_code=502, detail=encountered_error.get("error", "Model error"))

        gen_ms = int((time.perf_counter() - t_gen_start) * 1000)
        draft_reply = "".join(accumulated_chunks)

        trimmed_draft, was_cut = trim_to_last_complete_sentence(draft_reply)
        if was_cut:
            draft_reply = trimmed_draft

        final_reply = draft_reply
        was_verified = False
        verify_ms = 0
        verify_status = "not_verified"
        verify_reason = None

        if not final_reply.strip():
            final_reply = "I couldn't put an answer together that time. Ask again, or turn off Think harder."
            draft_reply = final_reply
            verify_status = "not_verified"
            verify_reason = "empty_reply"
        elif used_backend == "local" and settings.quality_mode:
            final_reply, was_verified, verify_ms, verify_status, verify_reason = await verify_reply(
                draft=draft_reply,
                persona_rules=persona_state.content,
                clock_ctx=clock_context,
                memory_ctx=memory_context or "",
                local_adapter=local_adapter,
                model=used_model,
                options=target_opts,
                keep_alive=settings.local_keep_alive,
                is_detail=is_detail
            )
        elif used_backend != "local":
            verify_status = "not_verified"
            verify_reason = "api_backend"
        else:
            verify_status = "not_verified"
            verify_reason = "quality_mode_off"

        latency_breakdown = {
            "generation_ms": gen_ms,
            "verify_ms": verify_ms,
            "think_ms": 0,
            "memory_ms": memory_ms
        }

        ast_msg = history_manager.add_message(
            conv_id,
            "assistant",
            final_reply,
            model=used_model,
            backend=used_backend
        )
        inter_id = history_manager.log_interaction(
            conv_id=conv_id,
            user_prompt=latest_user_text,
            answer=final_reply,
            model=used_model,
            backend=used_backend,
            message_id=ast_msg["id"],
            draft_reply=draft_reply,
            verified=was_verified,
            latency_ms=gen_ms + verify_ms,
            verify_ms=verify_ms,
            think_ms=0,
            memory_ms=memory_ms
        )
        if final_reply.strip():
            if not is_private and settings.memory_enabled and settings.memory_extract_after_each_turn:
                import asyncio
                asyncio.create_task(
                    memory_manager.extract_and_store(
                        conversation_id=conv_id,
                        user_message=latest_user_text,
                        assistant_message=final_reply,
                        is_private=is_private
                    )
                )
        return ChatResponse(
            role="assistant",
            content=final_reply,
            model=used_model,
            backend=used_backend,
            conversation_id=conv_id,
            persona_fallback=persona_state.is_fallback,
            notice=used_notice,
            message_id=ast_msg["id"],
            interaction_id=inter_id,
            verified=was_verified,
            think_harder_used=think_harder_used,
            detailed_used=is_detail,
            hit_token_limit=was_cut,
            latency_breakdown=latency_breakdown
        )
