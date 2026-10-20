import json
import uuid
from typing import List, Optional
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

router = APIRouter()
settings = get_settings()

history_manager = ChatHistoryManager(db_path=settings.sqlite_path)
persona_manager = PersonaManager(file_path=settings.persona_file)

local_adapter = OllamaAdapter(
    host=settings.local_host,
    default_model=settings.default_local_model,
    default_options=settings.local_options,
    default_think=settings.local_think
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

class ChatResponse(BaseModel):
    role: str
    content: str
    model: str
    backend: str
    conversation_id: str
    persona_fallback: bool = False
    notice: Optional[str] = None

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

    # Save latest user message to SQLite history
    latest_msg = req.messages[-1]
    latest_user_text = latest_msg.content if latest_msg.role == "user" else ""
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

    # Identify target backend for memory retrieval privacy rule
    router_decision = model_router.decide_backend(
        latest_user_text,
        is_private=is_private,
        last_backend=last_backend
    )
    is_api = (router_decision.target_backend == "api")

    # Retrieve memory context (only for local model requests per privacy rules)
    memory_context = memory_manager.retrieve_context(
        latest_user_text,
        is_private=is_private,
        is_api_request=is_api,
        send_personal_context=settings.api_send_personal_context
    )

    if memory_context:
        system_content = f"{persona_state.content}\n\n{memory_context}"
    else:
        system_content = persona_state.content

    # Prepend persona system prompt (with memory context if applicable) and trim history
    full_messages = [{"role": "system", "content": system_content}] + messages_to_trim
    trimmed_messages = trim_history(full_messages, max_tokens=settings.max_context_tokens)

    # Re-read fresh API key if changed in environment
    api_adapter.api_key = settings.get_api_key()

    response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
    response.headers["X-Conversation-Id"] = conv_id
    if persona_state.notice:
        response.headers["X-Persona-Notice"] = persona_state.notice

    if req.stream:
        async def event_generator():
            accumulated_chunks = []
            used_backend = "local"
            used_model = settings.default_local_model
            stream_notice = persona_state.notice

            # Initial metadata payload
            init_meta = {
                "type": "meta",
                "conversation_id": conv_id,
                "persona_fallback": persona_state.is_fallback,
                "notice": persona_state.notice,
                "is_private": is_private,
                "logged_by_provider": settings.api_logged_by_provider
            }
            yield f"data: {json.dumps(init_meta)}\n\n"

            async for event in model_router.stream_chat(
                trimmed_messages,
                user_prompt=latest_user_text,
                is_private=is_private,
                last_backend=last_backend
            ):
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

            full_response = "".join(accumulated_chunks)
            if full_response.strip():
                # Persist message with model & backend
                history_manager.add_message(
                    conv_id,
                    "assistant",
                    full_response,
                    model=used_model,
                    backend=used_backend
                )
                # Log interaction
                history_manager.log_interaction(
                    conv_id=conv_id,
                    user_prompt=latest_user_text,
                    answer=full_response,
                    model=used_model,
                    backend=used_backend
                )
                # Background memory extraction using LOCAL model (never API)
                if not is_private and settings.memory_enabled and settings.memory_extract_after_each_turn:
                    import asyncio
                    asyncio.create_task(
                        memory_manager.extract_and_store(
                            conversation_id=conv_id,
                            user_message=latest_user_text,
                            assistant_message=full_response,
                            is_private=is_private
                        )
                    )

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
        used_model = settings.default_local_model
        used_notice = persona_state.notice

        async for event in model_router.stream_chat(
            trimmed_messages,
            user_prompt=latest_user_text,
            is_private=is_private,
            last_backend=last_backend
        ):
            accumulated_chunks.append(event["chunk"])
            used_backend = event["backend"]
            used_model = event["model"]
            if event.get("notice"):
                used_notice = event["notice"]

        content = "".join(accumulated_chunks)
        history_manager.add_message(
            conv_id,
            "assistant",
            content,
            model=used_model,
            backend=used_backend
        )
        history_manager.log_interaction(
            conv_id=conv_id,
            user_prompt=latest_user_text,
            answer=content,
            model=used_model,
            backend=used_backend
        )
        if content.strip():
            if not is_private and settings.memory_enabled and settings.memory_extract_after_each_turn:
                import asyncio
                asyncio.create_task(
                    memory_manager.extract_and_store(
                        conversation_id=conv_id,
                        user_message=latest_user_text,
                        assistant_message=content,
                        is_private=is_private
                    )
                )
        return ChatResponse(
            role="assistant",
            content=content,
            model=used_model,
            backend=used_backend,
            conversation_id=conv_id,
            persona_fallback=persona_state.is_fallback,
            notice=used_notice
        )
