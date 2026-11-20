import pytest
import time
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation
from backend.models.api_adapter import ApiAdapter
from backend.security.auth import (
    SessionTokenManager,
    get_active_session_token,
    set_active_session_token,
    rotate_active_session_token
)

client = TestClient(app)


# ==============================================================================
# 1. Missing and Invalid Privacy & Attachment Metadata (Fail-Closed)
# ==============================================================================
def test_missing_privacy_metadata():
    """Verify missing is_private metadata (None) fails closed immediately."""
    valid_messages = [{"role": "user", "content": "Explain binary search."}]
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=valid_messages,
            is_private=None,
            has_attachments=False
        )
    assert exc_info.value.category == "invalid_privacy_metadata"
    assert "is_private" in str(exc_info.value)


def test_invalid_privacy_metadata():
    """Verify non-boolean is_private metadata (str, int, dict) fails closed."""
    valid_messages = [{"role": "user", "content": "Explain binary search."}]
    for invalid_val in ["true", "false", 1, 0, {}, []]:
        with pytest.raises(OutboundPrivacyViolation) as exc_info:
            OutboundPrivacyGate.verify_outbound_payload(
                messages=valid_messages,
                is_private=invalid_val,
                has_attachments=False
            )
        assert exc_info.value.category == "invalid_privacy_metadata"


def test_missing_attachment_metadata():
    """Verify missing or non-boolean has_attachments fails closed immediately."""
    valid_messages = [{"role": "user", "content": "Explain binary search."}]
    for invalid_val in [None, "true", "false", 1, 0, {}]:
        with pytest.raises(OutboundPrivacyViolation) as exc_info:
            OutboundPrivacyGate.verify_outbound_payload(
                messages=valid_messages,
                is_private=False,
                has_attachments=invalid_val
            )
        assert exc_info.value.category == "invalid_attachment_metadata"


# ==============================================================================
# 2. Unknown Message Roles & Structure Validation
# ==============================================================================
def test_unknown_message_roles():
    """Verify roles outside {system, developer, user, assistant, tool} fail closed."""
    for bad_role in ["admin", "custom_agent", "function", "bot", "moderator", ""]:
        payload = [{"role": bad_role, "content": "Hello"}]
        with pytest.raises(OutboundPrivacyViolation) as exc_info:
            OutboundPrivacyGate.verify_outbound_payload(
                messages=payload,
                is_private=False,
                has_attachments=False
            )
        assert exc_info.value.category == "unsupported_role"


def test_missing_message_keys():
    """Verify messages missing 'role' or 'content' keys fail closed."""
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=[{"content": "missing role"}],
            is_private=False,
            has_attachments=False
        )
    assert exc_info.value.category == "malformed_payload"

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=[{"role": "user"}],
            is_private=False,
            has_attachments=False
        )
    assert exc_info.value.category == "malformed_payload"


# ==============================================================================
# 3. Structured Content & Multimodal Payload Inspection
# ==============================================================================
def test_structured_text_payload_passes_when_clean():
    """Verify structured list of parts containing clean text is accepted."""
    structured_payload = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is the capital of France?"}
            ]
        }
    ]
    result = OutboundPrivacyGate.inspect_payload(
        messages=structured_payload,
        is_private=False,
        has_attachments=False
    )
    assert result.is_safe is True


def test_structured_text_payload_blocks_credentials():
    """Verify structured text parts are scanned and blocked for credentials."""
    structured_payload = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "My card pin is 987654."}
            ]
        }
    ]
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=structured_payload,
            is_private=False,
            has_attachments=False
        )
    assert "pin" in exc_info.value.category


def test_multimodal_image_url_fails_closed():
    """Verify image_url multimodal content fails closed."""
    multimodal_payload = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image:"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}}
            ]
        }
    ]
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=multimodal_payload,
            is_private=False,
            has_attachments=False
        )
    assert exc_info.value.category == "multimodal_payload_prohibited"


def test_multimodal_audio_fails_closed():
    """Verify input_audio multimodal content fails closed."""
    audio_payload = [
        {
            "role": "user",
            "content": [
                {"type": "input_audio", "data": "base64audio..."}
            ]
        }
    ]
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=audio_payload,
            is_private=False,
            has_attachments=False
        )
    assert exc_info.value.category == "multimodal_payload_prohibited"


def test_unsupported_content_types_fail_closed():
    """Verify arbitrary non-string, non-list content types (int, bytes, dict) fail closed."""
    for bad_content in [12345, b"binary bytes", {"raw": "dict"}, None]:
        payload = [{"role": "user", "content": bad_content}]
        with pytest.raises(OutboundPrivacyViolation) as exc_info:
            OutboundPrivacyGate.verify_outbound_payload(
                messages=payload,
                is_private=False,
                has_attachments=False
            )
        assert exc_info.value.category == "unsupported_content_type"


# ==============================================================================
# 4. Tool Message Role Inspection
# ==============================================================================
def test_tool_message_inspected_and_blocks_credentials():
    """Verify role 'tool' is inspected and blocked if it contains sensitive data."""
    tool_payload = [
        {"role": "user", "content": "Run query"},
        {"role": "tool", "content": "Database result: user password is superSecretPassword123"}
    ]
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=tool_payload,
            is_private=False,
            has_attachments=False
        )
    assert "password" in exc_info.value.category or "credential" in exc_info.value.category


# ==============================================================================
# 5. Direct ApiAdapter Invocation Boundaries
# ==============================================================================
@pytest.mark.asyncio
async def test_direct_adapter_stream_chat_fails_on_missing_metadata():
    """Verify direct stream_chat call fails closed without explicit privacy booleans."""
    adapter = ApiAdapter(provider="openai_compatible", model="test-model", api_key="valid-key")
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        async for _ in adapter.stream_chat(
            messages=[{"role": "user", "content": "Hello"}]
            # Note: is_private and has_attachments omitted
        ):
            pass
    assert exc_info.value.category == "invalid_privacy_metadata"


@pytest.mark.asyncio
async def test_direct_adapter_chat_fails_on_missing_metadata():
    """Verify direct chat call fails closed without explicit privacy booleans."""
    adapter = ApiAdapter(provider="openai_compatible", model="test-model", api_key="valid-key")
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        await adapter.chat(
            messages=[{"role": "user", "content": "Hello"}]
            # Note: is_private and has_attachments omitted
        )
    assert exc_info.value.category == "invalid_privacy_metadata"


# ==============================================================================
# 6. Local API Authorization & Endpoint Protection (HTTP 401 Enforcement)
# ==============================================================================
def test_unauthorized_destructive_endpoints_return_401():
    """Verify destructive endpoints return 401 when called without session token."""
    unauth_headers = {"X-Hinaku-Token": ""}

    # Wipe all
    res_wipe = client.post("/api/settings/wipe-all", json={"confirm": "WIPE_ALL"}, headers=unauth_headers)
    assert res_wipe.status_code == 401
    assert "Unauthorized" in res_wipe.json().get("detail", "")

    # Clear memory via settings
    res_clear_settings = client.post("/api/settings/clear-memory", headers=unauth_headers)
    assert res_clear_settings.status_code == 401

    # Clear memory via memories router
    res_clear_mem = client.post("/api/memories/clear", headers=unauth_headers)
    assert res_clear_mem.status_code == 401

    # Delete conversation
    res_del_conv = client.delete("/api/conversations/non-existent-id", headers=unauth_headers)
    assert res_del_conv.status_code == 401

    # Delete memory
    res_del_mem = client.delete("/api/memories/non-existent-id", headers=unauth_headers)
    assert res_del_mem.status_code == 401

    # Delete attachment
    res_del_att = client.delete("/api/conversations/c1/attachments/a1", headers=unauth_headers)
    assert res_del_att.status_code == 401


def test_unauthorized_export_endpoints_return_401():
    """Verify database export endpoint returns 401 when called without valid token."""
    res_no_token = client.get("/api/settings/export", headers={"X-Hinaku-Token": ""})
    assert res_no_token.status_code == 401

    res_bad_bearer = client.get("/api/settings/export", headers={"Authorization": "Bearer fake_token_value", "X-Hinaku-Token": ""})
    assert res_bad_bearer.status_code == 401


def test_unauthorized_memory_endpoints_return_401():
    """Verify memory retrieval and reindex endpoints return 401 when called without valid token."""
    res_list = client.get("/api/memories", headers={"X-Hinaku-Token": ""})
    assert res_list.status_code == 401

    res_reindex = client.post("/api/memories/reindex", headers={"X-Hinaku-Token": ""})
    assert res_reindex.status_code == 401


def test_unauthorized_training_endpoints_return_401():
    """Verify promotion and rollback endpoints return 401 without valid token."""
    unauth_headers = {"X-Hinaku-Token": ""}

    res_promote = client.post(
        "/api/training/promote",
        json={"version": "v1", "candidate_score": 0.9, "current_local_score": 0.8, "confirmed": True},
        headers=unauth_headers
    )
    assert res_promote.status_code == 401

    res_rollback = client.post(
        "/api/training/rollback",
        json={"target_version": "v0"},
        headers=unauth_headers
    )
    assert res_rollback.status_code == 401

    res_exclude = client.post(
        "/api/training/curate/exclude",
        json={"interaction_id": "i1"},
        headers=unauth_headers
    )
    assert res_exclude.status_code == 401


def test_valid_desktop_session_requests_succeed():
    """Verify requests with active session token succeed with HTTP 200."""
    token = get_active_session_token()
    valid_headers = {"X-Hinaku-Token": token}

    # Memory list succeeds
    res_mem = client.get("/api/memories", headers=valid_headers)
    assert res_mem.status_code == 200

    # Settings export succeeds
    res_exp = client.get("/api/settings/export", headers=valid_headers)
    assert res_exp.status_code == 200

    # Authorization via Bearer header also succeeds
    bearer_headers = {"Authorization": f"Bearer {token}"}
    res_bearer = client.get("/api/memories", headers=bearer_headers)
    assert res_bearer.status_code == 200


def test_expired_or_invalid_tokens_return_401():
    """Verify expired or tampered session tokens return HTTP 401."""
    # Completely invalid token
    res_invalid = client.get("/api/memories", headers={"X-Hinaku-Token": "tampered_session_token_xyz"})
    assert res_invalid.status_code == 401

    # Short-lived manager to test expiration
    test_manager = SessionTokenManager(token_ttl_seconds=0.05)
    test_token = test_manager.get_token()
    assert test_manager.validate_token(test_token) is True

    # Sleep to expire
    time.sleep(0.06)
    assert test_manager.is_expired() is True
    assert test_manager.validate_token(test_token) is False
