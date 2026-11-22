"""
backend/intelligence/task_manager.py

Task Manager Foundation for HINAKU.
Maintains state, coordinates lifecycle transitions, manages dependencies, records audit history,
and strictly enforces owner approval boundaries for critical operations.
"""

import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set
import uuid

from .decision_types import CriticalActionCategory
from .errors import (
    CriticalApprovalRequiredError,
    IntelligenceError,
    TaskLifecycleViolation,
)
from .planning_types import (
    DependencyType,
    ManagedTask,
    TaskDependency,
    TaskStateTransition,
)
from .types import TaskPriority, TaskStatus
from backend.database.backup import coordinated_write
from backend.security.auth import assert_owner_session_required

logger = logging.getLogger("hinaku.intelligence.task_manager")


# Valid state transitions graph for managed tasks
VALID_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.ACTIVE, TaskStatus.PENDING_APPROVAL, TaskStatus.CANCELLED},
    TaskStatus.ACTIVE: {TaskStatus.PAUSED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.PENDING_APPROVAL},
    TaskStatus.PAUSED: {TaskStatus.ACTIVE, TaskStatus.CANCELLED},
    TaskStatus.PENDING_APPROVAL: {TaskStatus.ACTIVE, TaskStatus.QUEUED, TaskStatus.CANCELLED},
    # Backward compatibility aliases
    TaskStatus.PENDING: {TaskStatus.ACTIVE, TaskStatus.PENDING_APPROVAL, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.PAUSED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.PENDING_APPROVAL},
    # Terminal states
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class TaskManager:
    """Coordinates task state, enforces lifecycle rules, and records state transitions."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS managed_tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_id TEXT,
                    project_id TEXT,
                    decision_id TEXT,
                    parent_task_id TEXT,
                    dependencies TEXT NOT NULL DEFAULT '[]',
                    completion_criteria TEXT NOT NULL DEFAULT '[]',
                    requires_owner_approval INTEGER NOT NULL DEFAULT 0,
                    critical_action_category TEXT,
                    approval_status TEXT,
                    assigned_agent TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    action_hash TEXT,
                    target_resource TEXT,
                    operation TEXT,
                    scope_parameters TEXT NOT NULL DEFAULT '{}',
                    approval_metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS task_history (
                    transition_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    changed_by TEXT NOT NULL DEFAULT 'system',
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES managed_tasks(task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON managed_tasks (status, deleted);
                CREATE INDEX IF NOT EXISTS idx_tasks_proj ON managed_tasks (project_id, deleted);
                CREATE INDEX IF NOT EXISTS idx_tasks_plan ON managed_tasks (plan_id, deleted);
                CREATE INDEX IF NOT EXISTS idx_task_history_task ON task_history (task_id, timestamp DESC);
            """)

            # Schema migration check for scoped approval columns in pre-existing tables
            existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(managed_tasks);").fetchall()}
            for col, col_def in [
                ("action_hash", "TEXT"),
                ("target_resource", "TEXT"),
                ("operation", "TEXT"),
                ("scope_parameters", "TEXT NOT NULL DEFAULT '{}'"),
                ("approval_metadata", "TEXT NOT NULL DEFAULT '{}'"),
            ]:
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE managed_tasks ADD COLUMN {col} {col_def};")
                    except Exception as e:
                        logger.warning(f"Failed to add column {col} to managed_tasks: {e}")

    # --------------------------------------------------------------------------
    # Task Creation & Retrieval
    # --------------------------------------------------------------------------

    @coordinated_write("task_manager")
    def create_task(
        self,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        plan_id: Optional[str] = None,
        project_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        dependencies: Optional[List[TaskDependency]] = None,
        completion_criteria: Optional[List[str]] = None,
        requires_owner_approval: bool = False,
        critical_action_category: Optional[CriticalActionCategory] = None,
        initial_status: TaskStatus = TaskStatus.QUEUED,
        task_id: Optional[str] = None,
        action_hash: Optional[str] = None,
        target_resource: Optional[str] = None,
        operation: Optional[str] = None,
        scope_parameters: Optional[Dict[str, Any]] = None,
        approval_metadata: Optional[Dict[str, Any]] = None,
    ) -> ManagedTask:
        """Creates and stores a managed task, recording its initial transition."""
        tid = task_id or str(uuid.uuid4())
        now = time.time()

        # Enforce approval requirement if critical action category is assigned
        if critical_action_category is not None:
            requires_owner_approval = True

        if requires_owner_approval and not action_hash and target_resource and operation:
            cat_str = critical_action_category.value if critical_action_category else "none"
            canonical_payload = json.dumps(scope_parameters or {}, sort_keys=True)
            action_hash = hashlib.sha256(
                f"{tid}:{cat_str}:{target_resource}:{operation}:{canonical_payload}".encode("utf-8")
            ).hexdigest()

        task = ManagedTask(
            task_id=tid,
            title=title,
            description=description,
            priority=priority,
            status=initial_status,
            plan_id=plan_id,
            project_id=project_id,
            decision_id=decision_id,
            parent_task_id=parent_task_id,
            dependencies=dependencies or [],
            completion_criteria=completion_criteria or [],
            requires_owner_approval=requires_owner_approval,
            critical_action_category=critical_action_category,
            approval_status="pending" if requires_owner_approval else None,
            action_hash=action_hash,
            target_resource=target_resource,
            operation=operation,
            scope_parameters=scope_parameters or {},
            approval_metadata=approval_metadata or {},
            created_at=now,
            updated_at=now,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO managed_tasks (
                    task_id, title, description, priority, status,
                    plan_id, project_id, decision_id, parent_task_id,
                    dependencies, completion_criteria, requires_owner_approval,
                    critical_action_category, approval_status, assigned_agent,
                    created_at, updated_at, completed_at, deleted,
                    action_hash, target_resource, operation, scope_parameters, approval_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.title,
                    task.description,
                    task.priority.value,
                    task.status.value,
                    task.plan_id,
                    task.project_id,
                    task.decision_id,
                    task.parent_task_id,
                    json.dumps([d.to_dict() for d in task.dependencies]),
                    json.dumps(task.completion_criteria),
                    1 if task.requires_owner_approval else 0,
                    task.critical_action_category.value if task.critical_action_category else None,
                    task.approval_status,
                    task.assigned_agent,
                    task.created_at,
                    task.updated_at,
                    task.completed_at,
                    task.deleted,
                    task.action_hash,
                    task.target_resource,
                    task.operation,
                    json.dumps(task.scope_parameters),
                    json.dumps(task.approval_metadata),
                )
            )

            # Record initial history
            conn.execute(
                """
                INSERT INTO task_history (
                    transition_id, task_id, from_status, to_status,
                    reason, changed_by, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    task.task_id,
                    initial_status.value,
                    initial_status.value,
                    "Task initialized",
                    "system",
                    now,
                )
            )

        return task

    def get_task(self, task_id: str) -> Optional[ManagedTask]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_tasks WHERE task_id = ? AND deleted = 0",
                (task_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_task(row)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        project_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> List[ManagedTask]:
        query = "SELECT * FROM managed_tasks WHERE deleted = 0"
        params: List[Any] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        if plan_id is not None:
            query += " AND plan_id = ?"
            params.append(plan_id)
        query += " ORDER BY updated_at DESC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_task(r) for r in rows]

    # --------------------------------------------------------------------------
    # Lifecycle Transitions & Controlled State Operations
    # --------------------------------------------------------------------------

    @coordinated_write("task_manager")
    def transition_task(
        self,
        task_id: str,
        new_status: TaskStatus,
        reason: str,
        changed_by: str = "system",
        owner_approved: bool = False,
    ) -> ManagedTask:
        """
        Transitions a task to a new lifecycle state with transition validation
        and strict owner approval verification.
        """
        task = self.get_task(task_id)
        if not task:
            raise IntelligenceError(f"Task '{task_id}' not found.")

        # Check valid state transition
        allowed_targets = VALID_TRANSITIONS.get(task.status, set())
        if new_status not in allowed_targets:
            raise TaskLifecycleViolation(
                f"Invalid task lifecycle transition: cannot move task '{task_id}' from '{task.status.value}' to '{new_status.value}'. "
                f"Allowed target states: {[s.value for s in allowed_targets]}"
            )

        # Enforce owner approval preconditions for starting or executing approval-gated tasks
        if new_status == TaskStatus.ACTIVE:
            if task.requires_owner_approval:
                has_valid_approval = (task.approval_status == "approved" and bool(task.action_hash)) or owner_approved
                if not has_valid_approval:
                    cat_val = task.critical_action_category.value if task.critical_action_category else "critical operation"
                    raise CriticalApprovalRequiredError(
                        f"Task '{task.title}' requires explicit owner approval for {cat_val}. "
                        "Cannot transition to ACTIVE without owner authorization."
                    )

            # Check if any dependencies block this task
            blocked_by = self.get_blocking_dependencies(task_id)
            if blocked_by:
                raise TaskLifecycleViolation(
                    f"Cannot activate task '{task_id}': blocked by unfinished dependencies: {blocked_by}"
                )

        now = time.time()
        completed_at = now if new_status == TaskStatus.COMPLETED else task.completed_at
        approval_status = "approved" if (owner_approved and task.requires_owner_approval) else task.approval_status

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE managed_tasks SET
                    status = ?,
                    approval_status = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE task_id = ?
                """,
                (
                    new_status.value,
                    approval_status,
                    now,
                    completed_at,
                    task_id,
                )
            )

            # Record audit transition
            conn.execute(
                """
                INSERT INTO task_history (
                    transition_id, task_id, from_status, to_status,
                    reason, changed_by, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    task_id,
                    task.status.value,
                    new_status.value,
                    reason,
                    changed_by,
                    now,
                )
            )

        return self.get_task(task_id)  # type: ignore

    def start_task(self, task_id: str, owner_approved: bool = False) -> ManagedTask:
        """Starts a queued or paused task."""
        task = self.get_task(task_id)
        if not task:
            raise IntelligenceError(f"Task '{task_id}' not found.")

        # If requires owner approval and not approved, transition to PENDING_APPROVAL
        if task.requires_owner_approval and task.approval_status != "approved" and not owner_approved:
            if task.status != TaskStatus.PENDING_APPROVAL:
                return self.transition_task(
                    task_id=task_id,
                    new_status=TaskStatus.PENDING_APPROVAL,
                    reason="Awaiting mandatory owner authorization for critical action",
                    changed_by="system",
                )
            raise CriticalApprovalRequiredError(
                f"Task '{task.title}' is pending owner approval and requires explicit owner approval."
            )

        return self.transition_task(
            task_id=task_id,
            new_status=TaskStatus.ACTIVE,
            reason="Task execution started",
            changed_by="owner" if owner_approved else "system",
            owner_approved=owner_approved,
        )

    def pause_task(self, task_id: str, reason: str = "Paused by coordinator") -> ManagedTask:
        return self.transition_task(task_id, TaskStatus.PAUSED, reason)

    def resume_task(self, task_id: str, owner_approved: bool = False) -> ManagedTask:
        return self.transition_task(task_id, TaskStatus.ACTIVE, "Task resumed", owner_approved=owner_approved)

    def complete_task(self, task_id: str, outcome_notes: str = "") -> ManagedTask:
        return self.transition_task(task_id, TaskStatus.COMPLETED, outcome_notes or "Task successfully completed")

    def fail_task(self, task_id: str, error_message: str) -> ManagedTask:
        return self.transition_task(task_id, TaskStatus.FAILED, f"Failed: {error_message}")

    def cancel_task(self, task_id: str, reason: str = "Cancelled") -> ManagedTask:
        return self.transition_task(task_id, TaskStatus.CANCELLED, reason)

    # --------------------------------------------------------------------------
    # Coordination & Progress Visibility
    # --------------------------------------------------------------------------

    def get_blocking_dependencies(self, task_id: str) -> List[str]:
        """Returns the task IDs of unfinished dependencies that block this task."""
        task = self.get_task(task_id)
        if not task:
            return []

        blocking: List[str] = []
        for dep in task.dependencies:
            if dep.dependency_type in (DependencyType.DEPENDS_ON, DependencyType.REQUIRED_BEFORE):
                dep_task = self.get_task(dep.target_task_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    blocking.append(dep.target_task_id)
        return blocking

    def get_task_history(self, task_id: str) -> List[TaskStateTransition]:
        """Retrieves the full audit transition history for a task."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_history WHERE task_id = ? ORDER BY timestamp ASC",
                (task_id,)
            ).fetchall()
            return [self._row_to_transition(r) for r in rows]

    def get_progress_summary(
        self,
        project_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates structured progress visibility without exposing raw internal traces."""
        all_tasks = self.list_tasks(project_id=project_id, plan_id=plan_id)

        active = [t for t in all_tasks if t.status == TaskStatus.ACTIVE]
        queued = [t for t in all_tasks if t.status in (TaskStatus.QUEUED, TaskStatus.PENDING)]
        paused = [t for t in all_tasks if t.status == TaskStatus.PAUSED]
        pending_appr = [t for t in all_tasks if t.status == TaskStatus.PENDING_APPROVAL]
        completed = [t for t in all_tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in all_tasks if t.status == TaskStatus.FAILED]

        # Identify blocked tasks among queued
        blocked_tasks = []
        for t in queued:
            b = self.get_blocking_dependencies(t.task_id)
            if b:
                blocked_tasks.append({"task_id": t.task_id, "title": t.title, "blocked_by": b})

        return {
            "total_tasks": len(all_tasks),
            "counts": {
                "active": len(active),
                "queued": len(queued),
                "paused": len(paused),
                "pending_approval": len(pending_appr),
                "completed": len(completed),
                "failed": len(failed),
            },
            "active_tasks": [{"task_id": t.task_id, "title": t.title, "priority": t.priority.value} for t in active],
            "pending_approval": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "category": t.critical_action_category.value if t.critical_action_category else None,
                }
                for t in pending_appr
            ],
            "blocked_tasks": blocked_tasks,
        }

    @coordinated_write("task_manager")
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> ManagedTask:
        """
        Updates task properties.
        CRITICAL INVARIANT:
        If task description, dependencies, completion criteria, target resource, operation,
        or scope parameters are modified after an approval is granted, the task automatically
        reverts to PENDING_APPROVAL and invalidates previous approvals.
        """
        existing = self.get_task(task_id)
        if not existing:
            raise IntelligenceError(f"Task '{task_id}' not found.")

        mutation_invalidates_approval = False
        mutation_fields = {
            "title", "description", "dependencies", "completion_criteria",
            "critical_action_category", "target_resource", "operation", "scope_parameters"
        }

        if existing.approval_status == "approved":
            for field in mutation_fields:
                if field in updates:
                    mutation_invalidates_approval = True
                    break

        now = time.time()
        set_clauses = ["updated_at = ?"]
        params: List[Any] = [now]

        allowed_fields = {
            "title", "description", "priority", "status", "plan_id", "project_id",
            "decision_id", "parent_task_id", "dependencies", "completion_criteria",
            "requires_owner_approval", "critical_action_category", "approval_status",
            "assigned_agent", "target_resource", "operation", "scope_parameters",
            "action_hash", "approval_metadata", "completed_at", "deleted"
        }

        for k, v in updates.items():
            if k not in allowed_fields:
                continue
            if k == "priority" and isinstance(v, TaskPriority):
                v = v.value
            elif k == "status" and isinstance(v, TaskStatus):
                v = v.value
            elif k == "critical_action_category" and isinstance(v, CriticalActionCategory):
                v = v.value
            elif k in ("dependencies", "completion_criteria", "scope_parameters", "approval_metadata"):
                if isinstance(v, (list, dict)):
                    v = json.dumps(v)
            set_clauses.append(f"{k} = ?")
            params.append(v)

        if mutation_invalidates_approval:
            set_clauses.append("approval_status = ?")
            params.append("pending")
            set_clauses.append("status = ?")
            params.append(TaskStatus.PENDING_APPROVAL.value)
            set_clauses.append("action_hash = ?")
            params.append(None)
            logger.warning(
                f"[Security] Task '{task_id}' was mutated after approval. Reverting to PENDING_APPROVAL and invalidating approval."
            )

        params.append(task_id)

        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE managed_tasks SET {', '.join(set_clauses)} WHERE task_id = ?",
                params
            )
            if mutation_invalidates_approval:
                conn.execute(
                    """
                    INSERT INTO task_history (
                        transition_id, task_id, from_status, to_status,
                        reason, changed_by, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        task_id,
                        existing.status.value,
                        TaskStatus.PENDING_APPROVAL.value,
                        "Approval invalidated due to task parameter/resource mutation",
                        "system",
                        now,
                    )
                )

        return self.get_task(task_id)  # type: ignore

    @coordinated_write("task_manager")
    def approve_task(
        self,
        task_id: str,
        action_hash: str,
        target_resource: str,
        operation: str,
        scope_parameters: Dict[str, Any],
        has_owner_session: bool,
    ) -> ManagedTask:
        """
        Enforces scoped owner desktop session approval for critical tasks.
        Binds cryptographic action_hash and validates parameters before approval.
        One-time use: valid only for this task.
        """
        assert_owner_session_required("approve_critical_task", has_owner_session=has_owner_session)

        task = self.get_task(task_id)
        if not task:
            raise IntelligenceError(f"Task '{task_id}' not found.")

        # Check if task already has target_resource / operation defined, enforce exact match
        if task.target_resource and task.target_resource != target_resource:
            raise CriticalApprovalRequiredError(
                f"Approval target_resource mismatch: task defines '{task.target_resource}', approval requested for '{target_resource}'."
            )
        if task.operation and task.operation != operation:
            raise CriticalApprovalRequiredError(
                f"Approval operation mismatch: task defines '{task.operation}', approval requested for '{operation}'."
            )

        # Compute canonical hash
        canonical_payload = json.dumps(scope_parameters, sort_keys=True)
        cat_str = task.critical_action_category.value if task.critical_action_category else "none"
        expected_hash = hashlib.sha256(
            f"{task.task_id}:{cat_str}:{target_resource}:{operation}:{canonical_payload}".encode("utf-8")
        ).hexdigest()

        # Check if submitted hash matches expected canonical hash of the parameters
        if action_hash.lower() != expected_hash.lower():
            raise CriticalApprovalRequiredError(
                f"Action hash mismatch for task '{task_id}': expected '{expected_hash}', received '{action_hash}'."
            )

        # Furthermore, if the task has a pre-computed action_hash, enforce exact match
        if task.action_hash and task.action_hash.lower() != action_hash.lower():
            raise CriticalApprovalRequiredError(
                f"Action hash mismatch for task '{task_id}': task action_hash '{task.action_hash}' does not match provided '{action_hash}'."
            )

        now = time.time()
        meta = {
            "approved_by": "owner",
            "approved_at": now,
            "action_hash": action_hash,
            "target_resource": target_resource,
            "operation": operation,
        }

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE managed_tasks SET
                    approval_status = 'approved',
                    action_hash = ?,
                    target_resource = ?,
                    operation = ?,
                    scope_parameters = ?,
                    approval_metadata = ?,
                    status = CASE WHEN status = ? THEN ? ELSE status END,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (
                    action_hash,
                    target_resource,
                    operation,
                    canonical_payload,
                    json.dumps(meta),
                    TaskStatus.PENDING_APPROVAL.value,
                    TaskStatus.QUEUED.value,
                    now,
                    task_id,
                )
            )

            conn.execute(
                """
                INSERT INTO task_history (
                    transition_id, task_id, from_status, to_status,
                    reason, changed_by, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    task_id,
                    task.status.value,
                    TaskStatus.QUEUED.value if task.status == TaskStatus.PENDING_APPROVAL else task.status.value,
                    f"Explicit owner approval granted for {cat_str} on {target_resource}",
                    "owner",
                    now,
                )
            )

        return self.get_task(task_id)  # type: ignore

    @coordinated_write("task_manager")
    def delete_task(self, task_id: str) -> bool:
        """Soft-deletes a task (deleted = 1)."""
        existing = self.get_task(task_id)
        if not existing:
            return False
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE managed_tasks SET deleted = 1, updated_at = ? WHERE task_id = ?",
                (time.time(), task_id)
            )
        return True

    # --------------------------------------------------------------------------
    # Row Helpers
    # --------------------------------------------------------------------------

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> ManagedTask:
        deps = [TaskDependency.from_dict(d) for d in json.loads(row["dependencies"])]
        cat = CriticalActionCategory(row["critical_action_category"]) if row["critical_action_category"] else None

        scope_params = {}
        if "scope_parameters" in row.keys() and row["scope_parameters"]:
            try:
                scope_params = json.loads(row["scope_parameters"])
            except Exception:
                pass

        appr_meta = {}
        if "approval_metadata" in row.keys() and row["approval_metadata"]:
            try:
                appr_meta = json.loads(row["approval_metadata"])
            except Exception:
                pass

        act_hash = row["action_hash"] if "action_hash" in row.keys() else None
        tgt_res = row["target_resource"] if "target_resource" in row.keys() else None
        op = row["operation"] if "operation" in row.keys() else None

        return ManagedTask(
            task_id=row["task_id"],
            title=row["title"],
            description=row["description"],
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            plan_id=row["plan_id"],
            project_id=row["project_id"],
            decision_id=row["decision_id"],
            parent_task_id=row["parent_task_id"],
            dependencies=deps,
            completion_criteria=json.loads(row["completion_criteria"]),
            requires_owner_approval=bool(row["requires_owner_approval"]),
            critical_action_category=cat,
            approval_status=row["approval_status"],
            assigned_agent=row["assigned_agent"],
            action_hash=act_hash,
            target_resource=tgt_res,
            operation=op,
            scope_parameters=scope_params,
            approval_metadata=appr_meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            deleted=row["deleted"],
        )

    @staticmethod
    def _row_to_transition(row: sqlite3.Row) -> TaskStateTransition:
        return TaskStateTransition(
            transition_id=row["transition_id"],
            task_id=row["task_id"],
            from_status=TaskStatus(row["from_status"]),
            to_status=TaskStatus(row["to_status"]),
            reason=row["reason"],
            changed_by=row["changed_by"],
            timestamp=row["timestamp"],
        )
