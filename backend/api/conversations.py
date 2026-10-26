from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.config import get_settings
from backend.history import ChatHistoryManager
from backend.attachments import AttachmentManager

router = APIRouter()
settings = get_settings()
history_manager = ChatHistoryManager(db_path=settings.sqlite_path)
attachment_manager = AttachmentManager()

class CreateConversationRequest(BaseModel):
    title: Optional[str] = "New conversation"
    is_private: Optional[bool] = False

class UpdateConversationRequest(BaseModel):
    title: Optional[str] = None
    is_private: Optional[bool] = None
    pinned: Optional[bool] = None

@router.get("/conversations")
async def list_conversations():
    return history_manager.list_conversations()

@router.post("/conversations")
async def create_conversation(req: CreateConversationRequest):
    return history_manager.create_conversation(
        title=req.title or "New conversation",
        is_private=req.is_private or False
    )

@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = history_manager.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

@router.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: str, req: UpdateConversationRequest):
    conv = history_manager.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if req.title is not None:
        conv = history_manager.rename_conversation(conv_id, req.title)
    if req.is_private is not None:
        conv = history_manager.set_conversation_privacy(conv_id, req.is_private)
    if req.pinned is not None:
        conv = history_manager.set_conversation_pinned(conv_id, req.pinned)

    return conv

@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    deleted = history_manager.delete_conversation(conv_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Cascading hard delete of all attachments and vectors
    attachment_manager.delete_conversation_attachments(conv_id)
    return {"status": "deleted", "id": conv_id}
