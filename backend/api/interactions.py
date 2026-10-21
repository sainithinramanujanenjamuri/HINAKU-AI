from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from backend.config import get_settings
from backend.history import _UNSET

router = APIRouter(tags=["interactions"])

class FeedbackRequest(BaseModel):
    feedback: Optional[str] = None  # "thumbs_up", "thumbs_down", or None
    edited_answer: Optional[str] = None

class EditMessageRequest(BaseModel):
    edited_answer: str

def get_history_mgr():
    from backend.api.chat import history_manager
    return history_manager

@router.post("/interactions/{interaction_id}/feedback")
async def update_interaction_feedback_endpoint(interaction_id: str, req: FeedbackRequest):
    if req.feedback is not None and req.feedback not in ("thumbs_up", "thumbs_down"):
        raise HTTPException(status_code=400, detail="Invalid feedback value. Must be 'thumbs_up', 'thumbs_down', or null.")
    
    hm = get_history_mgr()
    ok = hm.update_interaction_feedback(
        interaction_id=interaction_id,
        feedback=req.feedback,
        edited_answer=req.edited_answer if req.edited_answer is not None else _UNSET
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Interaction not found")
    
    inter = hm.get_interaction(interaction_id)
    return {
        "success": True,
        "interaction_id": interaction_id,
        "feedback": inter.get("feedback") if inter else req.feedback,
        "edited_answer": inter.get("edited_answer") if inter else req.edited_answer
    }

@router.get("/interactions/{interaction_id}")
async def get_interaction_endpoint(interaction_id: str):
    hm = get_history_mgr()
    inter = hm.get_interaction(interaction_id)
    if not inter:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return inter

@router.post("/messages/{message_id}/feedback")
async def update_message_feedback_endpoint(message_id: str, req: FeedbackRequest):
    if req.feedback is not None and req.feedback not in ("thumbs_up", "thumbs_down"):
        raise HTTPException(status_code=400, detail="Invalid feedback value. Must be 'thumbs_up', 'thumbs_down', or null.")
    
    hm = get_history_mgr()
    msg = hm.get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    ok = hm.update_interaction_feedback(
        message_id=message_id,
        feedback=req.feedback,
        edited_answer=req.edited_answer if req.edited_answer is not None else _UNSET
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record feedback")
    
    inter = hm.get_interaction_by_message_id(message_id)
    return {
        "success": True,
        "message_id": message_id,
        "interaction_id": inter.get("id") if inter else None,
        "feedback": req.feedback,
        "edited_answer": inter.get("edited_answer") if inter else req.edited_answer
    }

@router.post("/messages/{message_id}/edit")
async def edit_message_endpoint(message_id: str, req: EditMessageRequest):
    edited = req.edited_answer.strip()
    if not edited:
        raise HTTPException(status_code=400, detail="Edited answer cannot be empty")
    
    hm = get_history_mgr()
    msg = hm.get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Update content in messages table
    hm.update_message_content(message_id, edited)
    
    # Update or create interaction record
    hm.update_interaction_feedback(message_id=message_id, edited_answer=edited)
    inter = hm.get_interaction_by_message_id(message_id)

    return {
        "success": True,
        "message_id": message_id,
        "interaction_id": inter.get("id") if inter else None,
        "edited_answer": edited
    }
