import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.config import get_settings
from backend.models.ollama_adapter import OllamaAdapter
from backend.persona import PersonaManager

router = APIRouter()
settings = get_settings()
adapter = OllamaAdapter(host=settings.local_host, default_model=settings.default_local_model)
persona_manager = PersonaManager(file_path=settings.persona_file)

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]
    model: Optional[str] = None
    stream: Optional[bool] = True

class ChatResponse(BaseModel):
    role: str
    content: str
    model: str
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

    # Hot-reload persona if modified, or fallback to neutral prompt
    persona_state = persona_manager.get_persona()

    # Prepend persona system prompt; discard any client-provided system role
    user_assistant_messages = [
        {"role": m.role, "content": m.content}
        for m in req.messages
        if m.role != "system"
    ]
    messages_with_persona = [
        {"role": "system", "content": persona_state.content}
    ] + user_assistant_messages

    model_name = req.model or settings.default_local_model

    response.headers["X-Persona-Fallback"] = str(persona_state.is_fallback).lower()
    if persona_state.notice:
        response.headers["X-Persona-Notice"] = persona_state.notice

    if req.stream:
        async def event_generator():
            # Send initial metadata about persona notice
            meta_payload = json.dumps({
                "type": "meta",
                "persona_fallback": persona_state.is_fallback,
                "notice": persona_state.notice
            })
            yield f"data: {meta_payload}\n\n"

            async for chunk in adapter.stream_chat(messages_with_persona, model=model_name):
                payload = json.dumps({
                    "type": "chunk",
                    "chunk": chunk,
                    "model": model_name,
                    "persona_fallback": persona_state.is_fallback,
                    "notice": persona_state.notice
                })
                yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Persona-Fallback": str(persona_state.is_fallback).lower(),
                "X-Persona-Notice": persona_state.notice or ""
            }
        )
    else:
        content = await adapter.chat(messages_with_persona, model=model_name)
        return ChatResponse(
            role="assistant",
            content=content,
            model=model_name,
            persona_fallback=persona_state.is_fallback,
            notice=persona_state.notice
        )
