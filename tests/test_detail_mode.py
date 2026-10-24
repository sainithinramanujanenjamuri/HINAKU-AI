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

