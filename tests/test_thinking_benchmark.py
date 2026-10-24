import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from scripts.benchmark_thinking import call_model, TEST_PROMPTS

@pytest.mark.asyncio
async def test_call_model_logs_all_required_metrics():
    """Verify call_model extracts done_reason, eval_count, reasoning_chars, content_chars, retry_fired, total_time."""
    mock_resp_lines = [
        '{"message": {"thinking": "Step 1: 2x = 14. Step 2: x = 7."}, "done": false}',
        '{"message": {"content": "The answer is 17."}, "done": true, "done_reason": "stop", "eval_count": 42}'
    ]

    async def mock_aiter_lines():
        for line in mock_resp_lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.aiter_lines = mock_aiter_lines

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream.return_value = mock_stream_ctx

    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await call_model("bonsai-2:9b", "Solve: 2x + 5 = 19", think=True)

    assert res["model"] == "bonsai-2:9b"
    assert res["think"] is True
    assert res["done_reason"] == "stop"
    assert res["eval_count"] == 42
    assert res["reasoning_chars"] > 0
    assert res["content_chars"] > 0
    assert res["retry_fired"] is False
    assert res["total_time"] >= 0
    assert "17" in res["reply"]

@pytest.mark.asyncio
async def test_call_model_retries_when_thinking_exhausts_tokens_with_no_content():
    """When think is True and length exhausted with no content, it retries with think: False."""
    call_count = 0

    def mock_stream(method, url, json):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if json.get("think") is True:
            # First call: exhausted in thinking
            lines = [
                '{"message": {"thinking": "Thinking intensely..."}, "done": false}',
                '{"message": {"content": ""}, "done": true, "done_reason": "length", "eval_count": 3000}'
            ]
        else:
            # Second call: retry with think=False produces content
            lines = [
                '{"message": {"content": "Retried direct answer without deep thinking."}, "done": true, "done_reason": "stop", "eval_count": 25}'
            ]

        async def aiter():
            for l in lines:
                yield l

        resp.aiter_lines = aiter
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.stream = mock_stream

    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await call_model("bonsai-2:9b", "Hard prompt", think=True)

    assert res["retry_fired"] is True
    assert "Retried direct answer" in res["reply"]
    assert call_count == 2
