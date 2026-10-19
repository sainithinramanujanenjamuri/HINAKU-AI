from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.config import get_settings
from backend.history import ChatHistoryManager

router = APIRouter()
settings = get_settings()
history_manager = ChatHistoryManager(db_path=settings.sqlite_path)

class CreateConversationRequest(BaseModel):
    title: Optional[str] = "New conversation"

class RenameConversationRequest(BaseModel):
    title: str

@router.get("/conversations")
async def list_conversations():
    return history_manager.list_conversations()

@router.post("/conversations")
async def create_conversation(req: CreateConversationRequest):
    return history_manager.create_conversation(title=req.title or "New conversation")

@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = history_manager.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

@router.patch("/conversations/{conv_id}")
async def rename_conversation(conv_id: str, req: RenameConversationRequest):
    conv = history_manager.rename_conversation(conv_id, req.title)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    deleted = history_manager.delete_conversation(conv_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "id": conv_id}
