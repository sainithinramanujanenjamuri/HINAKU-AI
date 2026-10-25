import pytest
import re
from backend.guards import is_detail_request, trim_to_last_complete_sentence
from backend.quality import is_malformed_verification, verify_reply


def test_is_detail_request_triggers():
    # Explicit detail phrases
    assert is_detail_request("explain TTFT in more detail") is True
    assert is_detail_request("I need longer explanation") is True
    assert is_detail_request("give me an in-depth answer") is True
    assert is_detail_request("can you elaborate on that?") is True
    assert is_detail_request("explain more about transformers") is True
    assert is_detail_request("walk me through it step by step") is True
    assert is_detail_request("give me a deep dive into vector search") is True

    # Short follow-ups
    assert is_detail_request("more") is True
    assert is_detail_request("go on") is True
    assert is_detail_request("continue") is True
    assert is_detail_request("longer") is True

    # Normal questions must NOT trigger detail mode
    assert is_detail_request("what is TTFT?") is False
    assert is_detail_request("hello") is False
    assert is_detail_request("who are you?") is False
    assert is_detail_request("what day is it") is False
    assert is_detail_request("Which editor should I use?") is False


def test_trim_to_last_complete_sentence():
    # Completely finished text: no cut
    full_text = "This is the first sentence. This is the second sentence."
    trimmed, was_cut = trim_to_last_complete_sentence(full_text)
    assert trimmed == full_text
    assert was_cut is False

    # Ends mid-sentence: must cut cleanly back to second sentence
    cut_text = "This is the first sentence. This is the second sentence. And here is an incomplete thought that got"
    trimmed, was_cut = trim_to_last_complete_sentence(cut_text)
    assert trimmed == "This is the first sentence. This is the second sentence."
    assert was_cut is True

    # Punctuation with quote
    quote_text = 'First sentence. "This is a quoted sentence!" Incomplete end'
    trimmed, was_cut = trim_to_last_complete_sentence(quote_text)
    assert trimmed == 'First sentence. "This is a quoted sentence!"'
    assert was_cut is True


def test_verification_leaves_long_detail_replies_alone():
    # In detail mode, a reply with 8 sentences must not be treated as malformed or violating rule 3
    long_reply = (
        "Memory stores historical context for autonomous systems. "
        "It can be split into short-term working memory and long-term vector storage. "
        "Short-term memory tracks current task goals and active state. "
        "Long-term memory indexes past turns using semantic embeddings. "
        "Learning continuously refines the internal models from user feedback. "
        "Reinforcement signals adjust weights over successive cycles. "
        "Together, these systems enable continuous improvement. "
        "Without both, an assistant remains purely reactive."
    )
    sentences = [p for p in re.split(r"[.!?]+", long_reply) if p.strip()]
    assert len(sentences) == 8
    words = long_reply.split()
    assert 6 <= len(sentences)
    assert len(words) <= 350

    # is_malformed_verification with is_detail=True must NOT reject 8 sentences
    assert is_malformed_verification(long_reply, is_detail=True) is False

    # But in standard mode (is_detail=False), 8 sentences is considered malformed / rule violation (> 4 sentences)
    assert is_malformed_verification(long_reply, is_detail=False) is True


@pytest.mark.asyncio
async def test_verify_reply_with_detail_mode_mock():
    # Test verify_reply with is_detail=True leaves compliant multi-sentence draft alone
    long_compliant_draft = (
        "Memory in autonomous agents acts as persistent context storage. "
        "It retains facts and preferences across interactions. "
        "Learning algorithms adapt internal policies from feedback loops. "
        "Vector databases provide semantic retrieval capabilities. "
        "Short-term context keeps immediate instructions fresh. "
        "Together, they form a cohesive architecture."
    )

    class MockAdapter:
        async def stream_chat(self, *args, **kwargs):
            # Verifier returns OK
            yield "OK"

    final_reply, was_verified, elapsed, status, reason = await verify_reply(
        draft=long_compliant_draft,
        persona_rules="Default to four sentences or fewer unless detail is requested.",
        clock_ctx="Thursday",
        memory_ctx="",
        local_adapter=MockAdapter(),
        model="gemma3:4b",
        options={},
        keep_alive="30m",
        is_detail=True
    )

    assert was_verified is True
    assert final_reply == long_compliant_draft


def test_trim_to_word_cap_enforces_hard_cap_at_sentence_boundary():
    from backend.guards import trim_to_word_cap

    # Generate 50 sentences with 10 words each (500 words total)
    sentences = [f"Sentence number {i} contains exactly ten words to test proper length." for i in range(1, 51)]
    long_text = " ".join(sentences)
    words = re.findall(r"\b\w+\b", long_text)
    assert len(words) == 550

    capped_text, was_capped = trim_to_word_cap(long_text, max_words=350)
    assert was_capped is True
    capped_words = re.findall(r"\b\w+\b", capped_text)
    assert len(capped_words) <= 350
    # Must end at a clean sentence boundary
    assert capped_text.endswith(".")
    # Shorter text within cap should not be modified
    short_text = "Short text with only seven words in it."
    unchanged, was_cut = trim_to_word_cap(short_text, max_words=350)
    assert was_cut is False
    assert unchanged == short_text



def test_persona_detail_rules_and_opener_prohibition():
    from backend.config import ROOT_DIR
    persona_path = ROOT_DIR / "config" / "hinaku_persona.md"
    assert persona_path.exists()
    content = persona_path.read_text(encoding="utf-8")

    # 1. Asks for about 250 words ending with a one-sentence conclusion
    assert "about 250 words ending with a one-sentence conclusion" in content

    # 2. Forbids "Okay, let's break down" opener
    assert "Okay, let's break down" in content
    assert "Never open explanations with filler phrases" in content


class MockDetailAdapter:
    def __init__(self, reply: str):
        self.reply = reply
        self.call_count = 0
        self.last_messages = None

    async def stream_chat(self, *args, **kwargs):
        self.call_count += 1
        self.last_messages = kwargs.get("messages", [])
        yield self.reply


@pytest.mark.asyncio
async def test_detail_mode_regenerates_when_over_350_words():
    from backend.quality import perform_reply_verification

    # Create a 400-word draft (40 sentences * 10 words)
    sentences_long = [f"Sentence number {i} contains exactly ten words to test proper length." for i in range(1, 41)]
    long_draft = " ".join(sentences_long)
    words = re.findall(r"\b\w+\b", long_draft)
    assert len(words) == 440

    # Shorter regenerated reply (~200 words) ending with a one-sentence conclusion
    regen_sentences = [f"Concise sentence {i} contains exactly ten words for clean test." for i in range(1, 20)]
    regen_sentences.append("In conclusion, the architecture cleanly separates concerns.")
    regen_reply = " ".join(regen_sentences)
    regen_words = re.findall(r"\b\w+\b", regen_reply)
    assert len(regen_words) <= 350

    adapter = MockDetailAdapter(reply=regen_reply)

    final, verified, ms, status, reason = await perform_reply_verification(
        draft_reply=long_draft,
        used_backend="local",
        used_model="gemma3:4b",
        target_opts={},
        persona_state=None,
        clock_context="",
        memory_context="",
        is_detail=True,
        local_adapter=adapter,
        settings=None,
        messages_for_regen=[{"role": "user", "content": "Explain virtual memory in detail"}]
    )

    assert adapter.call_count == 1
    # Verify extra instruction was passed
    assert any("200 words" in m.get("content", "") for m in adapter.last_messages)
    assert any("one-sentence conclusion" in m.get("content", "") for m in adapter.last_messages)
    assert final == regen_reply
    assert status == "corrected"
    assert "Regenerated detail reply to target under 350 words" in reason


@pytest.mark.asyncio
async def test_detail_mode_trims_at_sentence_boundary_as_last_resort():
    from backend.quality import perform_reply_verification

    # Create a 440-word draft
    sentences_long = [f"Sentence number {i} contains exactly ten words to test proper length." for i in range(1, 41)]
    long_draft = " ".join(sentences_long)

    # Adapter returns a candidate that is STILL over 350 words (440 words)
    stubborn_adapter = MockDetailAdapter(reply=long_draft)

    final, verified, ms, status, reason = await perform_reply_verification(
        draft_reply=long_draft,
        used_backend="local",
        used_model="gemma3:4b",
        target_opts={},
        persona_state=None,
        clock_context="",
        memory_context="",
        is_detail=True,
        local_adapter=stubborn_adapter,
        settings=None,
        messages_for_regen=[{"role": "user", "content": "Explain virtual memory in detail"}]
    )

    assert stubborn_adapter.call_count == 1
    final_words = re.findall(r"\b\w+\b", final)
    assert len(final_words) <= 350
    assert final.endswith(".")
    assert "last resort" in reason
