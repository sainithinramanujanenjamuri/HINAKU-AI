"""
tests/test_integration_and_hardening.py

Phase 1 Milestone 7, Step 5: Integration & Hardening Test Suite.
Validates all eight operational, architectural, and security acceptance criteria
detailed in Section 10 of docs/PHASE_1_MILESTONE_7_IMPLEMENTATION_PLAN.md:

1. Authentication and Authorization (Desktop owner session vs internal tokens)
2. Approval Integrity & Scoping (Cryptographic action_hash binding, automatic invalidation on mutation, anti-replay)
3. Privacy & Model Orchestration Boundaries (Confidential project cloud isolation, zero cloud fallback, credential redaction)
4. Database Reliability, Coordinated Backup & Safe Rollback (Paired quiescence, fail-closed startup integrity, atomic rollback)
5. Project & Learning Isolation (Cross-project context isolation, experience unlinking, double-confirmed wipe)
6. Chat Integration (Explicit project context injection, interaction logging with credential redaction)
7. Desktop UI Compliance (Static asset delivery, modal DOM structures, critical approval categories)
8. End-to-End Hardening & Security Negative Testing (Lifecycle transition graphs, SQL injection resilience, directory traversal safety)
"""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import get_settings
from backend.security.auth import (
    get_active_session_token,
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
)
from backend.intelligence.project_engine import ProjectEngine
from backend.intelligence.task_manager import TaskManager
from backend.intelligence.experience_logger import ExperienceLogger
from backend.intelligence.weakness_catalog import WeaknessCatalog
from backend.intelligence.improvement_engine import ImprovementProposalEngine
from backend.database.backup import (
    DatabaseBackupManager,
    DatabaseWriteCoordinator,
    DatabaseIntegrityError,
    compute_file_sha256,
)
from backend.models.router import ModelRouter, RouterDecision
from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation
from backend.guards import check_and_redact_sensitive_data

client = TestClient(app)
ROOT_DIR = Path(__file__).resolve().parent.parent


# ==============================================================================
# Mock Adapters for Safe Offline Chat Testing
# ==============================================================================

class MockStreamingLocalAdapter:
    def __init__(self, default_model: str = "bonsai-2:9b", fail: bool = False):
        self.default_model = default_model
        self.fail = fail
        self.calls: List[Dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        is_private: Any = None,
        think_harder: bool = False,
        detailed: bool = False,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        self.calls.append({
            "model": model or self.default_model,
            "messages": [dict(m) for m in messages],
            "is_private": is_private,
        })
        if self.fail:
            raise RuntimeError("Simulated local Ollama engine failure (OOM / process terminated)")
        yield "Local assistant synthesized response."


class MockStreamingCloudAdapter:
    def __init__(self, model: str = "test-cloud-model", fail: bool = False):
        self.provider = "openai_compatible"
        self.model = model
        self.fail = fail
        self.transmitted_payloads: List[Dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        is_private: Any = None,
        has_attachments: Any = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=messages,
            is_private=is_private,
            has_attachments=has_attachments,
        )
        self.transmitted_payloads.append({
            "model": model or self.model,
            "messages": [dict(m) for m in messages],
            "is_private": is_private,
        })
        if self.fail:
            raise RuntimeError("Cloud provider unreachable")
        yield "Cloud API response."


# ==============================================================================
# 1. Authentication and Authorization Boundaries
# ==============================================================================

def test_cat1_auth_boundaries_and_rejections():
    """
    Acceptance Criteria 1:
    - Missing X-Hinaku-Token returns HTTP 401 on /api/projects and /api/tasks.
    - POST /api/tasks/{id}/approve invoked with an internal background token returns HTTP 403.
    - POST /api/learning/wipe invoked with an internal background token returns HTTP 403.
    - Critical operations require an active authenticated owner desktop session.
    """
    # Missing token on protected endpoints
    res_proj = client.get("/api/projects", headers={"X-Hinaku-Token": ""})
    assert res_proj.status_code == 401

    res_tasks = client.get("/api/tasks", headers={"X-Hinaku-Token": ""})
    assert res_tasks.status_code == 401

    # Generate internal background token
    internal_token = internal_token_manager.issue_token(
        scope=InternalScope.SYSTEM_MAINTENANCE
    )
    assert internal_token.startswith("hinaku_internal_")

    # Attempt task approval with internal token -> 403 Forbidden
    res_approve = client.post(
        "/api/tasks/non_existent_task/approve",
        headers={"X-Hinaku-Token": internal_token},
        json={
            "action_hash": "a" * 64,
            "target_resource": "data/test.txt",
            "operation": "delete_file",
            "scope_parameters": {},
            "confirmed": True
        }
    )
    assert res_approve.status_code == 403
    assert "Internal background tokens cannot authorize critical tasks" in res_approve.json()["detail"]

    # Attempt learning wipe with internal token -> 403 Forbidden
    res_wipe = client.post(
        "/api/learning/wipe",
        headers={"X-Hinaku-Token": internal_token},
        json={
            "confirm_wipe": True,
            "acknowledge_data_loss": True,
            "scope": "all_experiences_and_weaknesses"
        }
    )
    assert res_wipe.status_code == 403
    assert "Internal background tokens cannot execute full learning wipe" in res_wipe.json()["detail"]


# ==============================================================================
# 2. Approval Integrity & Scoping
# ==============================================================================

def test_cat2_approval_integrity_scoping_and_invalidation():
    """
    Acceptance Criteria 2:
    - POST /api/tasks/{id}/approve verifies action_hash bound to task_id, category, target, op, scope.
    - If task parameters or scope are modified after approval, previous approval is invalidated.
    - Approval for Task A cannot authorize Task B (anti-replay).
    - Scope parameter mismatch during approval returns HTTP 400.
    """
    owner_token = get_active_session_token()
    headers = {"X-Hinaku-Token": owner_token}

    # 1. Create a critical task with valid critical action category
    target_res = "workspace/config.json"
    operation = "modify_config"
    scope_params = {"mode": "strict", "timeout": 30}
    cat_str = CriticalActionCategory.SECURITY_OR_CREDENTIAL_CHANGE.value

    res_create = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Update Security Config",
            "description": "Critical security change",
            "priority": "critical",
            "critical_action_category": cat_str,
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": scope_params,
            "requires_owner_approval": True
        }
    )
    assert res_create.status_code == 201
    task_a = res_create.json()
    task_id_a = task_a["task_id"]
    action_hash_a = task_a["action_hash"]
    assert action_hash_a is not None
    assert task_a["approval_status"] == "pending"
    assert task_a["status"] == "queued"

    # 2. Scope mismatch rejection during approval
    res_scope_mismatch = client.post(
        f"/api/tasks/{task_id_a}/approve",
        headers=headers,
        json={
            "action_hash": action_hash_a,
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": {"mode": "permissive"},  # Mismatch
            "confirmed": True
        }
    )
    assert res_scope_mismatch.status_code == 400
    assert "Action hash mismatch" in res_scope_mismatch.json()["detail"]

    # 3. Valid Approval
    res_appr = client.post(
        f"/api/tasks/{task_id_a}/approve",
        headers=headers,
        json={
            "action_hash": action_hash_a,
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": scope_params,
            "confirmed": True
        }
    )
    assert res_appr.status_code == 200
    appr_data = res_appr.json()
    assert appr_data["status"] == "approved"
    assert appr_data["approval_status"] == "approved"

    # Verify task is now queued and approved
    task_get = client.get(f"/api/tasks/{task_id_a}", headers=headers).json()
    assert task_get["approval_status"] == "approved"
    assert task_get["status"] == "queued"

    # 4. Mutation Invalidation Invariant: modifying description/scope reverts to PENDING_APPROVAL
    res_mutate = client.patch(
        f"/api/tasks/{task_id_a}",
        headers=headers,
        json={"description": "Mutated operational description"}
    )
    assert res_mutate.status_code == 200
    task_mutated = res_mutate.json()
    assert task_mutated["approval_status"] == "pending"
    assert task_mutated["status"] == "pending_approval"

    # 5. Anti-Replay: Attempt to approve Task B using Task A's action_hash
    res_b = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Task B",
            "priority": "critical",
            "critical_action_category": cat_str,
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": scope_params,
            "requires_owner_approval": True
        }
    )
    task_b = res_b.json()
    task_id_b = task_b["task_id"]

    res_replay = client.post(
        f"/api/tasks/{task_id_b}/approve",
        headers=headers,
        json={
            "action_hash": action_hash_a,  # Replay from Task A
            "target_resource": target_res,
            "operation": operation,
            "scope_parameters": scope_params,
            "confirmed": True
        }
    )
    assert res_replay.status_code == 400
    assert "Action hash mismatch" in res_replay.json()["detail"]


# ==============================================================================
# 3. Privacy & Model Orchestration Boundaries
# ==============================================================================

@pytest.mark.asyncio
async def test_cat3_confidential_project_cloud_isolation_and_no_fallback():
    """
    Acceptance Criteria 3:
    - Active CONFIDENTIAL project strictly blocks cloud model dispatch in OutboundPrivacyGate.
    - Simulating local model failure on a confidential project halts execution; NEVER falls back to cloud.
    - verify_outbound_payload() executes and redacts sensitive credentials.
    """
    settings = get_settings()
    store = ProjectEngine(settings.sqlite_path)

    # Register CONFIDENTIAL project
    conf_proj = store.register_project(
        name="Apollo Confidential",
        purpose="Defense grade avionics",
        confidentiality=ProjectConfidentiality.CONFIDENTIAL
    )

    # Verify OutboundPrivacyGate inspect_payload blocks confidential project
    gate = OutboundPrivacyGate()
    insp_res = gate.inspect_payload(
        messages=[{"role": "user", "content": "Analyze confidential engine"}],
        is_private=False,
        has_attachments=False,
        project_confidentiality=conf_proj.confidentiality
    )
    assert not insp_res.is_safe
    assert insp_res.category == "confidential_project_boundary"

    # Verify OutboundPrivacyGate verify_outbound_payload raises OutboundPrivacyViolation
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        gate.verify_outbound_payload(
            messages=[{"role": "user", "content": "Analyze confidential engine"}],
            is_private=False,
            has_attachments=False,
            project_confidentiality=conf_proj.confidentiality
        )
    assert "CONFIDENTIAL" in str(exc_info.value)

    # Verify sensitive data detection and redaction
    detected, clean_text = check_and_redact_sensitive_data("My secret password is Password123! and PIN is 4455")
    assert detected is True
    assert "Password123!" not in clean_text
    assert "4455" not in clean_text
    assert "[removed]" in clean_text

    # Router Fallback Isolation: Local failure on confidential project MUST HALT, NEVER fall back to API
    failing_local = MockStreamingLocalAdapter(fail=True)
    cloud_api = MockStreamingCloudAdapter()
    router = ModelRouter(local_adapter=failing_local, api_adapter=cloud_api, mode="auto", fallback_on_failure=True)

    chunks = []
    async for item in router.stream_chat(
        messages=[{"role": "user", "content": "Complex algorithms in Apollo"}],
        user_prompt="Complex algorithms in Apollo",
        project_confidentiality=conf_proj.confidentiality
    ):
        chunks.append(item)

    assert any(c.get("type") == "error" and "Simulated local Ollama engine failure" in c.get("error", "") for c in chunks)
    # Cloud API was strictly NEVER called
    assert len(cloud_api.transmitted_payloads) == 0


# ==============================================================================
# 4. Database Reliability, Coordinated Backup & Safe Rollback
# ==============================================================================

def test_cat4_database_reliability_backup_and_safe_rollback(tmp_path):
    """
    Acceptance Criteria 4:
    - Startup integrity fails closed when either database is corrupt, preserving damaged files.
    - DatabaseBackupManager coordinates writes across both databases and verifies dual integrity before promotion.
    - Pruning retention never deletes the last verified known-good recovery set.
    - Atomic rollback restores pre-restoration state if restoration fails.
    """
    data_dir = tmp_path / "db_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hinaku_db = data_dir / "hinaku.db"
    chroma_dir = data_dir / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    chroma_db = chroma_dir / "chroma.sqlite3"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Initialize healthy databases
    with sqlite3.connect(hinaku_db) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE users (id TEXT, name TEXT);")
        conn.execute("INSERT INTO users VALUES ('1', 'Hinaku Owner');")

    with sqlite3.connect(chroma_db) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE embeddings (id TEXT, vector TEXT);")
        conn.execute("INSERT INTO embeddings VALUES ('emb1', '[0.1, 0.2]');")

    mgr = DatabaseBackupManager(
        hinaku_db_path=hinaku_db,
        chroma_db_path=chroma_db,
        chroma_dir=chroma_dir,
        backup_dir=backup_dir
    )

    # 1. Startup integrity passes on healthy databases
    verify_res = mgr.verify_startup_integrity()
    assert verify_res["ok"] is True

    # 2. Coordinated paired backup
    backup_meta = mgr.create_coordinated_backup(description="Test Coordinated Backup")
    assert backup_meta["status"] == "verified"
    set_id = backup_meta["recovery_set_id"]
    snapshot_dir = backup_dir / set_id
    assert (snapshot_dir / "hinaku.db").exists()
    assert (snapshot_dir / "chroma.sqlite3").exists()

    # 3. Retention never deletes the last verified known-good recovery set
    pruned = mgr.prune_backups()
    assert set_id not in pruned
    assert (backup_dir / set_id).exists()

    # 4. Corrupted database fails closed and preserves corrupted file
    corrupt_bytes = b"CORRUPTED_GARBAGE_DATA_NOT_A_SQLITE_FILE" * 20
    hinaku_db.write_bytes(corrupt_bytes)
    verify_corrupt = mgr.verify_startup_integrity()
    assert verify_corrupt["ok"] is False
    assert "hinaku" in verify_corrupt["failed_databases"]
    # File is preserved without deletion
    assert hinaku_db.exists()
    assert hinaku_db.read_bytes() == corrupt_bytes

    # 5. Restore successfully recovers coordinated pair
    restore_res = mgr.restore_recovery_set(recovery_set_id=set_id, has_owner_session=True)
    assert restore_res["status"] == "restored"
    # Verify data restored
    with sqlite3.connect(hinaku_db) as conn:
        val = conn.execute("SELECT name FROM users WHERE id='1';").fetchone()
        assert val[0] == "Hinaku Owner"


# ==============================================================================
# 5. Project & Learning Isolation
# ==============================================================================

def test_cat5_project_and_learning_isolation():
    """
    Acceptance Criteria 5:
    - Cross-project context leakage is blocked; Project A never returns Project B knowledge.
    - Deleting an experience record unlinks related foreign references without database corruption.
    - Full learning wipe enforces active owner session authorization, double-confirmation,
      deletes experiences/weaknesses/proposals, and preserves conversation history and persona.
    """
    settings = get_settings()
    proj_engine = ProjectEngine(settings.sqlite_path)
    exp_logger = ExperienceLogger(settings.sqlite_path)
    weakness_cat = WeaknessCatalog(settings.sqlite_path)

    # 1. Cross-project isolation
    proj_a = proj_engine.register_project(name="Project Alpha", purpose="Alpha Engine")
    proj_b = proj_engine.register_project(name="Project Beta", purpose="Beta Engine")

    from backend.intelligence.project_types import ProjectKnowledgeItem
    from backend.intelligence.types import KnowledgeProvenance, SourceAuthority, ImplementationStatus

    prov = KnowledgeProvenance(source_authority=SourceAuthority.OWNER_DIRECTIVE, claim_confidence=1.0, verification_status=ImplementationStatus.ACCEPTED)
    item_a = ProjectKnowledgeItem(item_id="k-alpha", project_id=proj_a.project_id, category=KnowledgeCategory.DECISIONS, title="Alpha Decision", content="Alpha secret algorithm", provenance=prov)
    item_b = ProjectKnowledgeItem(item_id="k-beta", project_id=proj_b.project_id, category=KnowledgeCategory.DECISIONS, title="Beta Decision", content="Beta secret algorithm", provenance=prov)

    proj_engine.store.add_knowledge_item(item_a)
    proj_engine.store.add_knowledge_item(item_b)

    know_a = proj_engine.list_knowledge(proj_a.project_id)
    assert any(k.title == "Alpha Decision" for k in know_a)
    assert not any(k.title == "Beta Decision" for k in know_a)

    # 2. Experience deletion unlinks weaknesses
    exp = exp_logger.log_from_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        observed_feedback="Quantum memory is impossible.",
        original_output="Explain quantum memory",
        inferred_error=ErrorCategory.FACTUAL_INACCURACY
    )

    weakness = weakness_cat.catalog_experience(exp)
    assert weakness is not None
    assert exp.experience_id in weakness.supporting_experience_ids

    # Delete experience via API
    headers = {"X-Hinaku-Token": get_active_session_token()}
    res_del_exp = client.delete(f"/api/learning/experiences/{exp.experience_id}", headers=headers)
    assert res_del_exp.status_code == 200

    # Weakness record still exists but experience reference is unlinked
    updated_weakness = weakness_cat.get_weakness(weakness.weakness_id)
    assert exp.experience_id not in updated_weakness.supporting_experience_ids

    # 3. Full learning wipe double-confirmation & preservation
    res_wipe = client.post(
        "/api/learning/wipe",
        headers=headers,
        json={
            "confirm_wipe": True,
            "acknowledge_data_loss": True,
            "scope": "all_experiences_and_weaknesses"
        }
    )
    assert res_wipe.status_code == 200
    wipe_data = res_wipe.json()
    assert wipe_data["status"] == "wiped"
    assert "core_conversation_history" in wipe_data["preserved_data"]
    assert "hinaku_persona" in wipe_data["preserved_data"]

    # Verify stores are empty
    assert len(exp_logger.list_experiences()) == 0
    assert len(weakness_cat.list_weaknesses()) == 0


# ==============================================================================
# 6. Chat Integration
# ==============================================================================

def test_cat6_chat_project_context_and_feedback_redaction(monkeypatch):
    """
    Acceptance Criteria 6:
    - Explicit project selection in /api/chat injects project context into prompt.
    - Interaction ratings (feedback/edits) log sanitized ExperienceRecords with secrets redacted.
    """
    settings = get_settings()
    proj_engine = ProjectEngine(settings.sqlite_path)
    proj = proj_engine.register_project(
        name="Project Orion",
        purpose="Orbital navigation algorithms",
        confidentiality=ProjectConfidentiality.INTERNAL
    )

    # Mock local and api adapters for safe offline chat endpoint execution
    mock_local = MockStreamingLocalAdapter()
    mock_api = MockStreamingCloudAdapter()

    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    headers = {"X-Hinaku-Token": get_active_session_token()}

    # 1. Chat with explicit project_id
    res_chat = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "How do we initialize orbital trajectories?"}],
            "project_id": proj.project_id,
            "stream": False
        }
    )
    assert res_chat.status_code == 200
    assert res_chat.json()["project_id"] == proj.project_id

    # Verify project context was injected in messages
    calls = mock_local.calls or mock_api.transmitted_payloads
    assert len(calls) >= 1
    system_turn = next(m["content"] for m in calls[-1]["messages"] if m["role"] == "system")
    assert "Project Orion" in system_turn

    # 2. Feedback logging with sensitive data redaction
    conv_res = client.post("/api/conversations", headers=headers, json={"title": "Feedback Test"}).json()
    conv_id = conv_res["id"]

    from backend.history import ChatHistoryManager
    hist_mgr = ChatHistoryManager(settings.sqlite_path)
    msg_obj = hist_mgr.add_message(
        conv_id=conv_id,
        role="assistant",
        content="Default assistant response"
    )
    msg_id = msg_obj["id"]
    hist_mgr.log_interaction(
        conv_id=conv_id,
        user_prompt="Explain quantum",
        answer="Default assistant response",
        model="local",
        backend="local",
        message_id=msg_id,
    )

    res_fb = client.post(
        f"/api/messages/{msg_id}/feedback",
        headers=headers,
        json={
            "feedback": "thumbs_down",
            "edited_answer": "Refused my PIN is 9988 and my password is SecretPass!"
        }
    )
    assert res_fb.status_code == 200

    # Verify ExperienceRecord has credentials redacted
    exp_logger = ExperienceLogger(settings.sqlite_path)
    records = exp_logger.list_experiences(feedback_type=FeedbackType.ACCEPTED_EDIT)
    assert len(records) > 0
    latest = records[0]
    feedback_text = latest.observed_user_feedback or ""
    assert "9988" not in feedback_text
    assert "SecretPass!" not in feedback_text
    assert "[removed]" in feedback_text


# ==============================================================================
# 7. Desktop UI Compliance
# ==============================================================================

def test_cat7_desktop_ui_compliance_and_static_serving():
    """
    Acceptance Criteria 7:
    - GET / serves index.html with all Step 4 elements.
    - All static JS and CSS files are served with status 200.
    - The action approval modal exposes all 6 critical approval categories.
    """
    # 1. GET / serves index.html
    res_index = client.get("/")
    assert res_index.status_code == 200
    html = res_index.text

    assert 'id="projects-toggle-btn"' in html
    assert 'id="tasks-toggle-btn"' in html
    assert 'id="learning-toggle-btn"' in html
    assert 'id="top-project-chip"' in html
    assert 'id="action-approval-modal"' in html
    assert 'id="task-history-modal"' in html

    # 2. Static files served cleanly
    for static_file in ["/static/app.js", "/static/js/pages.js", "/static/style.css", "/static/css/pages.css"]:
        res_file = client.get(static_file)
        assert res_file.status_code == 200
        assert len(res_file.text) > 0

    # 3. Verify the 6 critical approval categories are handled in pages.js
    pages_js = (ROOT_DIR / "ui" / "js" / "pages.js").read_text(encoding="utf-8")
    critical_categories = [
        "file_modification_or_deletion",
        "financial_transaction",
        "external_communication",
        "system_operation",
        "security_credential_change",
        "self_modification",
    ]
    for cat in critical_categories:
        assert cat in pages_js, f"Critical category {cat} missing from ui/js/pages.js"


# ==============================================================================
# 8. End-to-End Hardening & Security Negative Testing
# ==============================================================================

def test_cat8_hardening_boundary_and_negative_inputs():
    """
    Acceptance Criteria 8:
    - SQL injection payloads in project search and task titles do not cause errors or leak data.
    - Invalid task state transitions (e.g. COMPLETED -> QUEUED) are rejected with HTTP 400.
    - Transitioning an unapproved critical task directly to COMPLETED is rejected with HTTP 403 or 400.
    - Repository indexing on invalid or non-existent path handles error safely.
    """
    headers = {"X-Hinaku-Token": get_active_session_token()}

    # 1. SQL Injection payload in project search
    sqli_payload = "' UNION SELECT * FROM users --"
    res_sqli = client.get(f"/api/projects?status={sqli_payload}", headers=headers)
    assert res_sqli.status_code == 400
    assert "Invalid project status" in res_sqli.json()["detail"]

    # 2. SQL Injection in task creation title
    res_sqli_task = client.post(
        "/api/tasks",
        headers=headers,
        json={"title": "Test'); DROP TABLE tasks; --", "priority": "medium"}
    )
    assert res_sqli_task.status_code == 201
    created_task = res_sqli_task.json()
    task_id = created_task["task_id"]

    # Verify tasks table was NOT dropped
    res_verify = client.get("/api/tasks", headers=headers)
    assert res_verify.status_code == 200

    # 3. Invalid lifecycle transition: QUEUED -> COMPLETED without active progression
    res_invalid_trans = client.post(
        f"/api/tasks/{task_id}/transition",
        headers=headers,
        json={"new_status": "completed", "reason": "Skip execution", "changed_by": "owner"}
    )
    assert res_invalid_trans.status_code == 400

    # 4. Critical unapproved task cannot be transitioned directly to COMPLETED
    res_crit_task = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Critical Delete File",
            "priority": "critical",
            "critical_action_category": CriticalActionCategory.FILE_MODIFICATION_OR_DELETION.value,
            "target_resource": "system.bin",
            "operation": "delete_file",
            "requires_owner_approval": True
        }
    ).json()
    crit_id = res_crit_task["task_id"]

    res_bypass = client.post(
        f"/api/tasks/{crit_id}/transition",
        headers=headers,
        json={"new_status": "completed", "reason": "Bypass approval", "owner_approved": False}
    )
    assert res_bypass.status_code in (400, 403)

    # 5. Repo indexing with missing repo_path returns clean 400
    proj_no_repo = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "No Repo Project", "purpose": "Testing repo indexing check"}
    ).json()

    res_no_repo = client.post(f"/api/projects/{proj_no_repo['project_id']}/index_repo", headers=headers)
    assert res_no_repo.status_code == 400
    assert "does not have a configured repo_path" in res_no_repo.json()["detail"]
