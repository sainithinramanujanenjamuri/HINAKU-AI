import pytest
from backend.models.router import ModelRouter, is_short_followup
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter
from backend.markdown import normalize_markdown

def test_is_short_followup():
    assert is_short_followup("can you give an example?") is True
    assert is_short_followup("make it shorter") is True
    assert is_short_followup("why?") is True
    assert is_short_followup("continue") is True
    assert is_short_followup("and in typescript?") is True
    assert is_short_followup("what about rust?") is True
    assert is_short_followup("tell me more about this") is True

    # New topic starters should NOT be follow-ups
    assert is_short_followup("what is agi") is False
    assert is_short_followup("what is the capital of Australia") is False
    assert is_short_followup("new question: how does photosynthesis work") is False
    assert is_short_followup("by the way what are black holes") is False

    # Over 12 words should not be considered a short follow-up
    long_followup = "could you please elaborate and give me much more detail about this concept because I did not understand"
    assert len(long_followup.split()) >= 12
    assert is_short_followup(long_followup) is False

def test_router_stickiness():
    local_adapter = OllamaAdapter(default_model="qwen3.5:4b")
    api_adapter = ApiAdapter(provider="openai_compatible", model="api-model", api_key="test-key")
    router_auto = ModelRouter(local_adapter, api_adapter, mode="auto")

    # 1. Short follow-up after an API reply should stick to API
    dec_sticky_api = router_auto.decide_backend(
        "can you give an example?",
        is_private=False,
        last_backend="api"
    )
    assert dec_sticky_api.target_backend == "api"

    # 2. Short follow-up after a Local reply should stick to Local
    dec_sticky_local = router_auto.decide_backend(
        "tell me more",
        is_private=False,
        last_backend="local"
    )
    assert dec_sticky_local.target_backend == "local"

    # 3. Private chat overrides stickiness (never uses API)
    dec_private = router_auto.decide_backend(
        "can you give an example?",
        is_private=True,
        last_backend="api"
    )
    assert dec_private.target_backend == "local"

    # 4. Forced modes override stickiness
    router_local = ModelRouter(local_adapter, api_adapter, mode="local_only")
    assert router_local.decide_backend(
        "can you give an example?",
        last_backend="api"
    ).target_backend == "local"

    router_api = ModelRouter(local_adapter, api_adapter, mode="api_only")
    assert router_api.decide_backend(
        "tell me more",
        last_backend="local"
    ).target_backend == "api"

    # 5. New topic does NOT stick to previous backend
    dec_new_topic = router_auto.decide_backend(
        "hi there",
        is_private=False,
        last_backend="api"
    )
    assert dec_new_topic.target_backend == "local"

def test_markdown_bold_heading_after_list_item():
    # Case 1: Bullet list item with immediate bold heading
    raw_md = "- First item\n- Second item\n**Next Steps:**\nDo this next."
    normalized = normalize_markdown(raw_md)
    expected = "- First item\n- Second item\n\n**Next Steps:**\nDo this next."
    assert normalized == expected

    # Case 2: Numbered list item with immediate bold heading
    raw_md_num = "1. Step one\n2. Step two\n**Summary**\nEnd of instructions."
    normalized_num = normalize_markdown(raw_md_num)
    assert normalized_num == "1. Step one\n2. Step two\n\n**Summary**\nEnd of instructions."

    # Case 3: Already separated by a blank line should not add extra blank lines
    already_spaced = "- Step one\n\n**Next Step**"
    assert normalize_markdown(already_spaced) == already_spaced

    # Case 4: Asterisk and plus bullet lists
    raw_star = "* Point A\n**Key Takeaway**"
    assert normalize_markdown(raw_star) == "* Point A\n\n**Key Takeaway**"

