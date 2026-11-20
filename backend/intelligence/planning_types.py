"""
backend/intelligence/planning_types.py

Data structures, enums, and models for the HINAKU Planning Engine and Task Manager.
Decomposes approved objectives into manageable tasks with dependency and state management.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional

from .decision_types import CriticalActionCategory
from .types import TaskPriority, TaskStatus


class PlanStatus(str, Enum):
    """Lifecycle states for structured multi-task plans."""
    DRAFT = "draft"             # Plan framing in progress
    PROPOSED = "proposed"       # Ready for evaluation or owner review
    ACTIVE = "active"           # Execution underway across managed tasks
    PAUSED = "paused"           # Plan suspended temporarily
    COMPLETED = "completed"     # All planned tasks successfully resolved
    SUPERSEDED = "superseded"   # Replaced by an updated or restructured plan
    CANCELLED = "cancelled"     # Plan terminated before completion


class DependencyType(str, Enum):
    """Semantic nature of dependency between tasks."""
    DEPENDS_ON = "depends_on"          # Task cannot start until target finishes
    BLOCKS = "blocks"                  # Task prevents target from starting
    REQUIRED_BEFORE = "required_before"# Prerequisite ordering
    INDEPENDENT = "independent"        # Parallelizable work


@dataclass
class TaskDependency:
    """Directed dependency link to another task."""
    target_task_id: str
    dependency_type: DependencyType = DependencyType.DEPENDS_ON

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_task_id": self.target_task_id,
            "dependency_type": self.dependency_type.value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskDependency":
        return cls(
            target_task_id=data["target_task_id"],
            dependency_type=DependencyType(data.get("dependency_type", DependencyType.DEPENDS_ON.value)),
        )


@dataclass
class ManagedTask:
    """Stateful task tracked and coordinated by the TaskManager."""
    task_id: str
    title: str
    description: str
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.QUEUED
    plan_id: Optional[str] = None
    project_id: Optional[str] = None
    decision_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    dependencies: List[TaskDependency] = field(default_factory=list)
    completion_criteria: List[str] = field(default_factory=list)
    requires_owner_approval: bool = False
    critical_action_category: Optional[CriticalActionCategory] = None
    approval_status: Optional[str] = None  # None, "pending", "approved", "denied"
    assigned_agent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    deleted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status.value,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "decision_id": self.decision_id,
            "parent_task_id": self.parent_task_id,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "completion_criteria": self.completion_criteria,
            "requires_owner_approval": self.requires_owner_approval,
            "critical_action_category": (
                self.critical_action_category.value if self.critical_action_category else None
            ),
            "approval_status": self.approval_status,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManagedTask":
        cat = (
            CriticalActionCategory(data["critical_action_category"])
            if data.get("critical_action_category")
            else None
        )
        return cls(
            task_id=data["task_id"],
            title=data["title"],
            description=data.get("description", ""),
            priority=TaskPriority(data.get("priority", TaskPriority.MEDIUM.value)),
            status=TaskStatus(data.get("status", TaskStatus.QUEUED.value)),
            plan_id=data.get("plan_id"),
            project_id=data.get("project_id"),
            decision_id=data.get("decision_id"),
            parent_task_id=data.get("parent_task_id"),
            dependencies=[TaskDependency.from_dict(d) for d in data.get("dependencies", [])],
            completion_criteria=data.get("completion_criteria", []),
            requires_owner_approval=bool(data.get("requires_owner_approval", False)),
            critical_action_category=cat,
            approval_status=data.get("approval_status"),
            assigned_agent=data.get("assigned_agent"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            completed_at=data.get("completed_at"),
            deleted=data.get("deleted", 0),
        )


@dataclass
class TaskStateTransition:
    """Immutable audit record of a task status change."""
    transition_id: str
    task_id: str
    from_status: TaskStatus
    to_status: TaskStatus
    reason: str
    changed_by: str = "system"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "task_id": self.task_id,
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "reason": self.reason,
            "changed_by": self.changed_by,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskStateTransition":
        return cls(
            transition_id=data["transition_id"],
            task_id=data["task_id"],
            from_status=TaskStatus(data["from_status"]),
            to_status=TaskStatus(data["to_status"]),
            reason=data.get("reason", ""),
            changed_by=data.get("changed_by", "system"),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class PlanRecord:
    """A structured plan comprising decomposed tasks, milestones, and objective context."""
    plan_id: str
    objective: str
    status: PlanStatus = PlanStatus.DRAFT
    project_id: Optional[str] = None
    decision_id: Optional[str] = None
    task_ids: List[str] = field(default_factory=list)
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    revision: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    deleted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "objective": self.objective,
            "status": self.status.value,
            "project_id": self.project_id,
            "decision_id": self.decision_id,
            "task_ids": self.task_ids,
            "milestones": self.milestones,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanRecord":
        return cls(
            plan_id=data["plan_id"],
            objective=data["objective"],
            status=PlanStatus(data.get("status", PlanStatus.DRAFT.value)),
            project_id=data.get("project_id"),
            decision_id=data.get("decision_id"),
            task_ids=data.get("task_ids", []),
            milestones=data.get("milestones", []),
            revision=data.get("revision", 1),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            deleted=data.get("deleted", 0),
        )
