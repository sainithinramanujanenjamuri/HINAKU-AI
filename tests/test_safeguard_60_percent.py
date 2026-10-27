import pytest
from unittest.mock import MagicMock
from backend.quality import perform_reply_verification

@pytest.mark.asyncio
async def test_safeguard_refuses_shrinkage_below_60_percent_13421_chars():
    # Construct a realistic 13,421-character walkthrough draft
    base_paragraph = (
        "The AI Triad consists of Security, Ethics, and Regulation. "
        "Security protects the confidentiality, integrity, and availability of AI systems. "
        "Ethics ensures fairness, accountability, transparency, and human well-being. "
        "Regulation enforces legal compliance across jurisdictions.\n\n"
    )
    long_draft = (base_paragraph * 55)[:13421]
    assert len(long_draft) == 13421

    mock_persona = MagicMock()
    mock_persona.content = "You are HINAKU."
    mock_persona.is_fallback = False

    mock_adapter = MagicMock()
    async def empty_stream(*args, **kwargs):
        if False:
            yield ""
    mock_adapter.stream_chat = empty_stream

    class SimpleSettings:
        quality_mode = False
        local_keep_alive = "30m"

    # Simulate call outside detail mode: normally would try to trim to 4 sentences
    final_reply, was_verified, verify_ms, verify_status, verify_reason = await perform_reply_verification(
        draft_reply=long_draft,
        used_backend="local",
        used_model="bonsai-2:9b",
        target_opts={"num_ctx": 8192},
        persona_state=mock_persona,
        clock_context="",
        memory_context="",
        is_detail=False,
        local_adapter=mock_adapter,
        settings=SimpleSettings(),
        has_attachments=False  # Even if has_attachments is False, the 60% safeguard must protect it!
    )

    # Must preserve the full length, refusing any shrinkage to 4 sentences!
    assert len(final_reply) == 13421
    assert final_reply == long_draft
    assert "rejected" in (verify_reason or "").lower() or verify_status == "safeguard_kept_draft"


@pytest.mark.asyncio
async def test_safeguard_allows_guard_short_replies():
    # If the backend is guard (e.g. sensitive data refusal), short reply is permitted
    guard_draft = "You uploaded private account numbers. I cannot process this document."
    mock_persona = MagicMock()

    class SimpleSettings:
        quality_mode = False
        local_keep_alive = "30m"

    final_reply, was_verified, verify_ms, verify_status, verify_reason = await perform_reply_verification(
        draft_reply=guard_draft,
        used_backend="guard",
        used_model="guard",
        target_opts={},
        persona_state=mock_persona,
        clock_context="",
        memory_context="",
        is_detail=False,
        local_adapter=None,
        settings=SimpleSettings(),
        has_attachments=True
    )

    assert final_reply == guard_draft
