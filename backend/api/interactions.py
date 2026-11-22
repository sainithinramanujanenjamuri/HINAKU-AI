import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
from backend.config import get_settings
from backend.history import _UNSET
from backend.security.auth import require_session_auth

logger = logging.getLogger("hinaku.interactions")
router = APIRouter(tags=["interactions"])

class FeedbackRequest(BaseModel):
    feedback: Optional[str] = None  # "thumbs_up", "thumbs_down", or None
    edited_answer: Optional[str] = None

class EditMessageRequest(BaseModel):
    edited_answer: str

def get_history_mgr():
    from backend.api.chat import history_manager
    return history_manager

def _log_experience_from_feedback(inter: Optional[Dict[str, Any]], feedback: Optional[str], edited_answer: Optional[str]):
    """Connects interaction feedback and edits to ExperienceLogger with automatic credential redaction."""
    if not inter:
        return
    try:
        from backend.intelligence.experience_logger import ExperienceLogger
        from backend.intelligence.learning_types import FeedbackType
        settings = get_settings()
        exp_logger = ExperienceLogger(settings.sqlite_path)

        fb_type = None
        obs_feedback = ""
        if edited_answer:
            fb_type = FeedbackType.ACCEPTED_EDIT
            obs_feedback = f"Owner edited answer: {edited_answer}"
        elif feedback == "thumbs_down":
            fb_type = FeedbackType.THUMBS_DOWN
            obs_feedback = "Owner thumbs down"

        if fb_type:
            exp_logger.log_from_feedback(
                feedback_type=fb_type,
                observed_feedback=obs_feedback,
                original_output=inter.get("answer", "") or inter.get("draft_reply", ""),
                interaction_id=inter.get("id"),
                project_id=inter.get("project_id"),
                task_id=inter.get("task_id"),
            )
    except Exception as e:
        logger.warning(f"Failed to log experience record for interaction '{inter.get('id')}': {e}")

@router.post("/interactions/{interaction_id}/feedback")
async def update_interaction_feedback_endpoint(interaction_id: str, req: FeedbackRequest, _auth: str = Depends(require_session_auth)):
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
    _log_experience_from_feedback(inter, req.feedback, req.edited_answer)
    return {
        "success": True,
        "interaction_id": interaction_id,
        "feedback": inter.get("feedback") if inter else req.feedback,
        "edited_answer": inter.get("edited_answer") if inter else req.edited_answer
    }

@router.get("/interactions/ratings-by-model")
async def ratings_by_model_endpoint(_auth: str = Depends(require_session_auth)):
    """Return aggregated feedback and performance metrics per model."""
    hm = get_history_mgr()
    return hm.get_ratings_by_model()

@router.get("/interactions/{interaction_id}")
async def get_interaction_endpoint(interaction_id: str, _auth: str = Depends(require_session_auth)):
    hm = get_history_mgr()
    inter = hm.get_interaction(interaction_id)
    if not inter:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return inter

@router.post("/messages/{message_id}/feedback")
async def update_message_feedback_endpoint(message_id: str, req: FeedbackRequest, _auth: str = Depends(require_session_auth)):
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
    _log_experience_from_feedback(inter, req.feedback, req.edited_answer)
    return {
        "success": True,
        "message_id": message_id,
        "interaction_id": inter.get("id") if inter else None,
        "feedback": req.feedback,
        "edited_answer": inter.get("edited_answer") if inter else req.edited_answer
    }

@router.post("/messages/{message_id}/edit")
async def edit_message_endpoint(message_id: str, req: EditMessageRequest, _auth: str = Depends(require_session_auth)):
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
    _log_experience_from_feedback(inter, None, edited)

    return {
        "success": True,
        "message_id": message_id,
        "interaction_id": inter.get("id") if inter else None,
        "edited_answer": edited
    }
