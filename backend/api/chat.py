from datetime import datetime
import json
import re
import time
import uuid
import logging
from typing import List, Optional, Dict, Any, Tuple
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
from backend.api.attachments import attachment_manager
from backend.quality import (
    verify_reply,
    count_sentences,
    trim_to_four_sentences,
    detect_forbidden_offers,
    fix_clock_error_in_code,
    detect_hardware_conflict,
    perform_reply_verification
)
from backend.guards import (
    check_and_redact_sensitive_data,
    is_live_data_query,
    is_clock_query,
    get_clock_reply,
    get_system_clock_context
)
from backend.models.ollama_shared import log_ollama_call
from backend.attachments.intent import is_overview_intent, extract_target_unit

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
    verify_status: Optional[str] = None
    verify_reason: Optional[str] = None
    think_harder_used: bool = False
    detailed_used: bool = False
    hit_token_limit: bool = False
    is_private: bool = False
    latency_breakdown: Optional[Dict[str, int]] = None
    options: Optional[Dict[str, Any]] = None
    citations: Optional[List[Dict[str, Any]]] = None

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
    t_req_start = time.perf_counter()
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    memory_manager.notify_user_message_received()

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

    # Sensitive Topic Detection (mental health, mood, health, money trouble, personal relationships)
    from backend.guards import is_sensitive_topic, is_hopelessness_or_self_harm
    is_sensitive_topic_found, sensitive_topic_category = is_sensitive_topic(latest_user_text)
    auto_private_triggered = False
    auto_private_notice_text = None
    is_despair = is_hopelessness_or_self_harm(latest_user_text)
    if is_sensitive_topic_found and not is_private:
        is_private = True
        auto_private_triggered = True
        history_manager.set_conversation_privacy(conv_id, True)
        topic_label = sensitive_topic_category.replace("_", " ")
        auto_private_notice_text = f"Sensitive topic detected ({topic_label}). Marked conversation as Private to keep your data local, skip memory extraction, and exclude it from training."
        if is_despair and settings.helpline_numbers:
            lines = [f"{h.get('name')}: {h.get('number')}" for h in settings.helpline_numbers if h.get('name') and h.get('number')]
            if lines:
                auto_private_notice_text += " Support is available: " + "; ".join(lines)

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

    guards_ms = int((time.perf_counter() - t_req_start) * 1000)

    from backend.guards import is_detail_request, trim_to_last_complete_sentence

    is_detail = bool(req.detailed) or is_detail_request(latest_user_text)

    # Check for document attachments (forces local model)
    has_attachments = attachment_manager.has_attachments(conv_id)

    # Identify target backend for memory retrieval privacy rule
    t_router_start = time.perf_counter()
    router_decision = model_router.decide_backend(
        latest_user_text,
        is_private=is_private,
        last_backend=last_backend,
        is_detail=is_detail,
        has_attachments=has_attachments,
        requested_model=req.model
    )
    router_ms = int((time.perf_counter() - t_router_start) * 1000)
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
    if is_api:
        persona_text += "\n\nDo not use LaTeX or mathematical dollar signs ($...$ or $$...$$). Use standard Unicode characters (e.g. →, ×, ≤, ≥, ≠, ·, etc.) for symbols and equations."
    if is_detail and not has_attachments:
        persona_text += "\nExplain in about 250 words ending with a one-sentence conclusion. Do not open with 'Okay, let's break down' or similar filler; begin directly with the answer."
    system_parts = [persona_text, clock_context]
    if memory_context:
        system_parts.append(memory_context)
    coverage_meta = {"sections": [], "pages": []}
    t_att_start = time.perf_counter()
    if has_attachments:
        doc_context, coverage_meta = attachment_manager.get_document_prompt_context(conv_id, latest_user_text)
        if doc_context:
            system_parts.append(doc_context)
    attachment_ms = int((time.perf_counter() - t_att_start) * 1000)

    t_prompt_start = time.perf_counter()
    if is_despair:
        helpline_lines = [f"{h.get('name')}: {h.get('number')}" for h in settings.helpline_numbers if h.get('name') and h.get('number')]
        hl_info = f" Available helplines: {'; '.join(helpline_lines)}." if helpline_lines else " No external helplines are configured."
        system_parts.append(
            f"Guidance: The user's message suggests feelings of hopelessness or self-harm. "
            f"Respond with warmth and brevity. Do not sound clinical, do not diagnose, and do not provide long lists of techniques. "
            f"Ask gently about their safety and encourage contacting a trusted person or a local helpline.{hl_info} "
            f"Never invent or guess phone numbers or helpline names."
        )
    system_content = "\n\n".join(system_parts)

    # Prepend persona system prompt (with memory context if applicable) and trim history
    full_messages = [{"role": "system", "content": system_content}] + messages_to_trim
    trimmed_messages = trim_history(full_messages, max_tokens=settings.max_context_tokens)
    prompt_assembly_ms = int((time.perf_counter() - t_prompt_start) * 1000)

    # Re-read fresh API key if changed in environment
    api_adapter.api_key = settings.get_api_key()

    target_model = req.model if (req.model and (req.model in settings.allowed_local_models or req.model == settings.api_model)) else settings.default_local_model
    target_opts = dict(settings.get_model_options(target_model))
    if target_model == "bonsai-2:9b":
        target_opts["num_ctx"] = 8192
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
            was_cut = False
            message_actions = []

            # Initial metadata payload
            if auto_private_triggered:
                auto_priv_payload = {"type": "auto_private_notice", "notice": auto_private_notice_text, "auto_private": True, "undo_available": True, "conversation_id": conv_id}
                yield f"data: {json.dumps(auto_priv_payload)}\n\n"

            init_meta = {
                "type": "meta",
                "conversation_id": conv_id,
                "persona_fallback": persona_state.is_fallback,
                "notice": auto_private_notice_text or persona_state.notice,
                "is_private": is_private,
                "auto_private": auto_private_triggered,
                "logged_by_provider": settings.api_logged_by_provider,
                "think_harder_used": think_harder_used,
                "detailed_used": is_detail,
                "options": target_opts
            }
            yield f"data: {json.dumps(init_meta)}\n\n"

            if not is_api:
                try:
                    is_loaded = await local_adapter.is_model_loaded(target_model)
                    if not is_loaded:
                        loading_notice = {
                            "type": "notice",
                            "notice": "Loading model... about 15 s",
                            "loading_model": True,
                            "model": target_model,
                            "conversation_id": conv_id
                        }
                        yield f"data: {json.dumps(loading_notice)}\n\n"
                except Exception:
                    pass

            t_gen_start = time.perf_counter()
            t_ttft = None
            encountered_error = None

            if has_attachments and is_overview_intent(latest_user_text):
                # WALKTHROUGH FLOW (One model call per topic in order, cached in SQLite)
                from pathlib import Path
                prompt_file = Path("config/prompts/study_explainer.md")
                explainer_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "Explain from basics with examples."

                sections = attachment_manager.get_sections(conv_id)
                summary = attachment_manager.get_document_outline_summary(conv_id)
                target_unit = extract_target_unit(latest_user_text) or 1

                unit_sections = [s for s in sections if f"UNIT {target_unit}" in (s.get("unit_name") or "").upper()]
                if not unit_sections:
                    unit_sections = sections

                total_all_topics = summary.get("total_topics") or len(sections)
                doc_title = summary.get("title") or "Study Notes"
                unit_name = unit_sections[0].get("unit_name") if unit_sections else f"Unit {target_unit}"
                intro_desc = summary.get("intro_desc") or f"{total_all_topics} main topics across {len(summary.get('units') or [1])} units"

                unit_total_topics = len(unit_sections)
                # Measured average per topic including draft + style check/addendum + verification
                measured_avg_per_topic = 19.5
                initial_est_seconds = round(measured_avg_per_topic * unit_total_topics)
                initial_low = round(initial_est_seconds * 0.85)
                initial_high = round(initial_est_seconds * 1.15)
                prev_remaining_estimate = initial_est_seconds
                t_walkthrough_start = time.perf_counter()

                # Walkthrough options: allow up to 800 tokens so full explanation, example, and takeaways fit
                walkthrough_opts = dict(target_opts)
                walkthrough_opts["num_predict"] = max(target_opts.get("num_predict", 300), 800)

                # Full document text for global faithfulness grounding
                full_doc_text = "\n\n".join(s.get("text", "") for s in sections)

                # 1. Deterministic structure preamble
                intro_text = (
                    f"**{doc_title}**\n\n"
                    f"Your notes contain **{intro_desc}**. "
                    f"We'll learn them step by step starting with **{unit_name}** (~{initial_est_seconds}s estimated, range {initial_low}–{initial_high}s).\n\n"
                    "---\n"
                )
                if t_ttft is None:
                    t_ttft = time.perf_counter()
                accumulated_chunks.append(intro_text)
                yield f"data: {json.dumps({'type': 'chunk', 'chunk': intro_text, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"

                from backend.attachments.faithfulness import verify_explanation_faithfulness
                from backend.attachments.style_checker import check_study_style, build_addendum_prompt, check_and_fix_count_consistency

                # 2. Iterate topic by topic
                for idx, sec in enumerate(unit_sections, 1):
                    sec_title = sec["title"]
                    topic_num = sec.get("topic_number") or idx
                    rem_topics = unit_total_topics - (idx - 1)
                    if idx == 1:
                        current_topic_estimate = initial_est_seconds
                        low_est = initial_low
                        high_est = initial_high
                    else:
                        elapsed_total = time.perf_counter() - t_walkthrough_start
                        rolling_avg = elapsed_total / (idx - 1)
                        calc_est = round(rolling_avg * rem_topics)
                        current_topic_estimate = min(prev_remaining_estimate, max(1, calc_est))
                        low_est = max(1, round(current_topic_estimate * 0.85))
                        high_est = max(low_est, round(current_topic_estimate * 1.15))
                    prev_remaining_estimate = current_topic_estimate

                    progress_msg = f"Explaining topic {idx} of {unit_total_topics} (~{current_topic_estimate}s remaining, range {low_est}–{high_est}s)"
                    logger.info(
                        f"[Walkthrough Estimate] Topic {idx}/{unit_total_topics}: "
                        f"elapsed={time.perf_counter() - t_walkthrough_start:.1f}s | "
                        f"remaining={current_topic_estimate}s (range {low_est}-{high_est}s)"
                    )
                    yield f"data: {json.dumps({'type': 'walkthrough_progress', 'notice': progress_msg, 'current': idx, 'total': unit_total_topics, 'estimated_remaining_seconds': current_topic_estimate, 'topic': sec_title, 'conversation_id': conv_id})}\n\n"

                    # Check cache in SQLite
                    cached = sec.get("explanation_cache")
                    if cached:
                        cached_block = f"\n\n### {sec_title}\n\n{cached}\n\n"
                        accumulated_chunks.append(cached_block)
                        yield f"data: {json.dumps({'type': 'chunk', 'chunk': cached_block, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"
                        continue

                    # Stream generation from model
                    header_block = f"\n\n### {sec_title}\n\n"
                    accumulated_chunks.append(header_block)
                    yield f"data: {json.dumps({'type': 'chunk', 'chunk': header_block, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"

                    sec_user_prompt = f"Topic to explain:\nTitle: {sec_title}\n\nNotes Text:\n{sec['text']}"
                    topic_messages = [
                        {"role": "system", "content": explainer_prompt},
                        {"role": "user", "content": sec_user_prompt}
                    ]

                    topic_t0 = time.perf_counter()
                    topic_accumulated = []
                    is_first_chunk = True
                    draft_tokens = 0
                    async for chunk_evt in local_adapter.stream_chat(
                        model=target_model,
                        messages=topic_messages,
                        options=walkthrough_opts,
                        think=False
                    ):
                        c = chunk_evt if isinstance(chunk_evt, str) else chunk_evt.get("chunk", "")
                        if c:
                            # Strip any redundant leading heading emitted by the model
                            if is_first_chunk and (c.startswith("#") or c.startswith("**")) and sec_title.lower() in c.lower():
                                continue
                            is_first_chunk = False
                            draft_tokens += 1
                            topic_accumulated.append(c)
                            accumulated_chunks.append(c)
                            yield f"data: {json.dumps({'type': 'chunk', 'chunk': c, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"

                    draft_duration_s = time.perf_counter() - topic_t0
                    full_sec_explanation = "".join(topic_accumulated).strip()
                    # Inner section labels formatting: normalize inner ### to ####
                    full_sec_explanation = re.sub(r"(?m)^###\s+(\*\*[^*]+\*\*):?", r"#### \1", full_sec_explanation)
                    full_sec_explanation = re.sub(r"(?m)^###\s+", r"#### ", full_sec_explanation)
                    draft_load_ms = round((getattr(local_adapter, "last_load_duration", 0) or 0) / 1e6, 2)
                    topic_calls = [
                        {
                            "call_type": "draft",
                            "ms": int(draft_duration_s * 1000),
                            "tokens": draft_tokens,
                            "load_duration_ms": draft_load_ms
                        }
                    ]
                    logger.info(
                        f"[Walkthrough Call: Draft] [Topic {topic_num}/{total_all_topics}: '{sec_title}'] "
                        f"duration={draft_duration_s*1000:.1f}ms | tokens={draft_tokens} | "
                        f"load_duration={draft_load_ms}ms"
                    )

                    # 3. Count consistency check and fix
                    t_count_0 = time.perf_counter()
                    was_count_fixed, full_sec_explanation, count_fixes = check_and_fix_count_consistency(full_sec_explanation, section_text=sec.get("text", ""))
                    count_ms = int((time.perf_counter() - t_count_0) * 1000)
                    topic_calls.append({
                        "call_type": "count_check",
                        "ms": count_ms,
                        "fixed": was_count_fixed,
                        "fixes": count_fixes
                    })
                    if was_count_fixed:
                        logger.info(f"Count consistency corrected in '{sec_title}': {count_fixes}")

                    # 4. Style verification: check for example and takeaways
                    t_style_0 = time.perf_counter()
                    style_res = check_study_style(full_sec_explanation)
                    style_check_ms = int((time.perf_counter() - t_style_0) * 1000)
                    if not style_res["is_complete"]:
                        logger.info(
                            f"Style check in '{sec_title}': missing {style_res['missing_parts']}. "
                            f"Triggering short addendum generation."
                        )
                        addendum_prompt = build_addendum_prompt(
                            missing_parts=style_res["missing_parts"],
                            sec_title=sec_title,
                            sec_text=sec["text"],
                            existing_explanation=full_sec_explanation
                        )
                        addendum_messages = [
                            {"role": "system", "content": "You are a concise study assistant generating missing study components. Follow the instructions strictly."},
                            {"role": "user", "content": addendum_prompt}
                        ]
                        addendum_t0 = time.perf_counter()
                        addendum_chunks = ["\n\n"]
                        addendum_tokens = 0
                        async for a_evt in local_adapter.stream_chat(
                            model=target_model,
                            messages=addendum_messages,
                            options={"num_ctx": 8192, "num_predict": 400, "temperature": 0.5},
                            think=False
                        ):
                            a_str = a_evt if isinstance(a_evt, str) else a_evt.get("chunk", "")
                            if a_str:
                                addendum_tokens += 1
                                addendum_chunks.append(a_str)
                                accumulated_chunks.append(a_str)
                                yield f"data: {json.dumps({'type': 'chunk', 'chunk': a_str, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"

                        addendum_duration_s = time.perf_counter() - addendum_t0
                        addendum_text = "".join(addendum_chunks).strip()
                        full_sec_explanation += "\n\n" + addendum_text
                        addendum_load_ms = round((getattr(local_adapter, "last_load_duration", 0) or 0) / 1e6, 2)
                        topic_calls.append({
                            "call_type": "style_addendum",
                            "ms": int(addendum_duration_s * 1000),
                            "tokens": addendum_tokens,
                            "load_duration_ms": addendum_load_ms,
                            "missing_parts": style_res["missing_parts"]
                        })
                        logger.info(
                            f"[Walkthrough Call: Addendum] [Topic {topic_num}/{total_all_topics}: '{sec_title}'] "
                            f"duration={addendum_duration_s*1000:.1f}ms | tokens={addendum_tokens} | "
                            f"load_duration={addendum_load_ms}ms | components={style_res['missing_parts']}"
                        )
                    else:
                        topic_calls.append({
                            "call_type": "style_check",
                            "ms": style_check_ms,
                            "complete": True
                        })

                    # 5. Faithfulness check across document
                    t_faith_0 = time.perf_counter()
                    is_faithful, missing_terms, checked_text = verify_explanation_faithfulness(
                        explanation_text=full_sec_explanation,
                        section_text=sec["text"],
                        full_document_text=full_doc_text,
                        sec_title=sec_title
                    )
                    faith_ms = int((time.perf_counter() - t_faith_0) * 1000)
                    topic_calls.append({
                        "call_type": "faithfulness_check",
                        "ms": faith_ms,
                        "faithful": is_faithful,
                        "missing_terms": missing_terms
                    })
                    if not is_faithful:
                        logger.info(f"Faithfulness check triggered for '{sec_title}': ungrounded terms {missing_terms}. Running single-pass regeneration.")
                        regen_prompt = (
                            f"{sec_user_prompt}\n\n"
                            f"Important requirement: Use the exact terms and step names from the notes. "
                            f"Do not substitute, invent, or generalize step names."
                        )
                        regen_msgs = [
                            {"role": "system", "content": explainer_prompt},
                            {"role": "user", "content": regen_prompt}
                        ]
                        regen_t0 = time.perf_counter()
                        regen_chunks = []
                        regen_tokens = 0
                        async for c_evt in local_adapter.stream_chat(
                            model=target_model,
                            messages=regen_msgs,
                            options=walkthrough_opts,
                            think=False
                        ):
                            c_str = c_evt if isinstance(c_evt, str) else c_evt.get("chunk", "")
                            if c_str:
                                regen_tokens += 1
                                regen_chunks.append(c_str)
                        regen_duration_s = time.perf_counter() - regen_t0
                        regen_explanation = "".join(regen_chunks).strip()
                        regen_load_ms = round((getattr(local_adapter, "last_load_duration", 0) or 0) / 1e6, 2)
                        topic_calls.append({
                            "call_type": "faithfulness_regen",
                            "ms": int(regen_duration_s * 1000),
                            "tokens": regen_tokens,
                            "load_duration_ms": regen_load_ms
                        })
                        logger.info(
                            f"[Walkthrough Call: Regeneration] [Topic {topic_num}/{total_all_topics}: '{sec_title}'] "
                            f"duration={regen_duration_s*1000:.1f}ms | tokens={regen_tokens} | "
                            f"load_duration={regen_load_ms}ms"
                        )
                        is_regen_faithful, missing_regen, final_annotated = verify_explanation_faithfulness(
                            explanation_text=regen_explanation,
                            section_text=sec["text"],
                            full_document_text=full_doc_text,
                            sec_title=sec_title
                        )
                        if is_regen_faithful:
                            full_sec_explanation = regen_explanation
                        else:
                            full_sec_explanation = final_annotated

                    t_db_cache = time.perf_counter()
                    if full_sec_explanation:
                        attachment_manager.update_section_cache(sec["id"], full_sec_explanation)
                    db_cache_ms = int((time.perf_counter() - t_db_cache) * 1000)
                    topic_calls.append({
                        "call_type": "db_cache_write",
                        "ms": db_cache_ms
                    })

                    actual_duration_s = time.perf_counter() - topic_t0
                    rolling_sec_per_topic = (rolling_sec_per_topic * (idx - 1) + actual_duration_s) / idx
                    logger.info(
                        f"[Walkthrough Timing] [Topic {topic_num}/{total_all_topics}] "
                        f"Estimated: {current_topic_estimate}s | Actual: {actual_duration_s:.2f}s | "
                        f"Rolling Avg: {rolling_sec_per_topic:.2f}s/topic"
                    )

                    yield f"data: {json.dumps({'type': 'topic_calls', 'topic_idx': idx, 'topic_num': topic_num, 'total_topics': unit_total_topics, 'title': sec_title, 'calls': topic_calls, 'topic_duration_ms': int(actual_duration_s * 1000), 'rolling_sec_per_topic': round(rolling_sec_per_topic, 2), 'remaining_seconds': current_topic_estimate})}\n\n"

                # Check if next unit exists
                next_unit = target_unit + 1
                has_next = any(f"UNIT {next_unit}" in (s.get("unit_name") or "").upper() for s in sections)
                if has_next:
                    continue_block = (
                        f"\n\n---\n\n"
                        f"**Unit {target_unit} Complete.**\n"
                    )
                    accumulated_chunks.append(continue_block)
                    yield f"data: {json.dumps({'type': 'chunk', 'chunk': continue_block, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"
                    message_actions.append({
                        "label": f"Continue to Unit {next_unit} →",
                        "prompt": f"explain unit {next_unit}",
                        "style": "primary"
                    })

                # Offer study aids at the end of the walkthrough
                study_aids = summary.get("study_aids") or []
                if study_aids:
                    aid_lines = [f"- **{aid}**" for aid in study_aids]
                    aid_block = (
                        f"\n\n---\n\n"
                        f"### 📚 Available Study Aids\n\n"
                        f"Your notes include **{len(study_aids)} study aids** (reference materials):\n"
                        + "\n".join(aid_lines)
                        + "\n"
                    )
                    accumulated_chunks.append(aid_block)
                    yield f"data: {json.dumps({'type': 'chunk', 'chunk': aid_block, 'backend': 'local', 'model': target_model, 'conversation_id': conv_id})}\n\n"
                    message_actions.append({
                        "label": "Explain All Study Aids →",
                        "prompt": "explain the study aids",
                        "style": "highlight"
                    })
                    for aid in study_aids:
                        message_actions.append({
                            "label": f"Explain {aid} →",
                            "prompt": f"explain {aid}",
                            "style": "secondary"
                        })

                if message_actions:
                    yield f"data: {json.dumps({'type': 'actions', 'actions': message_actions, 'conversation_id': conv_id})}\n\n"
            else:
                async for event in model_router.stream_chat(
                    trimmed_messages,
                    user_prompt=latest_user_text,
                    is_private=is_private,
                    last_backend=last_backend,
                    override_model=target_model,
                    think=use_think,
                    options=target_opts,
                    is_detail=is_detail,
                    has_attachments=has_attachments,
                    requested_model=req.model
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
                    if event.get("chunk") and t_ttft is None:
                        t_ttft = time.perf_counter()
                    accumulated_chunks.append(event["chunk"])
                    yield f"data: {json.dumps(chunk_payload)}\n\n"

            if encountered_error:
                # Do NOT save error to DB, do NOT log to interactions or datasets
                yield "data: [DONE]\n\n"
                return

            gen_ms = int((time.perf_counter() - t_gen_start) * 1000)
            draft_reply = "".join(accumulated_chunks)

            # If reply hit token limit (ends mid-sentence), cut back to last complete sentence (chat turns only)
            if not has_attachments:
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
            final_reply, was_verified, verify_ms, verify_status, verify_reason = await perform_reply_verification(
                draft_reply=draft_reply,
                used_backend=used_backend,
                used_model=used_model,
                target_opts=target_opts,
                persona_state=persona_state,
                clock_context=clock_context,
                memory_context=memory_context or "",
                is_detail=is_detail,
                local_adapter=local_adapter,
                settings=settings,
                messages_for_regen=trimmed_messages,
                has_attachments=has_attachments
            )
            if not draft_reply.strip():
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
            elif final_reply != draft_reply:
                # Safeguard: Never replace with reply shorter than 60% of streamed draft (except guards)
                if used_backend != "guard" and len(final_reply) < 0.60 * len(draft_reply):
                    logger.warning(
                        f"Safeguard prevented correction: final length {len(final_reply)} is < 60% of "
                        f"streamed draft ({len(draft_reply)}). Keeping original streamed draft."
                    )
                    final_reply = draft_reply
                else:
                    corr_payload = {
                        "type": "correction",
                        "final_content": final_reply,
                        "conversation_id": conv_id
                    }
                    yield f"data: {json.dumps(corr_payload)}\n\n"

            t_post_start = time.perf_counter()
            from backend.attachments.citations import strip_wrapper_tags_and_extract_citations
            final_reply, doc_citations = strip_wrapper_tags_and_extract_citations(final_reply)

            # Strip any raw HTML tags (e.g. <button>, <div>, <script>) to guarantee stored text contains no HTML
            final_reply = re.sub(r"<(script|style|button|a|div|span|p|h[1-6])[^>]*>.*?</\1>", "", final_reply, flags=re.IGNORECASE | re.DOTALL)
            final_reply = re.sub(r"<[^>]+>", "", final_reply).strip()

            if has_attachments and not is_overview_intent(latest_user_text) and doc_context:
                from backend.attachments.citations import format_outline_citations
                coverage_note = format_outline_citations(coverage_meta.get("sections_meta", []))
                if not coverage_note and coverage_meta and coverage_meta.get("sections"):
                    sec_names = ", ".join(coverage_meta["sections"][:2])
                    p_nums = ", ".join(map(str, coverage_meta["pages"][:2]))
                    coverage_note = f"\n\n*Based on {sec_names} (pp. {p_nums}).*"

                if coverage_note:
                    final_reply += coverage_note
                    yield f"data: {json.dumps({'type': 'chunk', 'chunk': coverage_note, 'backend': used_backend, 'model': used_model, 'conversation_id': conv_id})}\n\n"
                    # Emit structured action chip only for document answers
                    message_actions = [{"label": "Explain the whole document →", "prompt": "explain this document to me", "style": "secondary"}]
                    yield f"data: {json.dumps({'type': 'actions', 'actions': message_actions, 'conversation_id': conv_id})}\n\n"
            post_processing_ms = int((time.perf_counter() - t_post_start) * 1000)

            t_db_start = time.perf_counter()
            ast_msg = None
            inter_id = None
            if final_reply.strip():
                # Persist message with model & backend
                ast_msg = history_manager.add_message(
                    conv_id,
                    "assistant",
                    final_reply,
                    model=used_model,
                    backend=used_backend,
                    metadata={"actions": message_actions} if message_actions else None
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
                # Background memory extraction after 5s idle using LOCAL model (never API)
                if not is_private and not has_attachments and settings.memory_enabled and settings.memory_extract_after_each_turn:
                    memory_manager.schedule_extraction(
                        conversation_id=conv_id,
                        user_message=latest_user_text,
                        assistant_message=final_reply,
                        is_private=is_private
                    )
                memory_manager.notify_chat_completed()
                db_writes_ms = int((time.perf_counter() - t_db_start) * 1000)
                total_turn_ms = int((time.perf_counter() - t_req_start) * 1000)
                ttft_ms = int((t_ttft - t_req_start) * 1000) if t_ttft else 0

                latency_breakdown = {
                    "guards_ms": guards_ms,
                    "router_ms": router_ms,
                    "memory_ms": memory_ms,
                    "attachment_ms": attachment_ms,
                    "prompt_assembly_ms": prompt_assembly_ms,
                    "ttft_ms": ttft_ms,
                    "generation_ms": gen_ms,
                    "verify_ms": verify_ms,
                    "think_ms": 0,
                    "post_processing_ms": post_processing_ms,
                    "db_writes_ms": db_writes_ms,
                    "total_ms": total_turn_ms
                }

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
                    "final_reply": final_reply,
                    "citations": doc_citations,
                    "actions": message_actions
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
            is_detail=is_detail,
            has_attachments=has_attachments,
            requested_model=req.model
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

        final_reply, was_verified, verify_ms, verify_status, verify_reason = await perform_reply_verification(
            draft_reply=draft_reply,
            used_backend=used_backend,
            used_model=used_model,
            target_opts=target_opts,
            persona_state=persona_state,
            clock_context=clock_context,
            memory_context=memory_context or "",
            is_detail=is_detail,
            local_adapter=local_adapter,
            settings=settings,
            messages_for_regen=trimmed_messages
        )

        from backend.attachments.citations import strip_wrapper_tags_and_extract_citations, format_outline_citations
        final_reply, doc_citations = strip_wrapper_tags_and_extract_citations(final_reply)

        message_actions = None
        if has_attachments and not is_overview_intent(latest_user_text) and doc_context:
            coverage_note = format_outline_citations(coverage_meta.get("sections_meta", []))
            if not coverage_note and coverage_meta and coverage_meta.get("sections"):
                sec_names = ", ".join(coverage_meta["sections"][:2])
                p_nums = ", ".join(map(str, coverage_meta["pages"][:2]))
                coverage_note = f"\n\n*Based on {sec_names} (pp. {p_nums}).*"
            if coverage_note:
                final_reply += coverage_note
                message_actions = [{"label": "Explain the whole document →", "prompt": "explain this document to me", "style": "secondary"}]

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
            backend=used_backend,
            metadata={"actions": message_actions} if message_actions else None
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
            if not is_private and not has_attachments and settings.memory_enabled and settings.memory_extract_after_each_turn:
                memory_manager.schedule_extraction(
                    conversation_id=conv_id,
                    user_message=latest_user_text,
                    assistant_message=final_reply,
                    is_private=is_private
                )
        memory_manager.notify_chat_completed()
        return ChatResponse(
            role="assistant",
            content=final_reply,
            model=used_model,
            backend=used_backend,
            conversation_id=conv_id,
            persona_fallback=persona_state.is_fallback,
            notice=auto_private_notice_text or used_notice,
            message_id=ast_msg["id"],
            interaction_id=inter_id,
            verified=was_verified,
            verify_status=verify_status,
            verify_reason=verify_reason,
            think_harder_used=think_harder_used,
            detailed_used=is_detail,
            hit_token_limit=was_cut,
            is_private=is_private,
            latency_breakdown=latency_breakdown,
            options=target_opts
        )
