"""
tests/test_authorization.py

Comprehensive test suite verifying local session authorization,
the "SECURE BY DEFAULT" principle for all state-changing endpoints,
absence of unintended side effects on rejected requests,
and the scoped internal authorization model for background tasks.
"""

import os
import secrets
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.security.auth import (
    SessionTokenManager,
    get_active_session_token,
    set_active_session_token,
    rotate_active_session_token,
    InternalScope,
    InternalAuthorizationError,
    CRITICAL_OWNER_ACTIONS,
    InternalTokenManager,
    internal_token_manager,
    validate_internal_scope,
    assert_owner_session_required
)
from backend.history import ChatHistoryManager
from backend.config import get_settings

client = TestClient(app)
settings = get_settings()
history_mgr = ChatHistoryManager(db_path=settings.sqlite_path)

UNAUTH_HEADERS = {"X-Hinaku-Token": "", "Authorization": ""}
INVALID_HEADERS = {"X-Hinaku-Token": "invalid_session_token_1234567890abcdef"}


# ==============================================================================
# 1. State-Changing Endpoints: Reject Unauthorized Requests (HTTP 401)
# ==============================================================================
def test_unauthorized_post_chat_rejected():
    """Verify POST /api/chat returns 401 without valid session authorization."""
    res = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Hello"}]},
        headers=UNAUTH_HEADERS
    )
    assert res.status_code == 401
    assert "Unauthorized" in res.json().get("detail", "")


def test_unauthorized_conversations_endpoints_rejected():
    """Verify POST and PATCH /api/conversations return 401 without valid session token."""
    # POST /api/conversations
    res_create = client.post(
        "/api/conversations",
        json={"title": "Unauthorized Conv", "is_private": False},
        headers=UNAUTH_HEADERS
    )
    assert res_create.status_code == 401

    # PATCH /api/conversations/{conv_id}
    res_patch = client.patch(
        "/api/conversations/non-existent-conv",
        json={"title": "Hacked Title", "is_private": True},
        headers=UNAUTH_HEADERS
    )
    assert res_patch.status_code == 401


def test_unauthorized_attachments_upload_rejected():
    """Verify POST /api/conversations/{id}/attachments returns 401 without valid token."""
    payload = {
        "files": [
            {
                "filename": "exploit.txt",
                "content_base64": "SGVsbG8gV29ybGQ=",
                "mime_type": "text/plain"
            }
        ]
    }
    res = client.post(
        "/api/conversations/any-conv-id/attachments",
        json=payload,
        headers=UNAUTH_HEADERS
    )
    assert res.status_code == 401


def test_unauthorized_interactions_and_feedback_rejected():
    """Verify interaction feedback and message edit return 401 without valid token."""
    # POST /api/interactions/{id}/feedback
    res_fb = client.post(
        "/api/interactions/any-id/feedback",
        json={"feedback": "thumbs_up"},
        headers=UNAUTH_HEADERS
    )
    assert res_fb.status_code == 401

    # POST /api/messages/{id}/feedback
    res_msg_fb = client.post(
        "/api/messages/any-id/feedback",
        json={"feedback": "thumbs_down"},
        headers=UNAUTH_HEADERS
    )
    assert res_msg_fb.status_code == 401

    # POST /api/messages/{id}/edit
    res_edit = client.post(
        "/api/messages/any-id/edit",
        json={"edited_answer": "Unauthorized edit"},
        headers=UNAUTH_HEADERS
    )
    assert res_edit.status_code == 401


def test_unauthorized_self_build_remind_later_rejected():
    """Verify POST /api/self-build/remind-later returns 401 without valid token."""
    res = client.post("/api/self-build/remind-later", headers=UNAUTH_HEADERS)
    assert res.status_code == 401


# ==============================================================================
# 2. Side-Effect Verification: Rejected Requests Mutate No State
# ==============================================================================
def test_rejected_create_conversation_produces_no_db_side_effects():
    """Verify an unauthorized conversation creation does not insert any database rows."""
    from backend.api.conversations import history_manager as hm
    initial_convs = hm.list_conversations()
    initial_ids = {c["id"] for c in initial_convs}

    res = client.post(
        "/api/conversations",
        json={"title": "Should Not Exist", "is_private": False},
        headers=UNAUTH_HEADERS
    )
    assert res.status_code == 401

    after_convs = hm.list_conversations()
    after_ids = {c["id"] for c in after_convs}
    assert initial_ids == after_ids


def test_rejected_patch_conversation_produces_no_db_side_effects():
    """Verify an unauthorized PATCH request does not alter conversation privacy or title."""
    from backend.api.conversations import history_manager as hm
    token = get_active_session_token()
    # Create legitimate conversation first with auth
    res_create = client.post(
        "/api/conversations",
        json={"title": "Original Title", "is_private": False},
        headers={"X-Hinaku-Token": token}
    )
    assert res_create.status_code == 200
    conv_id = res_create.json()["id"]

    try:
        # Attempt unauthorized modification of privacy and title
        res_patch = client.patch(
            f"/api/conversations/{conv_id}",
            json={"title": "Tampered Title", "is_private": True},
            headers=UNAUTH_HEADERS
        )
        assert res_patch.status_code == 401

        # Check conversation in DB
        conv = hm.get_conversation(conv_id)
        assert conv is not None
        assert conv["title"] == "Original Title"
        assert conv["is_private"] == 0
    finally:
        hm.delete_conversation(conv_id)


def test_rejected_message_edit_produces_no_db_side_effects():
    """Verify an unauthorized message edit does not mutate message content."""
    from backend.api.conversations import history_manager as hm
    token = get_active_session_token()
    # Create conversation and add a message
    res_create = client.post(
        "/api/conversations",
        json={"title": "Msg Test", "is_private": False},
        headers={"X-Hinaku-Token": token}
    )
    conv_id = res_create.json()["id"]

    try:
        msg_rec = hm.add_message(
            conv_id=conv_id,
            role="assistant",
            content="Original unedited answer.",
            model="local"
        )
        msg_id = msg_rec["id"]

        # Attempt unauthorized edit
        res_edit = client.post(
            f"/api/messages/{msg_id}/edit",
            json={"edited_answer": "Attacker modification"},
            headers=UNAUTH_HEADERS
        )
        assert res_edit.status_code == 401

        # Verify DB content unchanged
        msg = hm.get_message(msg_id)
        assert msg is not None
        assert msg["content"] == "Original unedited answer."
    finally:
        hm.delete_conversation(conv_id)


def test_rejected_remind_later_produces_no_metadata_mutation():
    """Verify unauthorized POST /api/self-build/remind-later does not modify snooze metadata."""
    from backend.api.conversations import history_manager as hm
    original_snooze = hm.get_metadata("self_build_snoozed_until")

    res = client.post("/api/self-build/remind-later", headers=UNAUTH_HEADERS)
    assert res.status_code == 401

    after_snooze = hm.get_metadata("self_build_snoozed_until")
    assert original_snooze == after_snooze


# ==============================================================================
# 3. Authorized Requests: Successful Execution with Valid Desktop Token
# ==============================================================================
def test_authorized_requests_succeed():
    """Verify requests with active session token succeed."""
    token = get_active_session_token()
    auth_headers = {"X-Hinaku-Token": token}

    # Create conversation succeeds
    res_create = client.post(
        "/api/conversations",
        json={"title": "Authorized Title", "is_private": False},
        headers=auth_headers
    )
    assert res_create.status_code == 200
    conv_id = res_create.json()["id"]

    try:
        # Update conversation succeeds
        res_patch = client.patch(
            f"/api/conversations/{conv_id}",
            json={"title": "Updated Title", "is_private": True},
            headers=auth_headers
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["title"] == "Updated Title"
        assert res_patch.json()["is_private"] == 1

        # Authorization via Bearer header also succeeds
        bearer_headers = {"Authorization": f"Bearer {token}"}
        res_bearer_patch = client.patch(
            f"/api/conversations/{conv_id}",
            json={"title": "Bearer Updated Title"},
            headers=bearer_headers
        )
        assert res_bearer_patch.status_code == 200
        assert res_bearer_patch.json()["title"] == "Bearer Updated Title"

    finally:
        # Delete conversation succeeds with auth
        res_del = client.delete(f"/api/conversations/{conv_id}", headers=auth_headers)
        assert res_del.status_code == 200


# ==============================================================================
# 4. Scoped Internal Authorization Model for Background Tasks
# ==============================================================================
def test_internal_token_lifecycle_and_scope_validation():
    """Verify internal tokens are created with specific scopes and validated correctly."""
    mgr = InternalTokenManager()

    # Issue token for scheduler scope
    sched_token = mgr.issue_token(InternalScope.BACKGROUND_SCHEDULER, ttl_seconds=60)
    assert sched_token.startswith("hinaku_internal_")

    # Validate against correct scope
    assert mgr.validate_token(sched_token, InternalScope.BACKGROUND_SCHEDULER) is True

    # Validate against wrong scope -> fails
    assert mgr.validate_token(sched_token, InternalScope.BACKGROUND_MEMORY) is False
    assert mgr.validate_token(sched_token, InternalScope.BACKGROUND_PREWARM) is False

    # Revoke token
    mgr.revoke_token(sched_token)
    assert mgr.validate_token(sched_token, InternalScope.BACKGROUND_SCHEDULER) is False


def test_internal_token_expiration():
    """Verify internal tokens expire after their TTL."""
    mgr = InternalTokenManager()
    short_token = mgr.issue_token(InternalScope.BACKGROUND_PREWARM, ttl_seconds=0.05)
    assert mgr.validate_token(short_token, InternalScope.BACKGROUND_PREWARM) is True

    time.sleep(0.06)
    assert mgr.validate_token(short_token, InternalScope.BACKGROUND_PREWARM) is False


def test_internal_tokens_cannot_authenticate_api_endpoints():
    """
    CRITICAL SECURITY CHECK:
    Verify that an internal background token CANNOT be used to authenticate external API endpoints.
    An internal token presented to require_session_auth must fail closed (HTTP 401).
    """
    internal_token = internal_token_manager.issue_token(InternalScope.BACKGROUND_SCHEDULER, ttl_seconds=60)

    # Attempt to call state-changing endpoints with internal token
    res_chat = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "bypass"}]},
        headers={"X-Hinaku-Token": internal_token}
    )
    assert res_chat.status_code == 401
    assert "Unauthorized" in res_chat.json().get("detail", "")

    res_conv = client.post(
        "/api/conversations",
        json={"title": "Bypass Conv"},
        headers={"X-Hinaku-Token": internal_token}
    )
    assert res_conv.status_code == 401

    res_bearer = client.get(
        "/api/settings/export",
        headers={"Authorization": f"Bearer {internal_token}", "X-Hinaku-Token": ""}
    )
    assert res_bearer.status_code == 401


def test_critical_owner_actions_cannot_be_executed_autonomously():
    """
    CRITICAL SECURITY CHECK:
    Verify that critical actions (promote, rollback, wipe, export) strictly require
    direct human owner authorization and cannot be run autonomously by background tasks
    or AI planning loops.
    """
    for action in CRITICAL_OWNER_ACTIONS:
        # When has_owner_session is False, must raise InternalAuthorizationError
        with pytest.raises(InternalAuthorizationError) as exc_info:
            assert_owner_session_required(action, has_owner_session=False)
        assert "restricted to owner desktop authorization" in str(exc_info.value)

        # When has_owner_session is True, must pass without error
        assert_owner_session_required(action, has_owner_session=True)


# ==============================================================================
# 5. Sensitive Read Endpoints: Reject Unauthorized Requests (HTTP 401)
# ==============================================================================
@pytest.mark.parametrize("endpoint", [
    "/api/conversations",
    "/api/conversations/dummy-conv-id",
    "/api/conversations/dummy-conv-id/attachments",
    "/api/settings",
    "/api/settings/model-options",
    "/api/interactions/ratings-by-model",
    "/api/interactions/1",
    "/api/training/curate",
    "/api/training/datasets",
    "/api/training/preflight",
    "/api/training/promotions",
    "/api/training/pending-approval",
    "/api/self-build/status",
    "/api/self-build/check-due",
    "/api/self-build/reports",
    "/api/self-build/reports/latest",
])
def test_unauthorized_sensitive_read_endpoints_rejected(endpoint: str):
    """
    CRITICAL SECURITY CHECK:
    Verify that sensitive read-only endpoints require valid desktop session authorization.
    Unauthorized calls (missing or invalid token) must return HTTP 401.
    """
    res = client.get(endpoint, headers=UNAUTH_HEADERS)
    assert res.status_code == 401, f"Expected 401 for unauthorized GET {endpoint}, got {res.status_code}"

    res_invalid = client.get(endpoint, headers=INVALID_HEADERS)
    assert res_invalid.status_code == 401, f"Expected 401 for invalid token GET {endpoint}, got {res_invalid.status_code}"


# ==============================================================================
# 6. Public Non-Sensitive Endpoints: Accessible Without Authentication
# ==============================================================================
@pytest.mark.parametrize("endpoint", [
    "/",
    "/health",
    "/api/info",
    "/api/health/ollama",
    "/api/demo/status",
    "/api/demo/info",
    "/api/demo/settings",
    "/api/demo/conversations",
])
def test_public_non_sensitive_endpoints_accessible_without_auth(endpoint: str):
    """
    Verify that genuinely public endpoints (health checks, static UI, demo fixtures/info)
    remain accessible without session authentication.
    """
    res = client.get(endpoint, headers=UNAUTH_HEADERS)
    assert res.status_code == 200, f"Expected 200 for public GET {endpoint}, got {res.status_code}"


# ==============================================================================
# 7. Internal Scope Validation Helper Verification
# ==============================================================================
def test_validate_internal_scope_enforcement():
    """Verify validate_internal_scope enforces valid tokens, correct scope, and expiry."""
    token = internal_token_manager.issue_token(InternalScope.BACKGROUND_SCHEDULER, ttl_seconds=60)

    # Valid scope passes without raising
    validate_internal_scope(token, InternalScope.BACKGROUND_SCHEDULER)

    # Wrong scope raises InternalAuthorizationError
    with pytest.raises(InternalAuthorizationError) as exc_info:
        validate_internal_scope(token, InternalScope.BACKGROUND_MEMORY)
    assert f"scope '{InternalScope.BACKGROUND_MEMORY.value}' is required" in str(exc_info.value)

    # Missing/None token raises InternalAuthorizationError
    with pytest.raises(InternalAuthorizationError):
        validate_internal_scope(None, InternalScope.BACKGROUND_SCHEDULER)

    # Expired token raises InternalAuthorizationError
    short_token = internal_token_manager.issue_token(InternalScope.BACKGROUND_PREWARM, ttl_seconds=0.05)
    time.sleep(0.06)
    with pytest.raises(InternalAuthorizationError):
        validate_internal_scope(short_token, InternalScope.BACKGROUND_PREWARM)

