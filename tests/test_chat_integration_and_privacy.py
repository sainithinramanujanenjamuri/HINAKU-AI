"""
tests/test_chat_integration_and_privacy.py

Comprehensive test suite for Phase 1 Milestone 7 Step 3:
Chat Integration & Privacy Hooks.

Verifies:
1. DomainRouter Project Context Injection:
   - When project_id is provided, DomainRouter assembles and injects ContextBundle.
   - Explicit project selection unconditionally supersedes automatic heuristics.
   - Project ID is persisted on conversation and logged on interactions.
2. Confidential Project Outbound Boundary:
   - Confidential / Restricted projects strictly block external cloud model dispatch.
   - OutboundPrivacyGate raises OutboundPrivacyViolation on confidential project contexts.
3. No Cloud Fallback for Confidential Projects:
   - Simulating a local model failure on a confidential project halts execution;
     it NEVER falls back to an external cloud model.
4. ExperienceLogger Integration & Redaction:
   - Submitting interaction feedback (thumbs_down / thumbs_up) or message edits
     records an ExperienceRecord.
   - Credentials in feedback or edits are automatically redacted to '[removed]'.
"""

import json
import uuid
import pytest
from typing import Any, AsyncGenerator, Dict, List, Optional
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import get_settings
from backend.security.auth import session_token_manager
from backend.models.router import ModelRouter, RouterDecision
from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation
from backend.intelligence.project_engine import ProjectEngine
from backend.intelligence.project_types import (
    ProjectConfidentiality,
    ProjectStatus,
    KnowledgeCategory,
)
from backend.intelligence.types import (
    ImplementationStatus,
    KnowledgeDomain,
    KnowledgeProvenance,
    SourceAuthority,
)
from backend.intelligence.experience_logger import ExperienceLogger
from backend.intelligence.learning_types import FeedbackType, ErrorCategory


class MockStreamingLocalAdapter:
    def __init__(self, default_model: str = "bonsai-2:9b", fail: bool = False):
        self.default_model = default_model
        self.fail = fail
        self.calls: List[Dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        self.calls.append({
            "model": model or self.default_model,
            "messages": [dict(m) for m in messages],
            "kwargs": kwargs
        })
        if self.fail:
            raise RuntimeError("Simulated local Ollama failure")
        yield "Local response grounded in project context."

    async def is_model_loaded(self, model: str) -> bool:
        return True

    async def check_health(self) -> Dict[str, Any]:
        return {"status": "ok", "local": True}


class MockStreamingApiAdapter:
    def __init__(self, model: str = "test-cloud-model", api_key: str = "valid-api-key", fail: bool = False):
        self.provider = "openai_compatible"
        self.model = model
        self.api_key = api_key
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
        # Enforce physical privacy gate
        OutboundPrivacyGate.verify_outbound_payload(
            messages=messages,
            is_private=is_private,
            has_attachments=has_attachments,
        )
        self.transmitted_payloads.append({
            "model": model or self.model,
            "messages": [dict(m) for m in messages],
            "is_private": is_private,
            "has_attachments": has_attachments,
        })
        if self.fail:
            raise RuntimeError("Cloud provider unreachable")
        yield "Cloud API response."


@pytest.fixture
def chat_env(monkeypatch):
    """Sets up isolated environment with mocked model adapters and authenticated session."""
    settings = get_settings()
    token = session_token_manager.get_token()
    client = TestClient(app)

    mock_local = MockStreamingLocalAdapter()
    mock_api = MockStreamingApiAdapter()

    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    return {
        "client": client,
        "token": token,
        "headers": {"X-Hinaku-Token": token},
        "settings": settings,
        "mock_local": mock_local,
        "mock_api": mock_api,
    }


def test_chat_injects_project_context_via_domain_router(chat_env):
    """
    Verifies:
    1. Providing project_id retrieves project context and architectural decisions via DomainRouter.
    2. Context is injected into system prompt.
    3. project_id is persisted on the conversation and returned in ChatResponse.
    """
    client = chat_env["client"]
    headers = chat_env["headers"]
    settings = chat_env["settings"]

    # Register project with decisions in ProjectEngine
    engine = ProjectEngine(settings.sqlite_path)
    proj = engine.register_project(
        name="Apollo Avionics",
        purpose="Guidance navigation and control software",
        confidentiality=ProjectConfidentiality.INTERNAL,
        tech_stack=["Rust", "C++"],
    )
    pid = proj.project_id

    # Add architectural decision
    engine.record_decision(
        project_id=pid,
        title="ADR-001: Zero dynamic memory allocation",
        decision_content="All memory buffers must be statically allocated at compile time.",
        authority=SourceAuthority.OWNER_DIRECTIVE,
    )

    # Invoke chat with explicit project_id
    resp = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "How do we handle memory buffers in Apollo?"}],
            "project_id": pid,
            "stream": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == pid
    cid = data["conversation_id"]

    # Verify context was injected into model call
    calls = chat_env["mock_local"].calls or chat_env["mock_api"].transmitted_payloads
    assert len(calls) >= 1
    system_turn = next(m["content"] for m in calls[-1]["messages"] if m["role"] == "system")
    assert "Apollo Avionics" in system_turn
    assert "Zero dynamic memory allocation" in system_turn
    assert "Guidance navigation and control software" in system_turn

    # Verify conversation retained project_id
    conv_resp = client.get(f"/api/conversations/{cid}", headers=headers)
    assert conv_resp.status_code == 200
    assert conv_resp.json()["project_id"] == pid


def test_explicit_project_selection_supersedes_heuristics(chat_env):
    """
    Verifies that explicit project_id parameter unconditionally supersedes any
    heuristics or other project mentions in the user prompt.
    """
    client = chat_env["client"]
    headers = chat_env["headers"]
    settings = chat_env["settings"]

    engine = ProjectEngine(settings.sqlite_path)
    proj_a = engine.register_project(name="Project Alpha", purpose="Primary chosen project")
    proj_b = engine.register_project(name="Project Beta", purpose="Mentioned in prompt but not active")

    # Pass explicit project_id for Project Alpha while mentioning Project Beta
    resp = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "Tell me about the work we did in Project Beta"}],
            "project_id": proj_a.project_id,
            "stream": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == proj_a.project_id

    calls = chat_env["mock_local"].calls or chat_env["mock_api"].transmitted_payloads
    assert len(calls) >= 1
    system_turn = next(m["content"] for m in calls[-1]["messages"] if m["role"] == "system")
    assert "Project Alpha" in system_turn
    assert "Project Beta" not in system_turn


def test_confidential_project_strictly_blocks_cloud_dispatch(chat_env, monkeypatch):
    """
    Verifies:
    1. Conversations with active CONFIDENTIAL projects strictly block cloud model dispatch.
    2. OutboundPrivacyGate blocks outbound transmission if attempted.
    """
    client = chat_env["client"]
    headers = chat_env["headers"]
    settings = chat_env["settings"]

    engine = ProjectEngine(settings.sqlite_path)
    secret_proj = engine.register_project(
        name="Project Blackhole",
        purpose="Classified gravitational simulation",
        confidentiality=ProjectConfidentiality.CONFIDENTIAL,
    )

    # Force router to api_only mode to verify confidential project overrides it
    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module.model_router, "mode", "api_only")

    resp = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "Explain tensor field equations"}],
            "project_id": secret_proj.project_id,
            "stream": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["backend"] == "local"

    # Verify zero API calls were transmitted
    mock_api = chat_env["mock_api"]
    assert len(mock_api.transmitted_payloads) == 0

    # Verify OutboundPrivacyGate directly rejects payload with confidential project metadata
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=[{"role": "user", "content": "query"}],
            is_private=False,
            has_attachments=False,
            project_confidentiality=ProjectConfidentiality.CONFIDENTIAL,
        )
    assert "strictly prohibited" in str(exc_info.value)


def test_simulated_local_failure_on_confidential_project_halts_never_falls_back(chat_env, monkeypatch):
    """
    Verifies that when local model execution fails on a confidential project,
    execution halts and NEVER falls back to an external cloud model.
    """
    client = chat_env["client"]
    headers = chat_env["headers"]
    settings = chat_env["settings"]

    engine = ProjectEngine(settings.sqlite_path)
    restricted_proj = engine.register_project(
        name="Project Stealth",
        purpose="Restricted radar signature database",
        confidentiality=ProjectConfidentiality.RESTRICTED,
    )

    # Enable router fallback_on_failure
    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module.model_router, "fallback_on_failure", True)

    # Set mock local adapter to fail
    chat_env["mock_local"].fail = True

    resp = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "Analyze stealth cross section"}],
            "project_id": restricted_proj.project_id,
            "stream": False,
        },
    )
    # Execution halts with 502 Bad Gateway (local error)
    assert resp.status_code == 502
    assert "Local model failed" in resp.json()["detail"]

    # Verify cloud provider was NEVER contacted
    mock_api = chat_env["mock_api"]
    assert len(mock_api.transmitted_payloads) == 0


def test_interaction_feedback_and_edits_log_to_experience_logger_with_redaction(chat_env):
    """
    Verifies:
    1. Feedback (thumbs_down) logs an ExperienceRecord with project_id correlation.
    2. Message edits log an ExperienceRecord of type CORRECTION.
    3. Sensitive credentials in feedback / edits are automatically redacted to '[removed]'.
    """
    client = chat_env["client"]
    headers = chat_env["headers"]
    settings = chat_env["settings"]

    engine = ProjectEngine(settings.sqlite_path)
    proj = engine.register_project(name="Auth Gateway", purpose="Authentication service")

    # 1. Send chat message to create interaction
    resp = client.post(
        "/api/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "Generate an API key format"}],
            "project_id": proj.project_id,
            "stream": False,
        },
    )
    assert resp.status_code == 200
    mid = resp.json()["message_id"]
    iid = resp.json()["interaction_id"]

    exp_logger = ExperienceLogger(settings.sqlite_path)
    initial_count = exp_logger.count_experiences()

    # 2. Record thumbs_down feedback
    fb_resp = client.post(
        f"/api/interactions/{iid}/feedback",
        headers=headers,
        json={"feedback": "thumbs_down"},
    )
    assert fb_resp.status_code == 200
    assert exp_logger.count_experiences() == initial_count + 1

    records = exp_logger.list_experiences(project_id=proj.project_id)
    assert len(records) >= 1
    assert records[-1].feedback_type == FeedbackType.THUMBS_DOWN
    assert records[-1].interaction_id == iid

    # 3. Edit message with sensitive credential
    secret_key = "sk-ant-live-0123456789abcdef0123"
    edit_resp = client.post(
        f"/api/messages/{mid}/edit",
        headers=headers,
        json={"edited_answer": f"Here is the corrected key: {secret_key}"},
    )
    assert edit_resp.status_code == 200

    # 4. Verify experience was logged with credentials redacted to '[removed]'
    records_after = exp_logger.list_experiences(project_id=proj.project_id)
    assert len(records_after) >= 2
    # list_experiences returns records ordered by created_at DESC (newest first)
    correction_record = records_after[0]
    assert correction_record.feedback_type == FeedbackType.ACCEPTED_EDIT
    assert secret_key not in correction_record.observed_user_feedback
    assert "[removed]" in correction_record.observed_user_feedback
