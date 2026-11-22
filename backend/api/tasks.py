"""
backend/api/tasks.py

FastAPI router for HINAKU Task Management & Scoped Owner Approval.
Implements task querying, lifecycle transitions, parameter mutations with automatic
approval invalidation, and the cryptographically bound owner approval endpoint.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.security.auth import (
    require_session_auth,
    session_token_manager,
)
from backend.intelligence.task_manager import TaskManager
from backend.intelligence.planning_types import (
    DependencyType,
    ManagedTask,
    TaskDependency,
)
from backend.intelligence.types import TaskPriority, TaskStatus
from backend.intelligence.decision_types import CriticalActionCategory
from backend.intelligence.errors import (
    CriticalApprovalRequiredError,
    IntelligenceError,
    TaskLifecycleViolation,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_task_manager() -> TaskManager:
    settings = get_settings()
    return TaskManager(settings.sqlite_path)


# ------------------------------------------------------------------------------
# Authentication Dependency for Scoped Owner Approvals
# ------------------------------------------------------------------------------

async def require_owner_session_for_approval(
    request: Request,
    x_hinaku_token: Optional[str] = Header(None, alias="X-Hinaku-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> str:
    """
    Enforces that task approvals originate strictly from an active human owner
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
            detail="Forbidden: Internal background tokens cannot authorize critical tasks; active owner desktop session is required."
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

class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Task title")
    description: Optional[str] = Field("", description="Task description / operational goal")
    priority: Optional[str] = Field("medium", description="low | medium | high | critical")
    plan_id: Optional[str] = None
    project_id: Optional[str] = None
    decision_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    dependencies: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    completion_criteria: Optional[List[str]] = Field(default_factory=list)
    requires_owner_approval: Optional[bool] = False
    critical_action_category: Optional[str] = Field(None, description="One of the 6 critical action categories")
    target_resource: Optional[str] = None
    operation: Optional[str] = None
    scope_parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)
    action_hash: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    dependencies: Optional[List[Dict[str, Any]]] = None
    completion_criteria: Optional[List[str]] = None
    critical_action_category: Optional[str] = None
    target_resource: Optional[str] = None
    operation: Optional[str] = None
    scope_parameters: Optional[Dict[str, Any]] = None


class TaskTransitionRequest(BaseModel):
    new_status: str = Field(..., description="Target lifecycle state")
    reason: str = Field(..., description="Justification for state change")
    changed_by: Optional[str] = Field("owner", description="Agent or user making transition")
    owner_approved: Optional[bool] = Field(False, description="Whether explicit owner approval was provided")


class TaskApprovalRequest(BaseModel):
    """
    Explicit and scoped owner approval request model (Milestone 7 Plan Section 5.2).
    """
    action_hash: str = Field(..., description="SHA-256 hash of task_id + action_category + target_resource + operation_payload")
    target_resource: str = Field(..., min_length=1, description="Exact file path, service, or API being touched")
    operation: str = Field(..., min_length=1, description="Specific operation (e.g. delete_file, modify_config)")
    scope_parameters: Dict[str, Any] = Field(default_factory=dict, description="Bounded parameters for operation")
    confirmed: bool = Field(..., description="Explicit checkbox confirmation toggle")


# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------

@router.get("", response_model=List[Dict[str, Any]], dependencies=[Depends(require_session_auth)])
async def list_tasks(
    project_id: Optional[str] = Query(None),
    plan_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """Lists managed tasks with optional filtering."""
    mgr = get_task_manager()
    st = None
    if status_filter:
        try:
            st = TaskStatus(status_filter.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid task status '{status_filter}'."
            )
    tasks = mgr.list_tasks(status=st, project_id=project_id, plan_id=plan_id)
    return [t.to_dict() for t in tasks]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def create_task(req: TaskCreateRequest):
    """Creates a new managed task."""
    mgr = get_task_manager()

    try:
        pri = TaskPriority(req.priority.lower()) if req.priority else TaskPriority.MEDIUM
    except ValueError:
        pri = TaskPriority.MEDIUM

    cat = None
    if req.critical_action_category:
        try:
            cat = CriticalActionCategory(req.critical_action_category.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid critical action category '{req.critical_action_category}'."
            )

    deps: List[TaskDependency] = []
    if req.dependencies:
        for d in req.dependencies:
            try:
                deps.append(TaskDependency.from_dict(d))
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid dependency specification: {e}"
                )

    task = mgr.create_task(
        title=req.title.strip(),
        description=(req.description or "").strip(),
        priority=pri,
        plan_id=req.plan_id,
        project_id=req.project_id,
        decision_id=req.decision_id,
        parent_task_id=req.parent_task_id,
        dependencies=deps,
        completion_criteria=req.completion_criteria or [],
        requires_owner_approval=bool(req.requires_owner_approval or cat is not None),
        critical_action_category=cat,
        target_resource=req.target_resource,
        operation=req.operation,
        scope_parameters=req.scope_parameters or {},
        action_hash=req.action_hash,
    )
    return task.to_dict()


@router.get("/{task_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def get_task(task_id: str):
    """Retrieves a single task by ID."""
    mgr = get_task_manager()
    task = mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found.")
    return task.to_dict()


@router.get("/{task_id}/history", response_model=List[Dict[str, Any]], dependencies=[Depends(require_session_auth)])
async def get_task_history(task_id: str):
    """Retrieves the full lifecycle state transition history for a task."""
    mgr = get_task_manager()
    task = mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found.")
    history = mgr.get_task_history(task_id)
    return [
        {
            "transition_id": h.transition_id,
            "task_id": h.task_id,
            "from_status": h.from_status.value,
            "to_status": h.to_status.value,
            "reason": h.reason,
            "changed_by": h.changed_by,
            "timestamp": h.timestamp,
        }
        for h in history
    ]


@router.patch("/{task_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
@router.put("/{task_id}", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def update_task(task_id: str, req: TaskUpdateRequest):
    """
    Updates task properties.
    Automatic Invalidation Invariant:
    If a task was previously approved and any parameter, dependency, target resource,
    or description is modified, its approval status is reset to 'pending' and its
    state reverts to PENDING_APPROVAL.
    """
    mgr = get_task_manager()
    task = mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found.")

    updates = req.model_dump(exclude_unset=True)

    if "dependencies" in updates and updates["dependencies"] is not None:
        try:
            updates["dependencies"] = [TaskDependency.from_dict(d).to_dict() for d in updates["dependencies"]]
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid dependencies: {e}")

    try:
        updated = mgr.update_task(task_id, updates)
        return updated.to_dict()
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{task_id}/transition", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
@router.patch("/{task_id}/transition", response_model=Dict[str, Any], dependencies=[Depends(require_session_auth)])
async def transition_task(task_id: str, req: TaskTransitionRequest):
    """
    Transitions a task to a new lifecycle state.
    Enforces valid state transition graph and owner approval preconditions.
    """
    mgr = get_task_manager()
    try:
        target_status = TaskStatus(req.new_status.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task lifecycle state '{req.new_status}'."
        )

    try:
        updated = mgr.transition_task(
            task_id=task_id,
            new_status=target_status,
            reason=req.reason,
            changed_by=req.changed_by or "owner",
            owner_approved=bool(req.owner_approved),
        )
        return updated.to_dict()
    except TaskLifecycleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except CriticalApprovalRequiredError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{task_id}/approve", response_model=Dict[str, Any])
async def approve_task(
    task_id: str,
    req: TaskApprovalRequest,
    _auth_token: str = Depends(require_owner_session_for_approval),
):
    """
    Scoped owner desktop session approval endpoint (Milestone 7 Plan Section 5.2).
    - Requires active owner desktop session (internal background tokens return HTTP 403).
    - Verifies cryptographic action_hash binding against parameters and target resource.
    - Approval is valid exclusively for this specific task (one-time use).
    """
    if not req.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation toggle must be true to grant approval."
        )

    mgr = get_task_manager()
    task = mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found.")

    try:
        updated = mgr.approve_task(
            task_id=task_id,
            action_hash=req.action_hash.strip(),
            target_resource=req.target_resource.strip(),
            operation=req.operation.strip(),
            scope_parameters=req.scope_parameters,
            has_owner_session=True,
        )
        return {
            "status": "approved",
            "task_id": task_id,
            "action_hash": req.action_hash,
            "approval_status": updated.approval_status,
            "task_status": updated.status.value,
            "approved_at": updated.approval_metadata.get("approved_at"),
        }
    except CriticalApprovalRequiredError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{task_id}", dependencies=[Depends(require_session_auth)])
async def delete_task(task_id: str):
    """Soft-deletes a task."""
    mgr = get_task_manager()
    success = mgr.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task '{task_id}' not found.")
    return {"status": "deleted", "task_id": task_id}
