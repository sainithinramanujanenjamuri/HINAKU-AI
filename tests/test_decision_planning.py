"""
tests/test_decision_planning.py

Comprehensive unit and integration tests for HINAKU Phase 1 Milestone 4:
Decision Engine, Planning Engine, Task Manager Foundation, and Owner Approval Boundaries.
"""

from pathlib import Path
import pytest
import time

from backend.intelligence import (
    AlternativeEvaluation,
    CriticalActionCategory,
    CriticalApprovalRequiredError,
    DecisionEngine,
    DecisionRecord,
    DecisionStatus,
    DependencyType,
    DomainIsolationViolation,
    EdgeRelationship,
    ImplementationStatus,
    IntelligenceContext,
    IntelligenceError,
    KnowledgeDomain,
    KnowledgeGraph,
    KnowledgeProvenance,
    ManagedTask,
    PlanningDependencyError,
    PlanningEngine,
    PlanRecord,
    PlanStatus,
    SourceAuthority,
    TaskDependency,
    TaskLifecycleViolation,
    TaskManager,
    TaskPriority,
    TaskStatus,
    UncertaintyAssessment,
    UncertaintyLevel,
)


@pytest.fixture
def decision_env(tmp_path):
    """Provides a fresh DecisionEngine backed by a temporary SQLite database with KnowledgeGraph."""
    db_file = tmp_path / "test_decisions.db"
    graph = KnowledgeGraph(db_file)
    engine = DecisionEngine(db_file, knowledge_graph=graph)
    return engine, graph


@pytest.fixture
def planning_env(tmp_path):
    """Provides a fresh PlanningEngine and TaskManager instance."""
    db_file = tmp_path / "test_planning.db"
    task_mgr = TaskManager(db_file)
    plan_eng = PlanningEngine(db_file, task_manager=task_mgr)
    return plan_eng, task_mgr


# ==============================================================================
# 1. Decision Engine Tests
# ==============================================================================

def test_structured_decision_evaluation(decision_env):
    """Test evaluating alternatives and uncertainty into a structured recommendation."""
    engine, graph = decision_env

    ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.DECISION, KnowledgeDomain.PROJECT},
    )

    alts = [
        AlternativeEvaluation(
            alternative_id="alt-sqlite",
            title="Embedded SQLite WAL",
            description="Use SQLite WAL mode for local zero-config persistence",
            pros=["Zero config", "Fast single-user transactions", "Reliable WAL"],
            cons=["Single writer concurrency ceiling"],
            reversibility="high",
            resource_cost="low",
            score=9.0,
            score_explanation="Matches single-user local-first architecture",
        ),
        AlternativeEvaluation(
            alternative_id="alt-postgres",
            title="External Postgres Server",
            description="Deploy local Postgres Docker service",
            pros=["Advanced indexing", "Multi-user concurrency"],
            cons=["High memory footprint", "Docker dependency"],
            reversibility="medium",
            resource_cost="high",
            score=4.0,
            score_explanation="Unnecessary background overhead on laptop",
        ),
    ]

    record = engine.evaluate_decision(
        title="Local Database Architecture",
        problem_statement="Select primary persistent storage engine for HINAKU",
        alternatives=alts,
        context=ctx,
        project_id="hinaku-core",
        known_facts=["Target environment has 6GB VRAM and single-user constraint"],
        assumptions=["Data volume remains under 100GB over 3 years"],
        unknowns=[],
        conflicting_evidence=[],
    )

    assert record.status == DecisionStatus.RECOMMENDED
    assert record.recommendation is not None
    assert record.recommendation.recommended_alternative_id == "alt-sqlite"
    assert record.uncertainty.level == UncertaintyLevel.MODERATE
    assert record.recommendation.requires_owner_approval is False

    # Check persistence
    fetched = engine.get_decision(record.decision_id)
    assert fetched is not None
    assert fetched.title == "Local Database Architecture"


def test_decision_uncertainty_and_critical_approval_enforcement(decision_env):
    """Test uncertainty escalation and critical approval requirement when high risks or critical categories apply."""
    engine, graph = decision_env

    ctx = IntelligenceContext(actor_id="owner", permitted_domains={KnowledgeDomain.DECISION})

    # Evaluation involving CriticalActionCategory.FILE_MODIFICATION_OR_DELETION
    record = engine.evaluate_decision(
        title="Purge Outdated Artifacts",
        problem_statement="Purge legacy cache files outside the temporary directory",
        alternatives=[
            AlternativeEvaluation(
                alternative_id="alt-purge",
                title="Purge Disk Cache",
                description="Delete old cache files",
                score=8.0,
            )
        ],
        context=ctx,
        critical_category=CriticalActionCategory.FILE_MODIFICATION_OR_DELETION,
        unknowns=["Are any external processes locking the legacy cache files?"],
    )

    assert record.uncertainty.level == UncertaintyLevel.CRITICAL
    assert record.recommendation.requires_owner_approval is True
    assert record.recommendation.critical_action_category == CriticalActionCategory.FILE_MODIFICATION_OR_DELETION


def test_decision_owner_choice_and_revisions(decision_env):
    """Test that owner decision updates status to APPROVED (not implemented) and records audit revision."""
    engine, graph = decision_env
    ctx = IntelligenceContext(actor_id="owner", permitted_domains={KnowledgeDomain.DECISION})

    record = engine.evaluate_decision(
        title="Vector Dimension",
        problem_statement="Choose embedding dimensions",
        alternatives=[AlternativeEvaluation(alternative_id="a1", title="1024 dims", description="", score=10.0)],
        context=ctx,
    )

    # Owner approves decision
    approved = engine.record_owner_choice(
        decision_id=record.decision_id,
        choice="a1",
        owner_notes="Approved 1024 dims per Qwen model standard",
        approved=True,
    )

    assert approved.status == DecisionStatus.APPROVED
    # Architectural Invariant: Approved decision receives status ACCEPTED, strictly NOT IMPLEMENTED
    assert approved.provenance.verification_status == ImplementationStatus.ACCEPTED
    assert approved.revision == 2


def test_challenge_proposal_if_conflicting(decision_env):
    """Test respectfully identifying proposals that conflict with known constraints or past decisions."""
    engine, graph = decision_env

    # 1. Conflict against known boundary constraint
    challenge = engine.challenge_proposal_if_conflicting(
        proposal="Let's send all user messages to an external cloud API",
        known_constraints=["Strict local-only privacy boundary; no API egress for personal data"],
    )
    assert challenge is not None
    assert challenge["conflict_detected"] is True
    assert "local-only boundary" in challenge["explanation"]


def test_decision_superseding_integration(decision_env):
    """Test marking an older decision as superseded with KnowledgeGraph edge."""
    engine, graph = decision_env
    ctx = IntelligenceContext(actor_id="owner", permitted_domains={KnowledgeDomain.DECISION})

    dec1 = engine.evaluate_decision(title="Dec 1", problem_statement="Problem 1", alternatives=[AlternativeEvaluation("a", "title", "", score=1)], context=ctx)
    dec2 = engine.evaluate_decision(title="Dec 2", problem_statement="Problem 2", alternatives=[AlternativeEvaluation("b", "title", "", score=1)], context=ctx)

    engine.supersede_decision(dec1.decision_id, dec2.decision_id, reason="New hardware upgrade")

    updated_dec1 = engine.get_decision(dec1.decision_id)
    assert updated_dec1.status == DecisionStatus.SUPERSEDED
    assert updated_dec1.provenance.verification_status == ImplementationStatus.SUPERSEDED

    # Check graph edge
    edges = graph.get_edges(dec2.decision_id, direction="out", relationship=EdgeRelationship.SUPERSEDES)
    assert len(edges) == 1
    assert edges[0].target_id == dec1.decision_id


# ==============================================================================
# 2. Planning Engine Tests
# ==============================================================================

def test_plan_creation_and_task_decomposition(planning_env):
    """Test creating a plan and decomposing an objective into managed tasks."""
    plan_eng, task_mgr = planning_env

    plan = plan_eng.create_plan(
        objective="Implement hybrid model router",
        project_id="hinaku-core",
        milestones=[{"name": "Sprint 1", "target": "Local fallback"}],
    )
    assert plan.status == PlanStatus.DRAFT

    # Add Task 1
    t1 = plan_eng.add_task_to_plan(
        plan_id=plan.plan_id,
        title="Configure Ollama adapter",
        priority=TaskPriority.HIGH,
    )
    assert t1.plan_id == plan.plan_id

    # Add Task 2 depending on Task 1
    t2 = plan_eng.add_task_to_plan(
        plan_id=plan.plan_id,
        title="Add fallback circuit breaker",
        priority=TaskPriority.MEDIUM,
        dependencies=[TaskDependency(target_task_id=t1.task_id, dependency_type=DependencyType.DEPENDS_ON)],
    )
    assert len(t2.dependencies) == 1

    updated_plan = plan_eng.get_plan(plan.plan_id)
    assert updated_plan.status == PlanStatus.ACTIVE
    assert len(updated_plan.task_ids) == 2


def test_planning_engine_detects_circular_dependencies(planning_env):
    """Test that circular dependencies are caught and rejected with PlanningDependencyError."""
    plan_eng, task_mgr = planning_env
    plan = plan_eng.create_plan(objective="Test cycles")

    t1 = plan_eng.add_task_to_plan(plan_id=plan.plan_id, title="Task 1")
    t2 = plan_eng.add_task_to_plan(
        plan_id=plan.plan_id,
        title="Task 2",
        dependencies=[TaskDependency(target_task_id=t1.task_id)],
    )

    # Attempting to add Task 3 depending on t2, while t1 is updated to depend on t3 -> cycle
    # More simply: add task depending on non-existent or cycle
    with pytest.raises(PlanningDependencyError, match="does not exist"):
        plan_eng.add_task_to_plan(
            plan_id=plan.plan_id,
            title="Invalid Task",
            dependencies=[TaskDependency(target_task_id="ghost-task-id")],
        )


def test_plan_reassessment_identifies_blocked_and_actionable_tasks(planning_env):
    """Test reassessing plan progress to identify actionable vs blocked tasks."""
    plan_eng, task_mgr = planning_env
    plan = plan_eng.create_plan(objective="Deployment pipeline")

    t1 = plan_eng.add_task_to_plan(plan_id=plan.plan_id, title="Build container")
    t2 = plan_eng.add_task_to_plan(
        plan_id=plan.plan_id,
        title="Run container smoke tests",
        dependencies=[TaskDependency(target_task_id=t1.task_id)],
    )

    reassess1 = plan_eng.reassess_plan(plan.plan_id)
    actionable_ids = [t["task_id"] for t in reassess1["actionable_next_tasks"]]
    blocked_ids = [b["task_id"] for b in reassess1["blocked_tasks"]]

    assert t1.task_id in actionable_ids
    assert t2.task_id in blocked_ids
    assert reassess1["is_complete"] is False

    # Complete t1
    task_mgr.start_task(t1.task_id)
    task_mgr.complete_task(t1.task_id)

    # Reassess again: t2 should now be actionable
    reassess2 = plan_eng.reassess_plan(plan.plan_id)
    actionable_ids_2 = [t["task_id"] for t in reassess2["actionable_next_tasks"]]
    assert t2.task_id in actionable_ids_2


# ==============================================================================
# 3. Task Manager Lifecycle & Security Tests
# ==============================================================================

def test_task_lifecycle_valid_transitions(planning_env):
    """Test valid lifecycle state progression: QUEUED -> ACTIVE -> PAUSED -> ACTIVE -> COMPLETED."""
    plan_eng, task_mgr = planning_env

    task = task_mgr.create_task(title="Refactor database indexes")
    assert task.status == TaskStatus.QUEUED

    # Start
    active_task = task_mgr.start_task(task.task_id)
    assert active_task.status == TaskStatus.ACTIVE

    # Pause
    paused_task = task_mgr.pause_task(task.task_id, reason="Higher priority interrupt")
    assert paused_task.status == TaskStatus.PAUSED

    # Resume
    resumed_task = task_mgr.resume_task(task.task_id)
    assert resumed_task.status == TaskStatus.ACTIVE

    # Complete
    completed_task = task_mgr.complete_task(task.task_id, outcome_notes="Indexes successfully created")
    assert completed_task.status == TaskStatus.COMPLETED
    assert completed_task.completed_at is not None

    # History audit verification
    history = task_mgr.get_task_history(task.task_id)
    assert len(history) == 5  # Initial + Start + Pause + Resume + Complete


def test_task_lifecycle_rejects_invalid_transitions(planning_env):
    """Test that invalid lifecycle transitions from terminal states raise TaskLifecycleViolation."""
    plan_eng, task_mgr = planning_env
    task = task_mgr.create_task(title="One-shot job")

    task_mgr.start_task(task.task_id)
    task_mgr.complete_task(task.task_id)

    # Attempting to resume or start a COMPLETED task must raise TaskLifecycleViolation
    with pytest.raises(TaskLifecycleViolation, match="Invalid task lifecycle transition"):
        task_mgr.start_task(task.task_id)


def test_task_manager_enforces_critical_approval_boundaries(planning_env):
    """Test that tasks requiring owner authorization cannot become ACTIVE without explicit approval."""
    plan_eng, task_mgr = planning_env

    task = task_mgr.create_task(
        title="Purge Old Workspace Directories",
        requires_owner_approval=True,
        critical_action_category=CriticalActionCategory.FILE_MODIFICATION_OR_DELETION,
    )
    assert task.requires_owner_approval is True

    # Attempting start_task without owner_approved=True sets to PENDING_APPROVAL
    pending_task = task_mgr.start_task(task.task_id, owner_approved=False)
    assert pending_task.status == TaskStatus.PENDING_APPROVAL

    # Direct start attempt on PENDING_APPROVAL without owner approval raises CriticalApprovalRequiredError
    with pytest.raises(CriticalApprovalRequiredError, match="requires explicit owner approval"):
        task_mgr.start_task(task.task_id, owner_approved=False)

    # With explicit owner approval (owner_approved=True), transition succeeds
    active_task = task_mgr.start_task(task.task_id, owner_approved=True)
    assert active_task.status == TaskStatus.ACTIVE
    assert active_task.approval_status == "approved"


def test_task_manager_dependency_blocking(planning_env):
    """Test that a task cannot start if its prerequisite dependencies are not completed."""
    plan_eng, task_mgr = planning_env

    t1 = task_mgr.create_task(title="Database schema migration")
    t2 = task_mgr.create_task(
        title="Start web server",
        dependencies=[TaskDependency(target_task_id=t1.task_id, dependency_type=DependencyType.DEPENDS_ON)],
    )

    # Starting t2 while t1 is QUEUED must fail
    with pytest.raises(TaskLifecycleViolation, match="blocked by unfinished dependencies"):
        task_mgr.start_task(t2.task_id)

    # Complete t1
    task_mgr.start_task(t1.task_id)
    task_mgr.complete_task(t1.task_id)

    # Now starting t2 succeeds
    t2_active = task_mgr.start_task(t2.task_id)
    assert t2_active.status == TaskStatus.ACTIVE


def test_task_manager_progress_summary(planning_env):
    """Test generating a structured progress summary for owner visibility."""
    plan_eng, task_mgr = planning_env

    t1 = task_mgr.create_task(title="Task A", priority=TaskPriority.HIGH)
    t2 = task_mgr.create_task(
        title="Task B",
        requires_owner_approval=True,
        critical_action_category=CriticalActionCategory.SYSTEM_OPERATION,
    )
    task_mgr.start_task(t1.task_id)
    task_mgr.start_task(t2.task_id, owner_approved=False)

    summary = task_mgr.get_progress_summary()
    assert summary["counts"]["active"] == 1
    assert summary["counts"]["pending_approval"] == 1
    assert len(summary["pending_approval"]) == 1
    assert summary["pending_approval"][0]["category"] == "system_operation"
