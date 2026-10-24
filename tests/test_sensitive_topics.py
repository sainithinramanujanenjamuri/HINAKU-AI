import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.guards import is_sensitive_topic
from backend.models.router import ModelRouter
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter
from backend.history import ChatHistoryManager
from backend.memory.manager import MemoryManager

def test_is_sensitive_topic_categories():
    # Mental health
    sens, cat = is_sensitive_topic("I feel low and lost")
    assert sens is True
    assert cat == "mental_health"

    sens, cat = is_sensitive_topic("I am having severe anxiety and panic attacks")
    assert sens is True
    assert cat == "mental_health"

    # Mood
    sens, cat = is_sensitive_topic("I have been in a terrible mood all day")
    assert sens is True
    assert cat == "mood"

    # Health
    sens, cat = is_sensitive_topic("My doctor said I have an illness and need medication")
    assert sens is True
    assert cat == "health"

    sens, cat = is_sensitive_topic("I have a high fever and severe chest pain")
    assert sens is True
    assert cat == "health"

    # Money trouble
    sens, cat = is_sensitive_topic("I am broke and can't pay rent this month")
    assert sens is True
    assert cat == "money_trouble"

    sens, cat = is_sensitive_topic("I am in massive debt and facing bankruptcy")
    assert sens is True
    assert cat == "money_trouble"

    # Personal relationships
    sens, cat = is_sensitive_topic("My partner and I broke up after a huge fight")
    assert sens is True
    assert cat == "personal_relationships"

    sens, cat = is_sensitive_topic("I am going through a painful divorce")
    assert sens is True
    assert cat == "personal_relationships"

    # Non-sensitive queries
    sens, _ = is_sensitive_topic("Explain quicksort in Python")
    assert sens is False

    sens, _ = is_sensitive_topic("What is the speed of light?")
    assert sens is False

    sens, _ = is_sensitive_topic("How do vector databases perform approximate nearest neighbor search?")
    assert sens is False


def test_sensitive_topic_forces_local_and_forbids_api():
    local = MagicMock(spec=OllamaAdapter)
    local.default_model = "gemma3:4b"

    api = MagicMock(spec=ApiAdapter)
    api.model = "test-api-model"
    api.api_key = "test-key"

    router = ModelRouter(
        local_adapter=local,
        api_adapter=api,
        mode="auto",
        fallback_on_failure=True
    )

    sensitive_prompts = [
        "I feel low and lost today",
        "My doctor prescribed medication for an illness",
        "I can't pay rent, I am completely broke",
        "My wife and I broke up yesterday"
    ]

    for prompt in sensitive_prompts:
        is_sens, cat = is_sensitive_topic(prompt)
        assert is_sens is True

        # When auto-private marks is_private=True, router must stay local
        decision = router.decide_backend(prompt, is_private=True)
        assert decision.target_backend == "local"
        assert decision.fallback_allowed is False
        assert decision.target_model == "gemma3:4b"


def test_sensitive_topic_privacy_guards_context_and_skips_extraction():
    storage = MagicMock()
    extractor = MagicMock()

    mgr = MemoryManager(
        storage=storage,
        extractor=extractor,
        enabled=True,
        learn_from_private_chats=False
    )

    # Context retrieval must return empty string for private chats
    ctx = mgr.retrieve_context("I feel low and lost", is_private=True)
    assert ctx == ""
    storage.query_memories.assert_not_called()

    # Memory extraction must immediately return empty list and skip extractor
    coro = mgr.extract_and_store(
        conversation_id="conv-private-01",
        user_message="I feel low and lost, my doctor gave me medication",
        assistant_message="Take things one step at a time.",
        is_private=True
    )
    try:
        coro.send(None)
    except StopIteration as e:
        assert e.value == []
    extractor.process_exchange.assert_not_called()


def test_conversation_privacy_persistence_and_undo(tmp_path):
    db_path = tmp_path / "privacy_test.db"
    hm = ChatHistoryManager(db_path)

    conv_id = "test-conv-priv-undo"
    hm.create_conversation(title="Test Sensitive", conv_id=conv_id, is_private=False)
    assert hm.get_conversation(conv_id)["is_private"] == 0

    # Auto-private trigger marks conversation private
    hm.set_conversation_privacy(conv_id, True)
    assert hm.get_conversation(conv_id)["is_private"] == 1

    # User clicks Undo: marks conversation back to standard
    hm.set_conversation_privacy(conv_id, False)
    assert hm.get_conversation(conv_id)["is_private"] == 0
