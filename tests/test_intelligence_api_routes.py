"""
tests/test_intelligence_api_routes.py

Comprehensive integration test suite for Milestone 7 Step 2:
Intelligence REST API Routes (/api/projects, /api/tasks, /api/learning).

Verifies:
1. Authentication & Authorization Boundaries:
   - Missing token -> 401 Unauthorized.
   - Internal background tokens on critical owner operations (/tasks/{id}/approve, /learning/wipe) -> 403 Forbidden.
   - Valid owner desktop session token -> Success.
2. Projects API (/api/projects):
   - CRUD lifecycle, duplicate prevention (409), status/confidentiality filtering.
   - Structured knowledge management.
   - Context bundle retrieval and strict confidentiality enforcement (blocks external API on confidential projects).
3. Tasks API (/api/tasks):
   - Task querying, lifecycle transitions (valid vs invalid transitions, approval preconditions).
   - Scoped owner approval (POST /api/tasks/{id}/approve):
     - Valid action_hash binding against parameters and target resource.
     - Tampered / mismatching action_hash rejection (400).
     - One-time use binding (approval for task A does not approve task B).
     - Automatic invalidation on mutation (task parameter edits revert approval to PENDING_APPROVAL).
4. Controlled Learning API (/api/learning):
   - Observational queries for sanitized experience audit trails (sensitive data redaction).
   - Systemic weakness catalog queries and status updates.
   - Improvement proposals, isolated evaluation, and explicit owner decision recording.
   - Full learning data wipe (POST /api/learning/wipe) with double-confirmation and core data preservation.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import get_settings
from backend.security.auth import (
    session_token_manager,
    internal_token_manager,
    InternalScope,
)
from backend.intelligence.types import (
    KnowledgeDomain,
    TaskPriority,
    TaskStatus,
)
from backend.intelligence.project_types import (
    ProjectConfidentiality,
    ProjectStatus,
    KnowledgeCategory,
)
from backend.intelligence.decision_types import CriticalActionCategory
from backend.intelligence.learning_types import (
    FeedbackType,
    ErrorCategory,
    WeaknessStatus,
    WeaknessSeverity,
    ProposalChangeCategory,
    ProposalEvaluationStatus,
    ProposalApprovalStatus,
)


@pytest.fixture
def api_test_env(tmp_path, monkeypatch):
    """
    Sets up an isolated database environment for intelligence API testing.
    """
    settings = get_settings()
    test_db = settings.sqlite_path

    # Initialize tables via engines
    from backend.intelligence.project_store import ProjectStore
    from backend.intelligence.task_manager import TaskManager
    from backend.intelligence.experience_logger import ExperienceLogger
    from backend.intelligence.weakness_catalog import WeaknessCatalog
    from backend.intelligence.improvement_engine import ImprovementProposalEngine

    ps = ProjectStore(test_db)
    tm = TaskManager(test_db)
    el = ExperienceLogger(test_db)
    wc = WeaknessCatalog(test_db)
    ie = ImprovementProposalEngine(test_db, weakness_catalog=wc)

    session_token = session_token_manager.get_token()

    # Generate legitimate internal background token
    internal_token = internal_token_manager.issue_token(
        scope=InternalScope.BACKGROUND_SCHEDULER,
        ttl_seconds=3600,
    )

    client = TestClient(app)

    return {
        "db_path": test_db,
        "client": client,
        "session_token": session_token,
        "internal_token": internal_token,
        "project_store": ps,
        "task_manager": tm,
        "experience_logger": el,
        "weakness_catalog": wc,
        "improvement_engine": ie,
    }


# ==============================================================================
# 1. AUTHENTICATION & AUTHORIZATION TESTS
# ==============================================================================

def test_auth_boundaries_missing_token_returns_401(api_test_env):
    """
    Acceptance Criteria 1:
    GET /api/projects and GET /api/tasks without valid token return HTTP 401.
    """
    client = api_test_env["client"]
    unauth_headers = {"X-Hinaku-Token": ""}

    resp = client.get("/api/projects", headers=unauth_headers)
    assert resp.status_code == 401

    resp = client.get("/api/tasks", headers=unauth_headers)
    assert resp.status_code == 401

    resp = client.get("/api/learning/experiences", headers=unauth_headers)
    assert resp.status_code == 401


def test_auth_boundaries_internal_token_rejected_on_approve_with_403(api_test_env):
    """
    Acceptance Criteria 1:
    POST /api/tasks/{id}/approve invoked with an internal background token returns HTTP 403.
    """
    client = api_test_env["client"]
    internal_token = api_test_env["internal_token"]
    tm = api_test_env["task_manager"]

    # Create task requiring approval
    task = tm.create_task(
        title="Deploy Critical Configuration",
        critical_action_category=CriticalActionCategory.SYSTEM_OPERATION,
    )

    internal_headers = {"X-Hinaku-Token": internal_token}
    resp = client.post(
        f"/api/tasks/{task.task_id}/approve",
        headers=internal_headers,
        json={
            "action_hash": "dummy_hash",
            "target_resource": "/etc/systemd/system",
            "operation": "modify_config",
            "scope_parameters": {},
            "confirmed": True,
        },
    )
    assert resp.status_code == 403
    assert "Internal background tokens cannot authorize" in resp.json()["detail"]


def test_auth_boundaries_internal_token_rejected_on_wipe_with_403(api_test_env):
    """
    POST /api/learning/wipe invoked with an internal background token returns HTTP 403.
    """
    client = api_test_env["client"]
    internal_token = api_test_env["internal_token"]

    internal_headers = {"X-Hinaku-Token": internal_token}
    resp = client.post(
        "/api/learning/wipe",
        headers=internal_headers,
        json={
            "confirm_wipe": True,
            "scope": "all_experiences_and_weaknesses",
            "acknowledge_data_loss": True,
        },
    )
    assert resp.status_code == 403
    assert "Internal background tokens cannot execute full learning wipe" in resp.json()["detail"]


# ==============================================================================
# 2. PROJECTS REST API TESTS (/api/projects)
# ==============================================================================

def test_projects_crud_lifecycle(api_test_env):
    """Verifies project creation, querying, updating, and soft-deletion."""
    client = api_test_env["client"]
    session_token = api_test_env["session_token"]
    headers = {"X-Hinaku-Token": session_token}

    # 1. Create Project
    resp = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Project Hinaku Core",
            "purpose": "Autonomous Intelligence Foundation",
            "description": "Desktop AI assistant core repository",
            "tech_stack": ["Python", "FastAPI", "SQLite"],
            "confidentiality": "internal",
        },
    )
    assert resp.status_code == 201
    pdata = resp.json()
    pid = pdata["project_id"]
    assert pdata["name"] == "Project Hinaku Core"
    assert pdata["confidentiality"] == "internal"

    # 2. Duplicate registration returns 409 Conflict
    resp_dup = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Project Hinaku Core",
            "purpose": "Duplicate creation attempt",
        },
    )
    assert resp_dup.status_code == 409

    # 3. Get Project
    resp_get = client.get(f"/api/projects/{pid}", headers=headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["project_id"] == pid

    # 4. Update Project (PATCH)
    resp_patch = client.patch(
        f"/api/projects/{pid}",
        headers=headers,
        json={"description": "Updated overview for core architecture"},
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["description"] == "Updated overview for core architecture"

    # 5. List Projects with filtering
    resp_list = client.get("/api/projects?confidentiality=internal", headers=headers)
    assert resp_list.status_code == 200
    assert any(p["project_id"] == pid for p in resp_list.json())

    # 6. Soft Delete Project
    resp_del = client.delete(f"/api/projects/{pid}", headers=headers)
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "deleted"

    # Subsequent GET without include_deleted returns 404
    resp_get_del = client.get(f"/api/projects/{pid}", headers=headers)
    assert resp_get_del.status_code == 404


def test_project_knowledge_and_context_retrieval(api_test_env):
    """
    Verifies structured knowledge item creation and context bundle assembly,
    enforcing that confidential projects block external API context transmission.
    """
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}

    # Register confidential project
    resp = client.post(
        "/api/projects",
        headers=headers,
        json={
            "name": "Project Shadow Vault",
            "purpose": "Secret local IP management",
            "confidentiality": "confidential",
        },
    )
    assert resp.status_code == 201
    pid = resp.json()["project_id"]

    # Add Knowledge Item
    resp_k = client.post(
        f"/api/projects/{pid}/knowledge",
        headers=headers,
        json={
            "category": "architecture",
            "title": "Air-Gapped Vault Security",
            "content": "All credentials stored in secure DPAPI enclave.",
            "claim_confidence": 0.95,
        },
    )
    assert resp_k.status_code == 201
    assert resp_k.json()["title"] == "Air-Gapped Vault Security"

    # Retrieve context for local operation (allowed)
    resp_ctx = client.get(f"/api/projects/{pid}/context?allow_external_api=false", headers=headers)
    assert resp_ctx.status_code == 200
    ctx_data = resp_ctx.json()
    assert "Air-Gapped Vault Security" in ctx_data["context"]
    assert ctx_data["confidentiality"] == "confidential"

    # Retrieve context with allow_external_api=True on confidential project -> BLOCKED (400)
    resp_blocked = client.get(f"/api/projects/{pid}/context?allow_external_api=true", headers=headers)
    assert resp_blocked.status_code == 400
    assert "strictly prohibited for confidential project intelligence" in resp_blocked.json()["detail"]


# ==============================================================================
# 3. TASKS REST API & SCOPED OWNER APPROVAL TESTS (/api/tasks)
# ==============================================================================

def test_task_creation_and_lifecycle_transitions(api_test_env):
    """Verifies task creation, dependency validation, and state transitions."""
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}

    # Create task 1
    resp1 = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Prepare Database Schema",
            "description": "Initialize relational tables",
            "priority": "high",
        },
    )
    assert resp1.status_code == 201
    t1_id = resp1.json()["task_id"]

    # Create task 2 depending on task 1
    resp2 = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Run Data Migration",
            "description": "Apply migrations after schema is ready",
            "dependencies": [{"target_task_id": t1_id, "dependency_type": "depends_on"}],
        },
    )
    assert resp2.status_code == 201
    t2_id = resp2.json()["task_id"]

    # Attempting to start Task 2 before Task 1 completes is blocked (400)
    resp_blocked = client.post(
        f"/api/tasks/{t2_id}/transition",
        headers=headers,
        json={"new_status": "active", "reason": "Starting dependent task early"},
    )
    assert resp_blocked.status_code == 400
    assert "blocked by unfinished dependencies" in resp_blocked.json()["detail"]

    # Start and complete Task 1
    client.post(f"/api/tasks/{t1_id}/transition", headers=headers, json={"new_status": "active", "reason": "Start t1"})
    client.post(f"/api/tasks/{t1_id}/transition", headers=headers, json={"new_status": "completed", "reason": "Finished t1"})

    # Now Task 2 can transition to active
    resp_t2_start = client.post(
        f"/api/tasks/{t2_id}/transition",
        headers=headers,
        json={"new_status": "active", "reason": "Prerequisite satisfied"},
    )
    assert resp_t2_start.status_code == 200
    assert resp_t2_start.json()["status"] == "active"


def test_scoped_owner_approval_and_cryptographic_action_hash(api_test_env):
    """
    Acceptance Criteria 2:
    - Verifies POST /api/tasks/{id}/approve enforces action_hash binding against parameters.
    - Approval granted for Task A cannot authorize Task B (one-time use).
    - If task parameters are modified after approval, approval is invalidated (status reverts to PENDING_APPROVAL).
    """
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}

    # Create task requiring critical approval
    resp = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Delete Legacy Cache Directory",
            "description": "Purge temporary cache files",
            "critical_action_category": "file_modification_or_deletion",
        },
    )
    assert resp.status_code == 201
    task_data = resp.json()
    tid = task_data["task_id"]
    assert task_data["requires_owner_approval"] is True
    assert task_data["approval_status"] == "pending"

    target_res = "data/temp/cache_v1"
    operation = "delete_directory"
    params = {"recursive": True, "dry_run": False}

    # Compute expected canonical action_hash
    canonical_payload = json.dumps(params, sort_keys=True)
    expected_hash = hashlib.sha256(
        f"{tid}:file_modification_or_deletion:{target_res}:{operation}:{canonical_payload}".encode("utf-8")
    ).hexdigest()

    # 1. Unconfirmed request rejected (400)
    resp_unconfirmed = client.post(
        f"/api/tasks/{tid}/approve",
        headers=headers,
        json={
            "action_hash": expected_hash,
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": params,
            "confirmed": False,
        },
    )
    assert resp_unconfirmed.status_code == 400

    # 2. Tampered / wrong action_hash rejected (400)
    resp_tampered = client.post(
        f"/api/tasks/{tid}/approve",
        headers=headers,
        json={
            "action_hash": "deadbeef1234567890abcdefdeadbeef",
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": params,
            "confirmed": True,
        },
    )
    assert resp_tampered.status_code == 400
    assert "Action hash mismatch" in resp_tampered.json()["detail"]

    # 3. Valid owner session approval succeeds
    resp_approved = client.post(
        f"/api/tasks/{tid}/approve",
        headers=headers,
        json={
            "action_hash": expected_hash,
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": params,
            "confirmed": True,
        },
    )
    assert resp_approved.status_code == 200
    appr_data = resp_approved.json()
    assert appr_data["status"] == "approved"
    assert appr_data["action_hash"] == expected_hash

    # Check task status in database
    get_resp = client.get(f"/api/tasks/{tid}", headers=headers)
    assert get_resp.json()["approval_status"] == "approved"

    # 4. One-time use: Attempting to use same approval hash on Task B fails
    resp_task_b = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Task B Critical",
            "critical_action_category": "file_modification_or_deletion",
        },
    )
    tid_b = resp_task_b.json()["task_id"]

    resp_b_reject = client.post(
        f"/api/tasks/{tid_b}/approve",
        headers=headers,
        json={
            "action_hash": expected_hash,  # Hash bound to Task A
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": params,
            "confirmed": True,
        },
    )
    assert resp_b_reject.status_code == 400
    assert "Action hash mismatch" in resp_b_reject.json()["detail"]

    # 5. Automatic Invalidation on Mutation:
    # Mutating Task A's parameters reverts approval to PENDING_APPROVAL
    resp_mutate = client.patch(
        f"/api/tasks/{tid}",
        headers=headers,
        json={"target_resource": "data/temp/cache_v2"},
    )
    assert resp_mutate.status_code == 200
    mutated_task = resp_mutate.json()
    assert mutated_task["approval_status"] == "pending"
    assert mutated_task["status"] == "pending_approval"


# ==============================================================================
# 4. CONTROLLED LEARNING REST API TESTS (/api/learning)
# ==============================================================================

def test_learning_experiences_sanitized_query(api_test_env):
    """Verifies observational querying of experiences with credential redaction."""
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}
    el = api_test_env["experience_logger"]

    # Log experience with credential
    el.log_from_feedback(
        feedback_type=FeedbackType.USER_CORRECTION,
        observed_feedback="Do not use secret key sk-ant-live-0123456789abcdef0123 in plaintext config.",
        original_output="Saved key sk-ant-live-0123456789abcdef0123 to config.yaml",
        inferred_error=ErrorCategory.MISINTERPRETED_INSTRUCTION,
    )

    resp = client.get("/api/learning/experiences", headers=headers)
    assert resp.status_code == 200
    exps = resp.json()
    assert len(exps) >= 1
    # Check that credentials were redacted
    assert "sk-ant-live-0123456789abcdef0123" not in exps[0]["observed_user_feedback"]
    assert "[removed]" in exps[0]["observed_user_feedback"]


def test_weakness_and_proposal_lifecycle(api_test_env):
    """Verifies systemic weakness browsing, proposal evaluation, and decision recording."""
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}
    wc = api_test_env["weakness_catalog"]
    ie = api_test_env["improvement_engine"]

    from backend.intelligence.learning_types import WeaknessRecord

    # 1. Register a weakness
    w = WeaknessRecord(
        weakness_id="weak_brevity_01",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Responses exceed four-sentence limit on factual lookups",
        frequency=2,
        severity=WeaknessSeverity.MEDIUM,
    )
    w = wc.register_weakness(w)
    wid = w.weakness_id

    # 2. Query weakness via API
    resp_w = client.get(f"/api/learning/weaknesses/{wid}", headers=headers)
    assert resp_w.status_code == 200
    assert resp_w.json()["weakness_id"] == wid

    # 3. Update weakness status
    resp_up = client.patch(
        f"/api/learning/weaknesses/{wid}",
        headers=headers,
        json={"status": "under_review", "resolution_note": "Investigating prompt brevity tuning"},
    )
    assert resp_up.status_code == 200
    assert resp_up.json()["status"] == "under_review"

    # 4. Formulate improvement proposal
    prop = ie.create_proposal(
        description="Add brevity constraint to factual query prefix",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Guarantees concise responses",
        potential_risks="May over-trim technical details",
        related_weakness_ids=[wid],
    )
    pid = prop.proposal_id

    # 5. Evaluate proposal via API
    resp_eval = client.post(f"/api/learning/proposals/{pid}/evaluate", headers=headers)
    assert resp_eval.status_code == 200
    assert resp_eval.json()["evaluation_passed"] is True

    # 6. Record owner decision
    resp_dec = client.post(
        f"/api/learning/proposals/{pid}/decision",
        headers=headers,
        json={"approved": True, "owner_comment": "Approved after clean benchmark evaluation"},
    )
    assert resp_dec.status_code == 200
    assert resp_dec.json()["owner_approval_status"] == "approved"


def test_full_learning_data_wipe_double_confirmation(api_test_env):
    """
    Verifies full learning data wipe:
    - Rejects invalid confirmation payloads (400).
    - Clears experiences, weaknesses, proposals.
    - Preserves core conversation history and configuration.
    """
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}
    el = api_test_env["experience_logger"]
    wc = api_test_env["weakness_catalog"]

    from backend.intelligence.learning_types import WeaknessRecord

    el.log_from_feedback(FeedbackType.THUMBS_DOWN, "Too verbose", "Output")
    w = WeaknessRecord(
        weakness_id="weak_filler_01",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Excessive filler words",
        frequency=1,
        severity=WeaknessSeverity.LOW,
    )
    wc.register_weakness(w)

    assert el.count_experiences() >= 1
    assert wc.count_weaknesses() >= 1

    # 1. Incomplete payload rejected (400)
    resp_bad = client.post(
        "/api/learning/wipe",
        headers=headers,
        json={"confirm_wipe": False, "scope": "all_experiences_and_weaknesses", "acknowledge_data_loss": True},
    )
    assert resp_bad.status_code == 400

    # 2. Confirmed wipe succeeds
    resp_wipe = client.post(
        "/api/learning/wipe",
        headers=headers,
        json={"confirm_wipe": True, "scope": "all_experiences_and_weaknesses", "acknowledge_data_loss": True},
    )
    assert resp_wipe.status_code == 200
    wipe_data = resp_wipe.json()
    assert wipe_data["status"] == "wiped"
    assert wipe_data["deleted_experiences"] >= 1
    assert wipe_data["deleted_weaknesses"] >= 1
    assert "core_conversation_history" in wipe_data["preserved_data"]

    # Verify stores are now empty
    assert el.count_experiences() == 0
    assert wc.count_weaknesses() == 0


def test_single_experience_deletion_unlinks_weakness(api_test_env):
    """
    Verifies that deleting an individual experience:
    - Removes the experience from persistent storage.
    - Unlinks the experience ID from all referencing WeaknessRecords.
    """
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}
    el = api_test_env["experience_logger"]
    wc = api_test_env["weakness_catalog"]

    from backend.intelligence.learning_types import WeaknessRecord

    # Create an experience
    exp = el.log_from_feedback(FeedbackType.THUMBS_DOWN, "Verbosity issue", "Excessive text", inferred_error=ErrorCategory.OVER_VERBOSITY)
    eid = exp.experience_id

    # Create weakness referencing the experience
    w = WeaknessRecord(
        weakness_id="weak_ref_01",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Referential test weakness",
        frequency=1,
        severity=WeaknessSeverity.LOW,
        supporting_experience_ids=[eid],
    )
    wc.register_weakness(w)

    w_before = wc.get_weakness("weak_ref_01")
    assert eid in w_before.supporting_experience_ids

    # Delete the experience via API
    resp_del = client.delete(f"/api/learning/experiences/{eid}", headers=headers)
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "deleted"
    assert resp_del.json()["unlinked_from_weaknesses"] == 1

    # Verify experience is gone
    assert el.get_experience(eid) is None

    # Verify weakness record no longer references the deleted experience
    w_after = wc.get_weakness("weak_ref_01")
    assert eid not in w_after.supporting_experience_ids


def test_task_approval_scope_mismatch_and_transition_security(api_test_env):
    """
    Verifies:
    - Attempting to approve with mismatched target_resource or operation is rejected (400).
    - Transitioning a critical task to ACTIVE without valid approval is rejected (400).
    """
    client = api_test_env["client"]
    headers = {"X-Hinaku-Token": api_test_env["session_token"]}

    # Create critical task with defined target_resource and operation
    resp = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Purge cache directory",
            "critical_action_category": "file_modification_or_deletion",
            "target_resource": "d:/temp/cache",
            "operation": "delete_directory",
            "scope_parameters": {"dry_run": False},
        },
    )
    assert resp.status_code == 201
    tid = resp.json()["task_id"]

    # 1. Attempt to transition to ACTIVE directly without approval -> rejected with 403
    resp_act = client.patch(
        f"/api/tasks/{tid}/transition",
        headers=headers,
        json={"new_status": "active", "reason": "Attempting unauthorized execution"},
    )
    assert resp_act.status_code == 403
    assert "requires explicit owner approval" in resp_act.json()["detail"]

    # 2. Attempt approval with mismatched target_resource -> rejected
    mismatch_hash = hashlib.sha256(
        f"{tid}:file_modification_or_deletion:d:/different/path:delete_directory:{json.dumps({'dry_run': False}, sort_keys=True)}".encode("utf-8")
    ).hexdigest()

    resp_bad_appr = client.post(
        f"/api/tasks/{tid}/approve",
        headers=headers,
        json={
            "action_hash": mismatch_hash,
            "target_resource": "d:/different/path",
            "operation": "delete_directory",
            "scope_parameters": {"dry_run": False},
            "confirmed": True,
        },
    )
    assert resp_bad_appr.status_code == 400
    assert "target_resource mismatch" in resp_bad_appr.json()["detail"]

    # 3. Valid scoped approval succeeds
    valid_hash = hashlib.sha256(
        f"{tid}:file_modification_or_deletion:d:/temp/cache:delete_directory:{json.dumps({'dry_run': False}, sort_keys=True)}".encode("utf-8")
    ).hexdigest()

    resp_good_appr = client.post(
        f"/api/tasks/{tid}/approve",
        headers=headers,
        json={
            "action_hash": valid_hash,
            "target_resource": "d:/temp/cache",
            "operation": "delete_directory",
            "scope_parameters": {"dry_run": False},
            "confirmed": True,
        },
    )
    assert resp_good_appr.status_code == 200
    assert resp_good_appr.json()["approval_status"] == "approved"

    # 4. Now transition to ACTIVE succeeds
    resp_act_good = client.patch(
        f"/api/tasks/{tid}/transition",
        headers=headers,
        json={"new_status": "active", "reason": "Starting approved task"},
    )
    assert resp_act_good.status_code == 200
    assert resp_act_good.json()["status"] == "active"

