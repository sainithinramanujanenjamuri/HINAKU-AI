import json
import pytest
from backend.config import get_settings
from backend.memory.safety import (
    validate_memory_quality,
    format_to_third_person,
    resolve_pronouns_in_fact,
    is_mood_or_health_statement,
    is_temporary_state,
    contains_time_reference,
    is_verbatim_copy
)

def test_reject_mood_mental_state_and_health():
    # Never store mood, mental-state, or health statements
    invalid_cases = [
        "I feel low and lost",
        "Owner has depression and anxiety",
        "Owner is feeling very sad and hopeless",
        "Diagnosed with diabetes",
        "Doctor prescribed new medication for heart condition",
        "Going to the hospital for surgery"
    ]
    for text in invalid_cases:
        is_valid, _, reason = validate_memory_quality(text)
        assert not is_valid, f"Expected '{text}' to be rejected, but passed"
        assert "Mood" in reason or "health" in reason


def test_reject_temporary_states_and_fleeting_conditions():
    # Never store temporary states ("I'm tired after a long coding session", "I'm hungry", "I'm busy today")
    invalid_cases = [
        "I'm tired after a long coding session",
        "I'm hungry",
        "I'm busy today",
        "Owner is exhausted",
        "Feeling sleepy right now",
        "Owner has a headache"
    ]
    for text in invalid_cases:
        is_valid, _, reason = validate_memory_quality(text)
        assert not is_valid, f"Expected '{text}' to be rejected, but passed"


def test_reject_time_references():
    # Anything with a time reference ("today", "this week", "tomorrow") is not a memory
    time_cases = [
        "Has an important meeting today",
        "Is learning Rust this week",
        "Has a major exam tomorrow",
        "Went to the gym yesterday",
        "Is coding late tonight"
    ]
    for text in time_cases:
        is_valid, _, reason = validate_memory_quality(text)
        assert not is_valid, f"Expected '{text}' to be rejected for time reference"
        assert "time reference" in reason.lower()


def test_third_person_formatting():
    # Write every memory in third person with plain wording ("Wants to build an LLM", "Cooks for himself")
    assert format_to_third_person("I want to build an LLM") == "Wants to build an LLM"
    assert format_to_third_person("I cook for myself") == "Cooks for himself"
    assert format_to_third_person("My favorite code editor is VS Code") == "Favorite code editor is VS Code"
    assert format_to_third_person("I use Python and TypeScript") == "Uses Python and TypeScript"
    assert format_to_third_person("I live in Bengaluru") == "Lives in Bengaluru"
    assert format_to_third_person("I drink black coffee") == "Drinks black coffee"


def test_resolve_pronouns_or_reject():
    # Resolve pronouns from conversation ("it" becomes the named thing); if cannot be resolved, do not store
    # Case 1: Resolvable from user message
    user_msg = "I want to build an LLM model and open source it"
    fact = "Wants to open source it"
    resolved_fact, is_resolved = resolve_pronouns_in_fact(fact, user_message=user_msg)
    assert is_resolved is True
    assert "LLM model" in resolved_fact
    assert "it" not in resolved_fact.split()

    # Case 2: Unresolvable pronoun (no entity in context)
    unresolvable_fact = "Wants to open source it"
    is_valid, _, reason = validate_memory_quality(unresolvable_fact, user_message="I want to open source it")
    assert not is_valid
    assert "unresolved pronoun" in reason.lower()

    unresolvable_fact2 = "Likes that a lot"
    is_valid2, _, reason2 = validate_memory_quality(unresolvable_fact2, user_message="I like that a lot")
    assert not is_valid2
    assert "unresolved pronoun" in reason2.lower()


def test_reject_verbatim_user_message():
    # Do not store the user's message word for word
    user_msg = "Favorite programming language is Python"
    fact = "Favorite programming language is Python"
    assert is_verbatim_copy(fact, user_msg) is True
    is_valid, _, reason = validate_memory_quality(fact, user_message=user_msg)
    assert not is_valid
    assert "Verbatim copy" in reason


def test_valid_durable_facts():
    # Valid durable facts and preferences
    valid_cases = [
        ("Uses a laptop with an RTX 4050 and 6 GB VRAM", "Uses a laptop with an RTX 4050 and 6 GB VRAM"),
        ("I prefer VS Code as my primary editor", "Prefers VS Code as his primary editor"),
        ("Primary programming language is Python", "Primary programming language is Python"),
        ("Drinks black coffee while coding", "Drinks black coffee while coding"),
    ]
    for candidate, expected in valid_cases:
        is_valid, processed, reason = validate_memory_quality(candidate, user_message="What tools do you like?")
        assert is_valid, f"Expected '{candidate}' to be valid, got: {reason}"
        assert processed.strip() != ""


def test_helpline_numbers_configured():
    settings = get_settings()
    helplines = settings.helpline_numbers
    assert isinstance(helplines, list)
    assert len(helplines) == 2
    names = [h.get("name", "") for h in helplines]
    assert "Tele-MANAS" in names
    assert "Emergency Services" in names
    # Verify no foreign 988 or merged KIRAN
    assert not any("988" in n or "KIRAN" in n for n in names)
    numbers = [h.get("number", "") for h in helplines]
    assert any("14416" in num for num in numbers)
    assert any("112" in num for num in numbers)


def test_hopelessness_detection():
    from backend.guards import is_hopelessness_or_self_harm, is_sensitive_topic
    despair_cases = [
        "I feel hopeless about everything",
        "nothing matters anymore",
        "I want to kill myself",
        "I feel like ending my life",
        "I can't go on like this",
        "thinking about self-harm"
    ]
    for text in despair_cases:
        assert is_hopelessness_or_self_harm(text), f"Failed for '{text}'"
        sens, _ = is_sensitive_topic(text)
        assert sens, f"Failed sensitive check for '{text}'"

    non_despair_sensitive = [
        "I broke up with my girlfriend yesterday",
        "I am stressed about my exam tomorrow",
        "I have a fever and cough",
        "I lost my job and I am broke"
    ]
    for text in non_despair_sensitive:
        assert not is_hopelessness_or_self_harm(text), f"Unexpected despair match for '{text}'"
        sens, _ = is_sensitive_topic(text)
        assert sens, f"Expected sensitive topic for '{text}'" 


def test_eval_golden_contains_emotional_support():
    with open("eval/golden.jsonl", "r", encoding="utf-8") as f:
        prompts = [json.loads(line) for line in f if line.strip()]

    support_prompts = [p for p in prompts if p.get("category") == "emotional_support"]
    assert len(support_prompts) == 6
    ids = {p["id"] for p in support_prompts}
    assert "emotional-support-01" in ids
    assert "emotional-support-04" in ids
    assert "emotional-support-06" in ids


def test_one_fact_per_memory_and_faithful_wording():
    """
    Verifies that compound user messages extract exactly one fact per memory
    with faithful wording and proper punctuation.
    """
    from backend.memory.extractor import MemoryExtractor
    extractor = MemoryExtractor(local_adapter=None, storage=None)
    
    # 1. Test user message: "my favorite fruit is mango and I live in Seattle"
    facts = extractor.parse_extracted_text(
        "my favorite fruit is mango and I live in Seattle",
        user_message="my favorite fruit is mango and I live in Seattle"
    )
    assert facts == ["Favorite fruit is mango.", "Lives in Seattle."]

    # 2. Test bullet-separated output from model
    bullet_facts = extractor.parse_extracted_text(
        "- Favorite fruit is mango.\n- Lives in Seattle.",
        user_message="my favorite fruit is mango and I live in Seattle"
    )
    assert bullet_facts == ["Favorite fruit is mango.", "Lives in Seattle."]

    # 3. Test compound sentence from model
    compound_facts = extractor.parse_extracted_text(
        "Favorite fruit is mango and lives in Seattle",
        user_message="my favorite fruit is mango and I live in Seattle"
    )
    assert compound_facts == ["Favorite fruit is mango.", "Lives in Seattle."]


def test_pending_memory_extractions_sqlite_persistence(tmp_path):
    """
    Verifies that pending memory extractions are persisted in SQLite (pending_memory_extractions)
    and successfully recovered across simulated application restarts.
    """
    from backend.memory.storage import MemoryStorage
    from backend.memory.manager import MemoryManager

    db_path = tmp_path / "test_pending.db"
    chroma_path = tmp_path / "chroma_pending"

    def fake_embed(_model, texts):
        return [[0.1] * 64 for _ in texts]

    # Session 1: Enqueue an extraction
    storage1 = MemoryStorage(
        db_path=db_path,
        chroma_path=chroma_path,
        embedding_model="test",
        embedding_dims=64,
        custom_embedder=fake_embed
    )
    mgr1 = MemoryManager(storage=storage1, extractor=None, enabled=True, idle_delay_seconds=60)
    mgr1.schedule_extraction(
        conversation_id="conv-persistent-1",
        user_message="my favorite fruit is mango and I live in Seattle",
        assistant_message="Understood.",
        is_private=False
    )

    assert len(mgr1._pending_extractions) == 1
    db_items = storage1.get_pending_extractions()
    assert len(db_items) == 1
    assert db_items[0]["conversation_id"] == "conv-persistent-1"
    assert db_items[0]["user_message"] == "my favorite fruit is mango and I live in Seattle"

    # Session 2 (Simulated App Restart):
    storage2 = MemoryStorage(
        db_path=db_path,
        chroma_path=chroma_path,
        embedding_model="test",
        embedding_dims=64,
        custom_embedder=fake_embed
    )
    mgr2 = MemoryManager(storage=storage2, extractor=None, enabled=True, idle_delay_seconds=60)
    assert len(mgr2._pending_extractions) == 1
    recovered = mgr2._pending_extractions[0]
    assert recovered["user_message"] == "my favorite fruit is mango and I live in Seattle"
    assert recovered["conversation_id"] == "conv-persistent-1"

    # Completion deletes the pending item
    storage2.delete_pending_extraction(recovered["id"])
    assert len(storage2.get_pending_extractions()) == 0

