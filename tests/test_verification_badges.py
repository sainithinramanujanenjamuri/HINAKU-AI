import pytest
from unittest.mock import AsyncMock
from backend.quality import verify_reply, count_sentences, trim_to_four_sentences

REAL_7_SENTENCE_REPLY = (
    "That's a lot to carry. Coding is demanding work.\n\n"
    "Rest. You've done something productive. Now prioritize stillness. "
    "Try a short body scan - notice where you feel tension, and consciously relax those areas.\n\n"
    "Do you want to talk about the coding session, or would you prefer I suggest a different approach to calming your mind?"
)

REAL_2_SENTENCE_REPLY = "Rest is necessary. Take a break."

@pytest.mark.asyncio
async def test_seven_sentence_reply_rewritten_outside_detail_mode():
    """Outside detail mode, a 7-sentence reply must be rewritten/trimmed to 4 sentences or fewer."""
    mock_adapter = AsyncMock()
    # Verifier hallucinating "OK" for a 7-sentence draft
    async def mock_stream(*args, **kwargs):
        yield "OK"

    mock_adapter.stream_chat = mock_stream

    final_reply, was_verified, elapsed_ms, status, reason = await verify_reply(
        draft=REAL_7_SENTENCE_REPLY,
        persona_rules="Default to four sentences or fewer.",
        clock_ctx="Saturday, 2026-10-24 1:30 PM",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m",
        is_detail=False
    )

    assert count_sentences(final_reply) <= 4
    assert status == "corrected"
    assert "Exceeded 4 sentences" in reason
    assert final_reply != REAL_7_SENTENCE_REPLY

@pytest.mark.asyncio
async def test_clean_short_reply_passes_as_verified():
    """A 2-sentence compliant reply gets verified with no changes."""
    mock_adapter = AsyncMock()
    async def mock_stream(*args, **kwargs):
        yield "OK"

    mock_adapter.stream_chat = mock_stream

    final_reply, was_verified, elapsed_ms, status, reason = await verify_reply(
        draft=REAL_2_SENTENCE_REPLY,
        persona_rules="Default to four sentences or fewer.",
        clock_ctx="Saturday, 2026-10-24 1:30 PM",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m",
        is_detail=False
    )

    assert final_reply == REAL_2_SENTENCE_REPLY
    assert was_verified is True
    assert status == "verified"
    assert reason is None

@pytest.mark.asyncio
async def test_verifier_error_returns_not_verified_with_reason():
    """If verifier raises an exception, return not_verified with the error reason."""
    mock_adapter = AsyncMock()
    async def mock_stream(*args, **kwargs):
        raise RuntimeError("Ollama connection timed out")
        yield "ignored"

    mock_adapter.stream_chat = mock_stream

    final_reply, was_verified, elapsed_ms, status, reason = await verify_reply(
        draft=REAL_2_SENTENCE_REPLY,
        persona_rules="Default to four sentences or fewer.",
        clock_ctx="Saturday, 2026-10-24 1:30 PM",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m",
        is_detail=False
    )

    assert final_reply == REAL_2_SENTENCE_REPLY
    assert was_verified is False
    assert status == "not_verified"
    assert "error" in reason
