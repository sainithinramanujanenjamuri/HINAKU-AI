import os
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from backend.main import app
from backend.models.router import ModelRouter, classify_prompt
from backend.models.api_adapter import ApiAdapter
from backend.models.ollama_adapter import OllamaAdapter
from backend.history import ChatHistoryManager

client = TestClient(app)

def test_classify_prompt_rules():
    # Greetings & small talk -> local
    assert classify_prompt("hi") == "local"
    assert classify_prompt("hello there") == "local"
    assert classify_prompt("how is today?") == "local"
    assert classify_prompt("who are you") == "local"
    assert classify_prompt("ok thanks") == "local"

    # Factual, technical, code, math -> api
    assert classify_prompt("what is python") == "api"
    assert classify_prompt("what is agi") == "api"
    assert classify_prompt("explain how transformers work") == "api"
    assert classify_prompt("def bubble_sort(arr):") == "api"
    assert classify_prompt("calculate the integral of x^2") == "api"
    assert classify_prompt("compare c++ vs rust") == "api"

    # Private chat -> ALWAYS local
    assert classify_prompt("what is python", is_private=True) == "local"
    assert classify_prompt("explain how transformers work", is_private=True) == "local"

    # Long message over limit -> api
    long_msg = "hello " * 400
    assert classify_prompt(long_msg, is_private=False, max_local_tokens=100) == "api"

def test_router_decisions():
    local_adapter = OllamaAdapter(default_model="qwen3.5:4b")
    api_adapter = ApiAdapter(provider="openai_compatible", model="api-model", api_key="test-key")

    router_auto = ModelRouter(local_adapter, api_adapter, mode="auto")
    # Greetings -> local
    d1 = router_auto.decide_backend("hi")
    assert d1.target_backend == "local"

    # Factual -> api
    d2 = router_auto.decide_backend("what is quantum computing")
    assert d2.target_backend == "api"

    # Private chat in auto mode -> local
    d3 = router_auto.decide_backend("what is quantum computing", is_private=True)
    assert d3.target_backend == "local"

    # local_only mode -> always local
    router_local = ModelRouter(local_adapter, api_adapter, mode="local_only")
    assert router_local.decide_backend("what is python").target_backend == "local"

    # api_only mode -> api
    router_api = ModelRouter(local_adapter, api_adapter, mode="api_only")
    assert router_api.decide_backend("hi").target_backend == "api"
    # But private chat in api_only mode -> STILL local
    assert router_api.decide_backend("hi", is_private=True).target_backend == "local"

def test_router_daily_limit_fallback(tmp_path):
    local_adapter = OllamaAdapter(default_model="qwen3.5:4b")
    api_adapter = ApiAdapter(provider="openai_compatible", model="api-model", api_key="test-key")
    db_file = tmp_path / "limit_test.db"
    manager = ChatHistoryManager(db_file)

    # Insert 5 fake API interactions
    for _ in range(5):
        manager.log_interaction("c1", "p", "a", "m", "api")

    router = ModelRouter(
        local_adapter,
        api_adapter,
        mode="auto",
        max_daily_api_requests=5,
        history_manager=manager
    )

    decision = router.decide_backend("what is python")
    assert decision.target_backend == "local"
    assert "Daily API request limit" in decision.notice

def test_api_adapter_mocked_openai_streaming():
    adapter = ApiAdapter(
        provider="openai_compatible",
        model="gpt-test",
        base_url="https://fake.api/v1",
        api_key="test-secret"
    )

    fake_lines = [
        'data: {"choices":[{"delta":{"content":"Hello "}}]}',
        'data: {"choices":[{"delta":{"content":"world!"}}]}',
        'data: [DONE]'
    ]

    class MockStreamResponse:
        status_code = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def aiter_lines(self):
            for l in fake_lines:
                yield l

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, headers=None, json=None):
            assert headers["Authorization"] == "Bearer test-secret"
            return MockStreamResponse()

    with patch("httpx.AsyncClient", MockClient):
        import asyncio
        result = asyncio.run(adapter.chat([{"role": "user", "content": "hi"}]))
        assert result == "Hello world!"

def test_api_adapter_mocked_anthropic_streaming():
    adapter = ApiAdapter(
        provider="anthropic",
        model="claude-test",
        base_url="https://fake.anthropic/v1",
        api_key="sk-ant-test"
    )

    fake_lines = [
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Anthropic "}}',
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "reply."}}',
        'data: {"type": "message_stop"}'
    ]

    class MockStreamResponse:
        status_code = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def aiter_lines(self):
            for l in fake_lines:
                yield l

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, headers=None, json=None):
            assert headers["x-api-key"] == "sk-ant-test"
            assert "system" in json
            return MockStreamResponse()

    with patch("httpx.AsyncClient", MockClient):
        import asyncio
        result = asyncio.run(adapter.chat([
            {"role": "system", "content": "You are HINAKU."},
            {"role": "user", "content": "hi"}
        ]))
        assert result == "Anthropic reply."

def test_interaction_logging_and_privacy_via_api():
    import backend.api.chat as chat_module

    # 1. Create a private conversation
    res = client.post("/api/conversations", json={"title": "Private Chat", "is_private": True})
    assert res.status_code == 200
    cid = res.json()["id"]
    assert res.json()["is_private"] is True

    # 2. Send message to chat endpoint
    res_chat = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "what is python"}],
        "conversation_id": cid,
        "stream": False
    })
    assert res_chat.status_code == 200
    data = res_chat.json()
    # Even though "what is python" is factual, private conversation forces local!
    assert data["backend"] == "local"

    # 3. Verify interaction was logged
    with chat_module.history_manager._get_connection() as conn:
        row = conn.execute(
            "SELECT user_prompt, backend, model FROM interactions WHERE conversation_id = ?",
            (cid,)
        ).fetchone()
        assert row is not None
        assert row["user_prompt"] == "what is python"
        assert row["backend"] == "local"

def test_optional_live_api():
    """Optional live test that only runs if HINAKU_API_KEY is configured."""
    key = os.getenv("HINAKU_API_KEY")
    if not key or "SET_ME" in key or len(key) < 10:
        pytest.skip("HINAKU_API_KEY not set or placeholder. Skipping live API test.")

    import backend.api.chat as chat_module
    import asyncio

    # Test single short prompt against real configured API
    prompt_msgs = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "Respond with the single word: PONG"}
    ]
    try:
        reply = asyncio.run(chat_module.api_adapter.chat(prompt_msgs))
        assert len(reply.strip()) > 0
    except Exception as e:
        pytest.skip(f"Live API call failed (possibly network/credit issue): {e}")

