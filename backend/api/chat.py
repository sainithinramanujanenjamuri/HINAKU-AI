import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.config import get_settings
from backend.models.ollama_adapter import OllamaAdapter
from backend.persona import PersonaManager
from backend.history import ChatHistoryManager, trim_history

router = APIRouter()
settings = get_settings()
adapter = OllamaAdapter(
    host=settings.local_host,
    default_model=settings.default_local_model,
    default_options=settings.local_options,
    default_think=settings.local_think
)
persona_manager = PersonaManager(file_path=settings.persona_file)
history_manager = ChatHistoryManager(db_path=settings.sqlite_path)

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
    conversation_id: str
    persona_fallback: bool = False
    notice: Optional[str] = None

@router.get("/info")
async def get_info():
    health = await adapter.check_health()
    persona_state = persona_manager.get_persona()
    return {
        "app_name": settings.app_name,
        "default_model": settings.default_local_model,
        "allowed_models": settings.allowed_local_models,
        "provider": "ollama (local)",
        "ollama_status": health,
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
        history_manager.create_conversation(conv_id=conv_id)

    # Save latest user message to SQLite history
    latest_msg = req.messages[-1]
    if latest_msg.role == "user":
        history_manager.add_message(conv_id, "user", latest_msg.content)

    # Load full conversation history from SQLite for robust context
    conv_data = history_manager.get_conversation(conv_id)
    db_messages = conv_data.get("messages", []) if conv_data else []

    # Map to role and content, trimming to max_context_tokens
    messages_to_trim = [{"role": m["role"], "content": m["content"]} for m in db_messages]
    if not messages_to_trim:
        # Fallback to request messages if db read was empty
        messages_to_trim = [
            {"role": m.role, "content": m.content}
            for m in req.messages
            if m.role != "system"
        ]

    # Prepend system prompt and trim history to max_context_tokens
    full_messages = [{"role": "system", "content": persona_state.content}] + messages_to_trim
    trimmed_messages = trim_history(full_messages, max_tokens=settings.max_context_tokens)

    model_name = req.model or settings.default_local_model

    response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
    response.headers["X-Conversation-Id"] = conv_id
    if persona_state.notice:
        response.headers["X-Persona-Notice"] = persona_state.notice

    if req.stream:
        async def event_generator():
            # Initial metadata payload
            meta_payload = json.dumps({
                "type": "meta",
                "conversation_id": conv_id,
                "persona_fallback": persona_state.is_fallback,
                "notice": persona_state.notice
            })
            yield f"data: {meta_payload}\n\n"

            accumulated_chunks = []
            async for chunk in adapter.stream_chat(trimmed_messages, model=model_name):
                accumulated_chunks.append(chunk)
                payload = json.dumps({
                    "type": "chunk",
                    "chunk": chunk,
                    "model": model_name,
                    "conversation_id": conv_id,
                    "persona_fallback": persona_state.is_fallback,
                    "notice": persona_state.notice
                })
                yield f"data: {payload}\n\n"

            # Persist assistant response to SQLite
            full_response = "".join(accumulated_chunks)
            if full_response.strip():
                history_manager.add_message(conv_id, "assistant", full_response, model=model_name)

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
        content = await adapter.chat(trimmed_messages, model=model_name)
        history_manager.add_message(conv_id, "assistant", content, model=model_name)
        return ChatResponse(
            role="assistant",
            content=content,
            model=model_name,
            conversation_id=conv_id,
            persona_fallback=persona_state.is_fallback,
            notice=persona_state.notice
        )
