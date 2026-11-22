"""
backend/intelligence/planning_engine.py

Planning Engine for HINAKU.
Transforms approved objectives and decisions into structured, inspectable plans.
Manages goal decomposition, task dependencies, cycle detection, and dynamic prioritization.
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set
import uuid

from .decision_types import CriticalActionCategory
from .errors import PlanningDependencyError
from .knowledge_graph import KnowledgeGraph
from .planning_types import (
    DependencyType,
    ManagedTask,
    PlanRecord,
    PlanStatus,
    TaskDependency,
)
from .task_manager import TaskManager
from .types import TaskPriority, TaskStatus
from backend.database.backup import coordinated_write


class PlanningEngine:
    """Decomposes objectives into actionable plans, coordinates dependencies, and reassesses progress."""

    def __init__(
        self,
        db_path: Path,
        task_manager: TaskManager,
        knowledge_graph: Optional[KnowledgeGraph] = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.task_manager = task_manager
        self.graph = knowledge_graph
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS managed_plans (
                    plan_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    project_id TEXT,
                    decision_id TEXT,
                    task_ids TEXT NOT NULL DEFAULT '[]',
                    milestones TEXT NOT NULL DEFAULT '[]',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_plans_proj ON managed_plans (project_id, deleted);
                CREATE INDEX IF NOT EXISTS idx_plans_status ON managed_plans (status, deleted);
            """)

    # --------------------------------------------------------------------------
    # Plan Creation & Decomposition
    # --------------------------------------------------------------------------

    @coordinated_write("planning_engine")
    def create_plan(
        self,
        objective: str,
        project_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        milestones: Optional[List[Dict[str, Any]]] = None,
    ) -> PlanRecord:
        """Initializes a new plan for an objective or approved decision."""
        plan_id = str(uuid.uuid4())
        now = time.time()

        plan = PlanRecord(
            plan_id=plan_id,
            objective=objective,
            status=PlanStatus.DRAFT,
            project_id=project_id,
            decision_id=decision_id,
            task_ids=[],
            milestones=milestones or [],
            revision=1,
            created_at=now,
            updated_at=now,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO managed_plans (
                    plan_id, objective, status, project_id, decision_id,
                    task_ids, milestones, revision, created_at, updated_at, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.objective,
                    plan.status.value,
                    plan.project_id,
                    plan.decision_id,
                    json.dumps(plan.task_ids),
                    json.dumps(plan.milestones),
                    plan.revision,
                    plan.created_at,
                    plan.updated_at,
                    plan.deleted,
                )
            )

        return plan

    @coordinated_write("planning_engine")
    def add_task_to_plan(
        self,
        plan_id: str,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        dependencies: Optional[List[TaskDependency]] = None,
        completion_criteria: Optional[List[str]] = None,
        requires_owner_approval: bool = False,
        critical_action_category: Optional[CriticalActionCategory] = None,
    ) -> ManagedTask:
        """
        Decomposes an element of the plan into a managed task, validating dependencies
        and cycle-safety before linking it to the plan.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            raise PlanningDependencyError(f"Plan '{plan_id}' does not exist.")

        deps = dependencies or []

        # Validate that all dependencies exist and belong to the plan/project
        for dep in deps:
            target = self.task_manager.get_task(dep.target_task_id)
            if not target:
                raise PlanningDependencyError(
                    f"Dependency validation failed: prerequisite task '{dep.target_task_id}' does not exist."
                )

        # Create task via TaskManager
        task = self.task_manager.create_task(
            title=title,
            description=description,
            priority=priority,
            plan_id=plan_id,
            project_id=plan.project_id,
            decision_id=plan.decision_id,
            dependencies=deps,
            completion_criteria=completion_criteria,
            requires_owner_approval=requires_owner_approval,
            critical_action_category=critical_action_category,
        )

        # Check for circular dependencies across the entire plan
        self._validate_no_cycles(plan_id, task.task_id)

        # Append task_id to plan
        updated_tasks = list(plan.task_ids)
        if task.task_id not in updated_tasks:
            updated_tasks.append(task.task_id)

        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE managed_plans SET
                    task_ids = ?,
                    status = ?,
                    updated_at = ?
                WHERE plan_id = ?
                """,
                (
                    json.dumps(updated_tasks),
                    PlanStatus.ACTIVE.value,
                    now,
                    plan_id,
                )
            )

        return task

    def _validate_no_cycles(self, plan_id: str, new_task_id: str) -> None:
        """
        Performs cycle detection on the task dependency graph using depth-first search.
        Raises PlanningDependencyError if a cycle is detected.
        """
        tasks = self.task_manager.list_tasks(plan_id=plan_id)
        task_map = {t.task_id: t for t in tasks}

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node_id: str) -> None:
            visited.add(node_id)
            rec_stack.add(node_id)

            task = task_map.get(node_id)
            if task:
                for dep in task.dependencies:
                    target_id = dep.target_task_id
                    if target_id not in visited:
                        dfs(target_id)
                    elif target_id in rec_stack:
                        raise PlanningDependencyError(
                            f"Circular dependency detected in plan '{plan_id}' involving task '{node_id}' and '{target_id}'."
                        )

            rec_stack.remove(node_id)

        for tid in task_map:
            if tid not in visited:
                dfs(tid)

    # --------------------------------------------------------------------------
    # Plan Reassessment & Progress Tracking
    # --------------------------------------------------------------------------

    def reassess_plan(self, plan_id: str) -> Dict[str, Any]:
        """
        Reassesses plan progress, identifying actionable next tasks, blocked tasks,
        and completion status without mutating history.
        """
        plan = self.get_plan(plan_id)
        if not plan:
            raise PlanningDependencyError(f"Plan '{plan_id}' not found.")

        tasks = self.task_manager.list_tasks(plan_id=plan_id)

        actionable: List[ManagedTask] = []
        blocked: List[Dict[str, Any]] = []
        pending_approval: List[ManagedTask] = []
        completed: List[ManagedTask] = []

        for t in tasks:
            if t.status == TaskStatus.COMPLETED:
                completed.append(t)
            elif t.status == TaskStatus.PENDING_APPROVAL:
                pending_approval.append(t)
            elif t.status in (TaskStatus.QUEUED, TaskStatus.PENDING):
                blocking = self.task_manager.get_blocking_dependencies(t.task_id)
                if blocking:
                    blocked.append({"task": t, "blocked_by": blocking})
                else:
                    actionable.append(t)

        all_completed = len(completed) == len(tasks) and len(tasks) > 0
        if all_completed and plan.status != PlanStatus.COMPLETED:
            self.update_plan_status(plan_id, PlanStatus.COMPLETED)

        return {
            "plan_id": plan_id,
            "objective": plan.objective,
            "total_tasks": len(tasks),
            "completed_count": len(completed),
            "actionable_next_tasks": [t.to_dict() for t in actionable],
            "blocked_tasks": [
                {"task_id": b["task"].task_id, "title": b["task"].title, "blocked_by": b["blocked_by"]}
                for b in blocked
            ],
            "pending_approval": [t.to_dict() for t in pending_approval],
            "is_complete": all_completed,
        }

    @coordinated_write("planning_engine")
    def update_plan_status(self, plan_id: str, new_status: PlanStatus) -> PlanRecord:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE managed_plans SET
                    status = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE plan_id = ?
                """,
                (new_status.value, now, plan_id)
            )
        return self.get_plan(plan_id)  # type: ignore

    def get_plan(self, plan_id: str) -> Optional[PlanRecord]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_plans WHERE plan_id = ? AND deleted = 0",
                (plan_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_plan(row)

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> PlanRecord:
        return PlanRecord(
            plan_id=row["plan_id"],
            objective=row["objective"],
            status=PlanStatus(row["status"]),
            project_id=row["project_id"],
            decision_id=row["decision_id"],
            task_ids=json.loads(row["task_ids"]),
            milestones=json.loads(row["milestones"]),
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted=row["deleted"],
        )
