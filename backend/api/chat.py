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

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    stream: Optional[bool] = True

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
    is_private = False
    if not conv:
        history_manager.create_conversation(conv_id=conv_id)
    else:
        is_private = conv.get("is_private", False)

    # Save latest user message to SQLite history
    latest_msg = req.messages[-1]
    latest_user_text = latest_msg.content if latest_msg.role == "user" else ""
    if latest_msg.role == "user":
        history_manager.add_message(conv_id, "user", latest_msg.content)

    # Load full conversation history from SQLite for robust context
    conv_data = history_manager.get_conversation(conv_id)
    db_messages = conv_data.get("messages", []) if conv_data else []

    messages_to_trim = [{"role": m["role"], "content": m["content"]} for m in db_messages]
    if not messages_to_trim:
        messages_to_trim = [
            {"role": m.role, "content": m.content}
            for m in req.messages
            if m.role != "system"
        ]

    # Prepend persona system prompt and trim history to max_context_tokens
    full_messages = [{"role": "system", "content": persona_state.content}] + messages_to_trim
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
                "is_private": is_private
            }
            yield f"data: {json.dumps(init_meta)}\n\n"

            async for event in model_router.stream_chat(
                trimmed_messages,
                user_prompt=latest_user_text,
                is_private=is_private
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
                    "notice": stream_notice
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
            is_private=is_private
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
        return ChatResponse(
            role="assistant",
            content=content,
            model=used_model,
            backend=used_backend,
            conversation_id=conv_id,
            persona_fallback=persona_state.is_fallback,
            notice=used_notice
        )
