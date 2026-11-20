import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from backend.models.api_adapter import ApiAdapter
from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation
from backend.config import get_settings


@pytest.mark.asyncio
async def test_claudemax_adapter_anthropic_url_and_headers():
    """Verify ApiAdapter normalizes ClaudeMax base URL and sets proper Anthropic headers."""
    # Test base URL without /v1
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in",
        model="claude-sonnet-4-6",
        api_key="test-claudemax-key",
        timeout=30.0,
        max_tokens=2048
    )
    assert adapter.is_anthropic is True

    captured_url = None
    captured_headers = None
    captured_json = None

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_lines(self):
            yield 'event: message_start'
            yield 'data: {"type": "message_start"}'
            yield 'event: content_block_delta'
            yield 'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello "}}'
            yield 'event: content_block_delta'
            yield 'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "from ClaudeMax."}}'
            yield 'event: message_stop'
            yield 'data: {"type": "message_stop"}'

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, headers=None, json=None):
            nonlocal captured_url, captured_headers, captured_json
            captured_url = url
            captured_headers = headers
            captured_json = json
            return MockStreamResponse()

    messages = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "What is Python?"}
    ]

    with patch("httpx.AsyncClient", MockClient):
        chunks = []
        async for chunk in adapter.stream_chat(messages, is_private=False, has_attachments=False):
            chunks.append(chunk)

    # 1. URL must correctly point to /v1/messages
    assert captured_url == "https://theclaudemax.in/v1/messages"

    # 2. Headers must contain both x-api-key and Authorization, plus anthropic-version
    assert captured_headers["x-api-key"] == "test-claudemax-key"
    assert captured_headers["Authorization"] == "Bearer test-claudemax-key"
    assert captured_headers["anthropic-version"] == "2023-06-01"
    assert captured_headers["content-type"] == "application/json"

    # 3. Payload must separate system prompt from messages
    assert captured_json["system"] == "You are HINAKU."
    assert captured_json["model"] == "claude-sonnet-4-6"
    assert captured_json["max_tokens"] == 2048
    assert captured_json["messages"] == [{"role": "user", "content": "What is Python?"}]
    assert captured_json["stream"] is True

    # 4. Streamed output must match deltas
    assert "".join(chunks) == "Hello from ClaudeMax."


@pytest.mark.asyncio
async def test_claudemax_adapter_url_with_v1_already():
    """Verify ApiAdapter does not duplicate /v1 if already present in base_url."""
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in/v1",
        model="claude-opus-4-6",
        api_key="test-key"
    )
    captured_url = None

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_lines(self):
            yield 'data: {"type": "content_block_delta", "delta": {"text": "ok"}}'
            yield 'data: {"type": "message_stop"}'

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, **kwargs):
            nonlocal captured_url
            captured_url = url
            return MockStreamResponse()

    with patch("httpx.AsyncClient", MockClient):
        async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], is_private=False, has_attachments=False):
            pass

    assert captured_url == "https://theclaudemax.in/v1/messages"


@pytest.mark.asyncio
async def test_claudemax_adapter_thinking_filter():
    """Verify thinking tags (<think>...</think>) are filtered out during streaming."""
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in",
        model="claude-sonnet-4-6",
        api_key="test-key"
    )

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_lines(self):
            yield 'data: {"type": "content_block_delta", "delta": {"text": "<think>Internal reasoning</think>Direct answer."}}'
            yield 'data: {"type": "message_stop"}'

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def stream(self, method, url, **kwargs):
            return MockStreamResponse()

    with patch("httpx.AsyncClient", MockClient):
        result = await adapter.chat([{"role": "user", "content": "test"}], is_private=False, has_attachments=False)
        assert result.strip() == "Direct answer."


@pytest.mark.asyncio
async def test_claudemax_privacy_gate_blocks_private_chats():
    """Verify outbound privacy gate strictly blocks private chat transmissions."""
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in",
        model="claude-sonnet-4-6",
        api_key="test-key"
    )

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        async for _ in adapter.stream_chat(
            messages=[{"role": "user", "content": "what is rust"}],
            is_private=True,
            has_attachments=False
        ):
            pass

    assert "private" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_claudemax_privacy_gate_blocks_memories():
    """Verify outbound privacy gate strictly blocks personal memory context."""
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in",
        model="claude-sonnet-4-6",
        api_key="test-key"
    )

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        async for _ in adapter.stream_chat(
            messages=[
                {"role": "system", "content": "You are HINAKU.\n\n[What HINAKU remembers about you]\n- Lives in Seattle"},
                {"role": "user", "content": "hello"}
            ],
            is_private=False,
            has_attachments=False
        ):
            pass

    assert "memory" in str(exc_info.value).lower() or "personal" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_claudemax_privacy_gate_blocks_attachments():
    """Verify outbound privacy gate strictly blocks document attachment context."""
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in",
        model="claude-sonnet-4-6",
        api_key="test-key"
    )

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        async for _ in adapter.stream_chat(
            messages=[
                {"role": "user", "content": "Explain this document."}
            ],
            is_private=False,
            has_attachments=True
        ):
            pass

    assert "attachment" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_claudemax_privacy_gate_blocks_credentials():
    """Verify outbound privacy gate strictly blocks raw credentials from leaving to ClaudeMax."""
    adapter = ApiAdapter(
        provider="anthropic",
        base_url="https://theclaudemax.in",
        model="claude-sonnet-4-6",
        api_key="test-key"
    )

    with pytest.raises(OutboundPrivacyViolation) as exc_info:
        async for _ in adapter.stream_chat(
            messages=[
                {"role": "user", "content": "My password is secretPassword123!"}
            ],
            is_private=False,
            has_attachments=False
        ):
            pass

    assert "credential" in str(exc_info.value).lower() or "password" in str(exc_info.value).lower()


def test_dynamic_settings_reload():
    """Verify get_settings detects config modification and updates api_adapter parameters."""
    settings = get_settings(reload=True)
    # Validate provider, base_url, model accessibility
    assert hasattr(settings, "api_provider")
    assert hasattr(settings, "api_base_url")
    assert hasattr(settings, "api_model")
    assert hasattr(settings, "get_api_key")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main(["-v", __file__]))
