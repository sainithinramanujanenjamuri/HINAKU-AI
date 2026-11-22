"""
backend/api/learning.py

FastAPI router for HINAKU Controlled Learning, Systemic Weaknesses & Improvement Proposals.
Provides observational query endpoints, owner decision recording, and double-confirmed
full learning data wipe.
"""

import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.security.auth import (
    require_session_auth,
    session_token_manager,
    assert_owner_session_required,
)
from backend.intelligence.experience_logger import ExperienceLogger
from backend.intelligence.weakness_catalog import WeaknessCatalog
from backend.intelligence.improvement_engine import ImprovementProposalEngine
from backend.intelligence.learning_types import (
    ErrorCategory,
    FeedbackType,
    ProposalApprovalStatus,
    ProposalChangeCategory,
    ProposalEvaluationStatus,
    WeaknessSeverity,
    WeaknessStatus,
)
from backend.intelligence.errors import (
    CriticalApprovalRequiredError,
    ImprovementEvaluationError,
    SafetyBoundaryViolation,
)

router = APIRouter(prefix="/learning", tags=["learning"])


def get_experience_logger() -> ExperienceLogger:
    settings = get_settings()
    return ExperienceLogger(settings.sqlite_path)


def get_weakness_catalog() -> WeaknessCatalog:
    settings = get_settings()
    return WeaknessCatalog(settings.sqlite_path)


def get_improvement_engine() -> ImprovementProposalEngine:
    settings = get_settings()
    catalog = get_weakness_catalog()
    return ImprovementProposalEngine(settings.sqlite_path, weakness_catalog=catalog)


# ------------------------------------------------------------------------------
# Authentication Dependency for Full Learning Data Wipe
# ------------------------------------------------------------------------------

async def require_owner_session_for_wipe(
    request: Request,
    x_hinaku_token: Optional[str] = Header(None, alias="X-Hinaku-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> str:
    """
    Enforces that full learning data wipes originate strictly from an active human owner
    desktop session.
    1. Missing token -> 401 Unauthorized.
    2. Internal background token (e.g. 'hinaku_internal_...') -> 403 Forbidden.
    3. Invalid / expired token -> 401 Unauthorized.
    """
    candidate = x_hinaku_token
    if not candidate and authorization:
        auth_str = authorization.strip()
        if auth_str.lower().startswith("bearer "):
            candidate = auth_str[7:].strip()
        else:
            candidate = auth_str

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing local session authorization token."
        )

    clean_candidate = candidate.strip()
    if clean_candidate.startswith("hinaku_internal_"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Internal background tokens cannot execute full learning wipe; active owner desktop session is required."
        )

    if not session_token_manager.validate_token(clean_candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or expired local session authorization token."
        )

    return clean_candidate


# ------------------------------------------------------------------------------
# Request / Response Models
# ------------------------------------------------------------------------------

class WeaknessStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="Target weakness status: identified | under_review | proposed_fix | resolved | ignored")
    resolution_note: Optional[str] = Field(None, description="Explanation or reference to resolving commit/proposal")


class ProposalDecisionRequest(BaseModel):
    approved: bool = Field(..., description="Whether to approve or reject the proposal")
    owner_comment: Optional[str] = Field(None, description="Optional feedback / guidance from owner")


class LearningWipeRequest(BaseModel):
    """
    Double-confirmation payload for full learning data wipe (Milestone 7 Plan Section 8.4).
    """
    confirm_wipe: bool = Field(..., description="Explicit boolean confirmation")
    scope: str = Field(..., description="Must be 'all_experiences_and_weaknesses'")
    acknowledge_data_loss: bool = Field(..., description="Explicit acknowledgment of permanent loss of learning data")


# ------------------------------------------------------------------------------
# Experience Endpoints
# ------------------------------------------------------------------------------

@router.get("/experiences", response_model=List[Dict[str, Any]], dependencies=[Depends(require_session_auth)])
async def list_experiences(
    feedback_type: Optional[str] = Query(None),
    error_category: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Lists sanitized interaction experience records."""
    logger_engine = get_experience_logger()
    fb = FeedbackType(feedback_type.lower()) if feedback_type else None
    err = ErrorCategory(error_category.lower()) if error_category else None

    records = logger_engine.list_experiences(
        feedback_type=fb,
        error_category=err,
        project_id=project_id,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    return [r.to_dict() for r in records]


@router.get("/experiences/{experience_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def get_experience(experience_id: str):
    """Retrieves a single sanitized experience record by ID."""
    logger_engine = get_experience_logger()
    record = logger_engine.get_experience(experience_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Experience '{experience_id}' not found.")
    return record.to_dict()


@router.delete("/experiences/{experience_id}", dependencies=[Depends(require_session_auth)])
async def delete_experience(experience_id: str):
    """Deletes an experience record and unlinks it from all weakness records (supports owner privacy data deletion)."""
    logger_engine = get_experience_logger()
    success = logger_engine.delete_experience(experience_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Experience '{experience_id}' not found.")

    weakness_cat = get_weakness_catalog()
    unlinked_count = weakness_cat.unlink_experience(experience_id)

    return {
        "status": "deleted",
        "experience_id": experience_id,
        "unlinked_from_weaknesses": unlinked_count,
    }


# ------------------------------------------------------------------------------
# Systemic Weakness Endpoints
# ------------------------------------------------------------------------------

@router.get("/weaknesses", response_model=List[Dict[str, Any]], dependencies=[Depends(require_session_auth)])
async def list_weaknesses(
    status_filter: Optional[str] = Query(None, alias="status"),
    error_category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Lists cataloged systemic weaknesses."""
    catalog = get_weakness_catalog()
    st = WeaknessStatus(status_filter.lower()) if status_filter else None
    err = ErrorCategory(error_category.lower()) if error_category else None
    sev = WeaknessSeverity(severity.lower()) if severity else None

    records = catalog.list_weaknesses(
        status=st,
        error_category=err,
        severity=sev,
        limit=limit,
        offset=offset,
    )
    return [r.to_dict() for r in records]


@router.get("/weaknesses/{weakness_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def get_weakness(weakness_id: str):
    """Retrieves a single systemic weakness record by ID."""
    catalog = get_weakness_catalog()
    record = catalog.get_weakness(weakness_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Weakness '{weakness_id}' not found.")
    return record.to_dict()


@router.patch("/weaknesses/{weakness_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def update_weakness_status(weakness_id: str, req: WeaknessStatusUpdateRequest):
    """Updates the status of a systemic weakness."""
    catalog = get_weakness_catalog()
    try:
        new_status = WeaknessStatus(req.status.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid weakness status '{req.status}'."
        )

    try:
        updated = catalog.update_status(
            weakness_id=weakness_id,
            new_status=new_status,
            resolution_note=req.resolution_note,
        )
        return updated.to_dict()
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Weakness '{weakness_id}' not found.")


# ------------------------------------------------------------------------------
# Improvement Proposal Endpoints
# ------------------------------------------------------------------------------

@router.get("/proposals", response_model=List[Dict[str, Any]], dependencies=[Depends(require_session_auth)])
async def list_proposals(
    evaluation_status: Optional[str] = Query(None),
    owner_approval_status: Optional[str] = Query(None),
    change_category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Lists candidate improvement proposals."""
    engine = get_improvement_engine()
    ev_st = ProposalEvaluationStatus(evaluation_status.lower()) if evaluation_status else None
    ap_st = ProposalApprovalStatus(owner_approval_status.lower()) if owner_approval_status else None
    cat = ProposalChangeCategory(change_category.lower()) if change_category else None

    proposals = engine.list_proposals(
        evaluation_status=ev_st,
        owner_approval_status=ap_st,
        change_category=cat,
        limit=limit,
        offset=offset,
    )
    return [p.to_dict() for p in proposals]


@router.get("/proposals/{proposal_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def get_proposal(proposal_id: str):
    """Retrieves a candidate proposal by ID."""
    engine = get_improvement_engine()
    proposal = engine.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Proposal '{proposal_id}' not found.")
    return proposal.to_dict()


@router.post("/proposals/{proposal_id}/decision", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def record_proposal_decision(proposal_id: str, req: ProposalDecisionRequest):
    """
    Records explicit owner decision on an evaluated proposal.
    Note: Approving does NOT autonomously deploy code or models.
    """
    engine = get_improvement_engine()
    try:
        updated = engine.record_owner_decision(
            proposal_id=proposal_id,
            approved=req.approved,
            owner_comment=req.owner_comment,
        )
        return updated.to_dict()
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Proposal '{proposal_id}' not found.")


@router.post("/proposals/{proposal_id}/evaluate", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def evaluate_proposal(proposal_id: str):
    """Executes isolated benchmark evaluation for an improvement proposal."""
    engine = get_improvement_engine()
    try:
        results = engine.evaluate_proposal(proposal_id)
        return results
    except ImprovementEvaluationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except SafetyBoundaryViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ------------------------------------------------------------------------------
# Full Learning Data Wipe (Double-Confirmation & Owner Authenticated)
# ------------------------------------------------------------------------------

@router.post("/wipe", response_model=Dict[str, Any])
async def wipe_all_learning_data(
    req: LearningWipeRequest,
    _auth_token: str = Depends(require_owner_session_for_wipe),
):
    """
    Full learning data wipe (Milestone 7 Plan Section 8.4).
    - Requires active owner desktop session (internal background tokens return HTTP 403).
    - Requires explicit double-confirmation payload.
    - Wipes all ExperienceRecords, WeaknessRecords, and ImprovementProposals.
    - Preserves core conversation history, audit logs, persona prompt, and security configs.
    """
    if not req.confirm_wipe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wipe rejected: 'confirm_wipe' must be True."
        )

    if not req.acknowledge_data_loss:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wipe rejected: 'acknowledge_data_loss' must be True."
        )

    if req.scope != "all_experiences_and_weaknesses":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wipe rejected: 'scope' must be 'all_experiences_and_weaknesses'."
        )

    assert_owner_session_required("full_learning_wipe", has_owner_session=True)

    exp_logger = get_experience_logger()
    weakness_cat = get_weakness_catalog()
    impr_engine = get_improvement_engine()

    deleted_experiences = exp_logger.clear_all_experiences()
    deleted_weaknesses = weakness_cat.clear_all_weaknesses()
    deleted_proposals = impr_engine.clear_all_proposals()

    return {
        "status": "wiped",
        "scope": req.scope,
        "deleted_experiences": deleted_experiences,
        "deleted_weaknesses": deleted_weaknesses,
        "deleted_proposals": deleted_proposals,
        "timestamp": time.time(),
        "preserved_data": [
            "core_conversation_history",
            "hinaku_persona",
            "security_configuration",
            "system_audit_logs",
        ],
    }
