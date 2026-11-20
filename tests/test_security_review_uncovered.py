import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation
from backend.models.api_adapter import ApiAdapter
from backend.models.router import ModelRouter, is_personal_statement
from backend.guards import is_sensitive_topic


client = TestClient(app)


# ==============================================================================
# 1. Malformed Payloads & Unexpected Message Formats (Fail-Closed)
# ==============================================================================
def test_privacy_gate_rejects_none_payload():
    """Verify privacy gate fails closed on None messages."""
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(None, is_private=False, has_attachments=False)
    assert "empty or not a list" in str(exc_info.value).lower()


def test_privacy_gate_rejects_empty_list():
    """Verify privacy gate fails closed on empty list messages."""
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload([], is_private=False, has_attachments=False)
    assert "empty or not a list" in str(exc_info.value).lower()


def test_privacy_gate_rejects_non_dict_elements():
    """Verify privacy gate fails closed on list containing non-dict items."""
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(["not a dict"], is_private=False, has_attachments=False)
    assert "malformed" in str(exc_info.value).lower()

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload([123, None, {}], is_private=False, has_attachments=False)
    assert "malformed" in str(exc_info.value).lower()


def test_privacy_gate_handles_none_role_and_content_safely():
    """Verify privacy gate fails closed on None role or None content."""
    result = OutboundPrivacyGate.inspect_payload([{"role": None, "content": "hi"}], is_private=False, has_attachments=False)
    assert result.is_safe is False
    assert result.category == "unsupported_role"

    result_content = OutboundPrivacyGate.inspect_payload([{"role": "user", "content": None}], is_private=False, has_attachments=False)
    assert result_content.is_safe is False
    assert result_content.category == "unsupported_content_type"


def test_privacy_gate_developer_role_scanned():
    """Verify modern 'developer' role is scanned for injected memories."""
    developer_payload = [
        {"role": "developer", "content": "You are HINAKU.\n[What HINAKU remembers about you]\n- Lives in Seattle"},
        {"role": "user", "content": "hello"}
    ]
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(developer_payload, is_private=False, has_attachments=False)
    assert "injected personal memory" in str(exc_info.value).lower()


# ==============================================================================
# 2. CORS Policy: Origin Validation & External Rejection
# ==============================================================================
def test_cors_rejects_untrusted_external_origin():
    """Verify external origins are not granted Access-Control-Allow-Origin."""
    response = client.options(
        "/api/info",
        headers={
            "Origin": "https://malicious-website.com",
            "Access-Control-Request-Method": "GET"
        }
    )
    # When CORS rejects an origin, FastAPI does not echo Access-Control-Allow-Origin for that origin
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "https://malicious-website.com"
    assert allow_origin != "*"


def test_cors_rejects_subdomain_spoofing():
    """Verify origins like attacker.localhost or localhost.evil.com are rejected."""
    response = client.options(
        "/api/info",
        headers={
            "Origin": "http://localhost.evil.com",
            "Access-Control-Request-Method": "GET"
        }
    )
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "http://localhost.evil.com"


def test_cors_allows_legitimate_local_origins():
    """Verify local loopback and pywebview origins are allowed."""
    for origin in ["http://127.0.0.1:8000", "http://localhost:8000", "pywebview://localhost", "null"]:
        response = client.options(
            "/api/info",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert response.headers.get("access-control-allow-origin") == origin


# ==============================================================================
# 3. English-Only Privacy Detection Boundary Test
# ==============================================================================
def test_english_only_detection_limitation_and_private_override():
    """
    Test-confirms the English-only limitation:
    Non-English statements are not caught by English regex, but ARE blocked when is_private=True.
    """
    spanish_depression = "Me siento profundamente deprimido y triste."
    hindi_trouble = "Main bahut pareshan hoon aur salary kam hai."

    # In English-only regex, non-English statements without English tokens are not flagged
    assert is_personal_statement(spanish_depression) is False
    assert is_sensitive_topic(hindi_trouble)[0] is False

    # BUT when conversation is marked private, OutboundPrivacyGate blocks 100% fail-closed
    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=[{"role": "user", "content": spanish_depression}],
            is_private=True,
            has_attachments=False
        )
    assert "private" in str(exc_info.value).lower()

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        OutboundPrivacyGate.verify_outbound_payload(
            messages=[{"role": "user", "content": hindi_trouble}],
            is_private=True,
            has_attachments=False
        )
    assert "private" in str(exc_info.value).lower()


# ==============================================================================
# 4. Direct ApiAdapter Failure Modes (No bypass possible)
# ==============================================================================
@pytest.mark.asyncio
async def test_api_adapter_fails_on_missing_api_key():
    """Verify ApiAdapter immediately raises ValueError if api_key is None or empty."""
    adapter = ApiAdapter(provider="openai_compatible", model="test-model", api_key="")
    with pytest.raises(ValueError) as exc_info:
        async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], is_private=False, has_attachments=False):
            pass
    assert "API key is missing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_api_adapter_fails_on_unset_model():
    """Verify ApiAdapter immediately raises ValueError if model is unset or SET_ME."""
    adapter = ApiAdapter(provider="openai_compatible", model="", api_key="valid-key")
    with pytest.raises(ValueError) as exc_info:
        async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], is_private=False, has_attachments=False):
            pass
    assert "model name is not configured" in str(exc_info.value)
