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


def test_improved_grader_strips_markdown_and_accepts_number_words():
    from scripts.benchmark_thinking import strip_markdown, TEST_PROMPTS

    # 1. strip_markdown checks
    raw_md = "**Nine** sheep are left. `code` and $$math$$ $x=7$."
    cleaned = strip_markdown(raw_md)
    assert "**" not in cleaned
    assert "`" not in cleaned
    assert "$$" not in cleaned

    # 2. Q1 accepts "Nine." and "Nine sheep are left."
    check_q1 = TEST_PROMPTS[0]["check"]
    assert check_q1("Nine.") is True
    assert check_q1("Nine sheep are left.") is True
    assert check_q1("9 sheep are left.") is True
    assert check_q1("8 sheep are left.") is False

    # 3. Q3 accepts real explanation concluding in "she has 1 sister" despite "2 sisters" in context
    check_q3 = TEST_PROMPTS[2]["check"]
    good_q3_reply = "Since each brother has 2 sisters, there are exactly 2 girls in the family. Sally is one of them, so she has 1 sister."
    assert check_q3(good_q3_reply) is True
    assert check_q3("Sally has 0 sisters.") is False

    # 4. Q5 accepts $0.05 even when breakdown mentions $1.10 and $1.00
    check_q5 = TEST_PROMPTS[4]["check"]
    good_q5_reply = "The ball costs **$0.05**. Here is the breakdown: - Let the ball's price be $x. - The bat costs $x + 1.00. - Total: $x"
    assert check_q5(good_q5_reply) is True
    assert check_q5("The ball costs $0.10.") is False
