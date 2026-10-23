import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.models.router import ModelRouter, RouterDecision
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter


@pytest.fixture
def mock_adapters():
    local = MagicMock(spec=OllamaAdapter)
    local.default_model = "gemma3:4b"
    local.last_done_reason = ""
    local.chat = AsyncMock(return_value="Local response")
    
    # Simple async generator helper for streaming
    async def mock_local_stream(messages, model=None, **kwargs):
        yield "Local "
        yield "stream "
        yield "chunk"

    local.stream_chat = mock_local_stream

    api = MagicMock(spec=ApiAdapter)
    api.model = "test-api-model"
    api.api_key = "test-key"
    api.chat = AsyncMock(side_effect=AssertionError("API chat should NEVER be called in local_only mode"))

    async def mock_api_stream(*args, **kwargs):
        raise AssertionError("API stream_chat should NEVER be called in local_only mode")
        yield "API"

    api.stream_chat = mock_api_stream

    return local, api


@pytest.mark.asyncio
async def test_local_only_standard_path_never_calls_api(mock_adapters):
    local, api = mock_adapters
    router = ModelRouter(
        local_adapter=local,
        api_adapter=api,
        mode="local_only",
        fallback_on_failure=True
    )

    decision = router.decide_backend("Explain quantum electrodynamics in depth with mathematical rigor")
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    events = []
    async for event in router.stream_chat(
        [{"role": "user", "content": "Explain quantum electrodynamics"}],
        user_prompt="Explain quantum electrodynamics"
    ):
        events.append(event)

    assert len(events) > 0
    assert all(e["backend"] == "local" for e in events)
    assert api.chat.call_count == 0


@pytest.mark.asyncio
async def test_local_only_error_never_falls_back_to_api(mock_adapters):
    local, api = mock_adapters
    
    async def failing_local_stream(*args, **kwargs):
        raise RuntimeError("Ollama connection failed (simulated crash)")
        yield ""

    local.stream_chat = failing_local_stream

    router = ModelRouter(
        local_adapter=local,
        api_adapter=api,
        mode="local_only",
        fallback_on_failure=True
    )

    events = []
    async for event in router.stream_chat(
        [{"role": "user", "content": "hello"}],
        user_prompt="hello"
    ):
        events.append(event)

    # Must yield a local error message, NOT fallback to API
    assert len(events) == 1
    assert events[0]["backend"] == "local"
    assert "[Error: Local model failed" in events[0]["chunk"]
    assert api.chat.call_count == 0


@pytest.mark.asyncio
async def test_local_only_think_retry_uses_local_and_never_calls_api(mock_adapters):
    local, api = mock_adapters

    call_count = 0

    async def dynamic_local_stream(messages, model=None, **kwargs):
        nonlocal call_count
        call_count += 1
        think = kwargs.get("think", False)
        if think:
            # First attempt: simulated think exhausting length with 0 content
            local.last_done_reason = "length"
            # Generator yields nothing
            return
        else:
            # Second attempt: think=False retry returns answer
            local.last_done_reason = "stop"
            yield "Recovered answer without thinking"

    local.stream_chat = dynamic_local_stream

    router = ModelRouter(
        local_adapter=local,
        api_adapter=api,
        mode="local_only",
        fallback_on_failure=True
    )

    events = []
    async for event in router.stream_chat(
        [{"role": "user", "content": "solve this riddle"}],
        user_prompt="solve this riddle",
        think=True
    ):
        events.append(event)

    assert call_count == 2
    assert len(events) == 1
    assert events[0]["chunk"] == "Recovered answer without thinking"
    assert events[0]["notice"] == "Answered without deep thinking"
    assert events[0]["backend"] == "local"
    assert api.chat.call_count == 0


@pytest.mark.asyncio
async def test_think_retry_never_retries_more_than_once(mock_adapters):
    local, api = mock_adapters
    call_count = 0

    async def always_empty_stream(messages, model=None, **kwargs):
        nonlocal call_count
        call_count += 1
        local.last_done_reason = "length"
        if False:
            yield ""
        return

    local.stream_chat = always_empty_stream

    router = ModelRouter(
        local_adapter=local,
        api_adapter=api,
        mode="local_only",
        fallback_on_failure=True
    )

    events = []
    async for event in router.stream_chat(
        [{"role": "user", "content": "solve this riddle"}],
        user_prompt="solve this riddle",
        think=True
    ):
        events.append(event)

    # Exactly 2 calls: 1 initial (think=True) + 1 retry (think=False), never 3
    assert call_count == 2
    assert api.chat.call_count == 0

