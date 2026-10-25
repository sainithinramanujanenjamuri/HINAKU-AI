import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from backend.quality import (
    verify_reply,
    count_sentences,
    trim_to_four_sentences,
    detect_forbidden_offers,
    fix_clock_error_in_code,
    detect_hardware_conflict,
    strip_persona_examples,
    is_llm_verifier_output_valid
)

REAL_7_SENTENCE_REPLY = (
    "That's a lot to carry. Coding is demanding work.\n\n"
    "Rest. You've done something productive. Now prioritize stillness. "
    "Try a short body scan - notice where you feel tension, and consciously relax those areas.\n\n"
    "Do you want to talk about the coding session, or would you prefer I suggest a different approach to calming your mind?"
)

REAL_2_SENTENCE_REPLY = "Rest is necessary. Take a break."

REAL_VECTOR_MEMORY_DRAFT = (
    "Vector memory is a technique used in retrieval systems to accelerate similarity searches. "
    "It allows the database to precompute and store distances between pairs of vectors, significantly speeding up queries. "
    "Data is represented as numerical vectors that capture semantic features in mathematical space. "
    "When a similarity query runs, the database calculates distances and returns the closest items."
)


@pytest.mark.asyncio
async def test_seven_sentence_reply_rewritten_outside_detail_mode():
    """Outside detail mode, a 7-sentence reply must be trimmed to 4 sentences or fewer."""
    mock_adapter = AsyncMock()
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
    assert "Trimmed to four sentences" in reason
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


# --- User-specified Real Failure Tests ---

def test_real_failure_canberra_turned_into_question_rejected():
    """
    Real failure: "Canberra." becoming "What location are you asking about?".
    Must be rejected because it turns a statement into a question.
    """
    draft = "Canberra."
    hallucinated_verifier_out = "What location are you asking about?"
    is_valid, reject_reason = is_llm_verifier_output_valid(draft, hallucinated_verifier_out)

    assert is_valid is False
    assert "turned statement into a question" in reject_reason


@pytest.mark.asyncio
async def test_verify_reply_rejects_canberra_to_question_and_keeps_draft():
    """When verifier turns 'Canberra.' into a question, verify_reply must reject it and keep 'Canberra.'."""
    mock_adapter = AsyncMock()
    async def mock_stream(*args, **kwargs):
        yield "What location are you asking about?"

    mock_adapter.stream_chat = mock_stream

    final_reply, was_verified, elapsed_ms, status, reason = await verify_reply(
        draft="Canberra.",
        persona_rules="Default to four sentences or fewer.",
        clock_ctx="Saturday, 2026-10-24 1:30 PM",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m",
        is_detail=False
    )

    assert final_reply == "Canberra."
    assert was_verified is False
    assert status == "not_verified"
    assert "question" in reason


def test_real_failure_vector_memory_reviewer_words_rejected():
    """
    Real failure: Vector-memory reply becoming a reviewer comment
    'The response accurately describes vector memory and its function. It includes a helpful breakdown of the process.'
    Must be rejected because it contains reviewer words ('the response', 'accurately') and is < 60% of draft.
    """
    reviewer_output = "The response accurately describes vector memory and its function. It includes a helpful breakdown of the process."
    is_valid, reject_reason = is_llm_verifier_output_valid(REAL_VECTOR_MEMORY_DRAFT, reviewer_output)

    assert is_valid is False
    assert "reviewer commentary" in reject_reason or "shorter than 60%" in reject_reason


@pytest.mark.asyncio
async def test_verify_reply_rejects_reviewer_comment_and_keeps_vector_draft():
    """When verifier outputs reviewer commentary, verify_reply must reject it and keep draft."""
    mock_adapter = AsyncMock()
    async def mock_stream(*args, **kwargs):
        yield "The response accurately describes vector memory and its function. It includes a helpful breakdown of the process."

    mock_adapter.stream_chat = mock_stream

    final_reply, was_verified, elapsed_ms, status, reason = await verify_reply(
        draft=REAL_VECTOR_MEMORY_DRAFT,
        persona_rules="Default to four sentences or fewer.",
        clock_ctx="Saturday, 2026-10-24 1:30 PM",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m",
        is_detail=True
    )

    assert final_reply == REAL_VECTOR_MEMORY_DRAFT
    assert was_verified is False
    assert status == "not_verified"
    assert "reviewer" in reason or "shorter" in reason


def test_real_failure_four_sentences_becoming_persona_example_rejected():
    """
    Real failure: "Four sentences or fewer." becoming "I'm here. What are we working on?".
    Must be rejected because it contains a persona example verbatim.
    """
    draft = "Four sentences or fewer."
    persona_example_output = "I'm here. What are we working on?"
    is_valid, reject_reason = is_llm_verifier_output_valid(draft, persona_example_output)

    assert is_valid is False
    assert "persona example" in reject_reason


@pytest.mark.asyncio
async def test_verify_reply_rejects_persona_example_and_keeps_draft():
    """When verifier outputs a persona example, verify_reply must reject it and keep draft."""
    mock_adapter = AsyncMock()
    async def mock_stream(*args, **kwargs):
        yield "I'm here. What are we working on?"

    mock_adapter.stream_chat = mock_stream

    final_reply, was_verified, elapsed_ms, status, reason = await verify_reply(
        draft="Four sentences or fewer.",
        persona_rules="Default to four sentences or fewer.",
        clock_ctx="Saturday, 2026-10-24 1:30 PM",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m",
        is_detail=False
    )

    assert final_reply == "Four sentences or fewer."
    assert was_verified is False
    assert status == "not_verified"
    assert "persona example" in reason


def test_strip_persona_examples_removes_style_reference_section():
    """Never show persona example lines to any verifier or checker prompt."""
    raw_persona = (
        "You are HINAKU.\n"
        "Rules:\n"
        "- Default to four sentences or fewer.\n\n"
        "Style reference:\n"
        "- Greeting:\n"
        "  Owner: hello\n"
        "  HINAKU: I'm here. What are we working on?\n"
    )
    stripped = strip_persona_examples(raw_persona)
    assert "Default to four sentences or fewer." in stripped
    assert "Style reference:" not in stripped
    assert "I'm here. What are we working on?" not in stripped


def test_deterministic_clock_weekday_fixed_by_code():
    """Clock errors (wrong weekday) are fixed directly by code without calling an LLM."""
    mock_sat = datetime(2026, 10, 24, 15, 0)  # Saturday
    draft_wrong_weekday = "It is a typical Tuesday with clear skies."
    fixed, did_fix, reason = fix_clock_error_in_code(draft_wrong_weekday, clock_dt=mock_sat)

    assert did_fix is True
    assert fixed == "It is a typical Saturday with clear skies."
    assert "Tuesday" not in fixed
    assert "Saturday" in fixed
    assert "Fixed weekday 'Tuesday' to 'Saturday'" in reason


def test_weekday_fixer_only_corrects_today_statements_and_leaves_other_days_unchanged():
    """
    Only correct statements that say what TODAY is ("Today is X", "It's X today", "X today").
    Never change weekday words that refer to other days (tomorrow, next Monday, "on Monday").
    Real draft: "If the work isn't done, you risk falling behind on Monday" (today is Sunday; must stay unchanged).
    """
    mock_sun = datetime(2026, 10, 25, 10, 0)  # Sunday

    # 1. Real draft: referring to future day ("on Monday") -> must stay unchanged
    real_draft = "If the work isn't done, you risk falling behind on Monday"
    fixed, did_fix, reason = fix_clock_error_in_code(real_draft, clock_dt=mock_sun)
    assert did_fix is False
    assert fixed == real_draft
    assert reason is None

    # check_reply must also not flag "on Monday" as a wrong weekday when clock is Sunday
    from scripts.model_bakeoff import check_reply
    res = check_reply("What should I keep in mind for my sprint?", real_draft, clock_dt=mock_sun)
    assert not any("wrong weekday" in r.lower() for r in res.get("reasons", []))

    # 2. Other-day references ("next Monday", "tomorrow is Monday", "by Monday") must stay unchanged
    for other_day_phrase in [
        "Let's review this next Monday.",
        "Tomorrow is Monday, so be prepared.",
        "Make sure to submit it by Monday."
    ]:
        f, changed, _ = fix_clock_error_in_code(other_day_phrase, clock_dt=mock_sun)
        assert changed is False
        assert f == other_day_phrase

    # 3. Statements asserting what TODAY is must be corrected
    # "Today is X"
    f1, ch1, r1 = fix_clock_error_in_code("Today is Tuesday. Focus on the core bug.", clock_dt=mock_sun)
    assert ch1 is True
    assert f1 == "Today is Sunday. Focus on the core bug."
    assert "Fixed weekday 'Tuesday' to 'Sunday'" in r1

    # "It's X today"
    f2, ch2, r2 = fix_clock_error_in_code("It's Tuesday today. Keep moving forward.", clock_dt=mock_sun)
    assert ch2 is True
    assert f2 == "It's Sunday today. Keep moving forward."

    # "X today"
    f3, ch3, r3 = fix_clock_error_in_code("Tuesday today. Clear the backlog.", clock_dt=mock_sun)
    assert ch3 is True
    assert f3 == "Sunday today. Clear the backlog."

    # Combined: asserts today is Tuesday AND mentions on Monday
    combined_draft = "Today is Tuesday. If the work isn't done, you risk falling behind on Monday."
    f4, ch4, r4 = fix_clock_error_in_code(combined_draft, clock_dt=mock_sun)
    assert ch4 is True
    assert f4 == "Today is Sunday. If the work isn't done, you risk falling behind on Monday."
    assert "Tuesday" not in f4
    assert "on Monday" in f4


def test_deterministic_forbidden_offers_detected():
    """Detect forbidden capability offers (music, reminders, alarms, timers, calendar, sending messages, opening apps, tracking)."""
    assert detect_forbidden_offers("I can play some ambient music if you wish.") is not None
    assert detect_forbidden_offers("Let me set a timer for 15 minutes.") is not None
    assert detect_forbidden_offers("I can set an alarm for 7 AM tomorrow.") is not None
    assert detect_forbidden_offers("Do you want me to set a reminder for a short break?") is not None
    assert detect_forbidden_offers("I will schedule a calendar event for our meeting.") is not None
    assert detect_forbidden_offers("Let me send a message to your team on Slack.") is not None
    assert detect_forbidden_offers("I will open VS Code for you now.") is not None
    assert detect_forbidden_offers("I will keep watching your system temperature.") is not None

    # Valid chat-only statement passes
    assert detect_forbidden_offers("Take a 15-minute break. Walk around and step away from the screen.") is None


def test_deterministic_hardware_conflict_detected():
    """Detect stated VRAM amount or GPU conflicting with owner's stored hardware (RTX 4050, 6 GB)."""
    assert detect_hardware_conflict("Your laptop has an RTX 3090.") is not None
    assert detect_hardware_conflict("Your machine has 16 GB of VRAM.") is not None
    assert detect_hardware_conflict("Your GPU has 8 GB VRAM.") is not None

    # Compliant statements pass
    assert detect_hardware_conflict("Your laptop has an RTX 4050 with 6 GB VRAM.") is None
    assert detect_hardware_conflict("Training a 70B model requires 80 GB GPUs like A100.") is None
