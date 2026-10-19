import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.config import get_settings
from backend.models.ollama_adapter import OllamaAdapter

router = APIRouter()
settings = get_settings()
adapter = OllamaAdapter(host=settings.local_host, default_model=settings.default_local_model)

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

@router.get("/info")
async def get_info():
    health = await adapter.check_health()
    return {
        "app_name": settings.app_name,
        "default_model": settings.default_local_model,
        "allowed_models": settings.allowed_local_models,
        "provider": "ollama (local)",
        "ollama_status": health,
        "reduced_motion": settings.app.get("reduced_motion", False)
    }

@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    dict_messages = [{"role": m.role, "content": m.content} for m in req.messages]
    model_name = req.model or settings.default_local_model

    if req.stream:
        async def event_generator():
            async for chunk in adapter.stream_chat(dict_messages, model=model_name):
                payload = json.dumps({"chunk": chunk, "model": model_name})
                yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        content = await adapter.chat(dict_messages, model=model_name)
        return ChatResponse(role="assistant", content=content, model=model_name)

