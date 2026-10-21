import datetime
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import get_settings, ROOT_DIR
from backend.guards import check_and_redact_sensitive_data, is_live_data_query
from backend.history import ChatHistoryManager
from backend.models.router import is_personal_statement, classify_prompt
from backend.memory.storage import MemoryStorage
from backend.memory.extractor import MemoryExtractor, consolidate_multi_value_facts, extract_attribute_key
from backend.training.curate import DatasetCurator
from backend.training.evaluate import EvaluationHarness
from backend.training.promote import ModelPromoter
from backend.scheduler.service import SelfBuildScheduler

client = TestClient(app)

# ==============================================================================
# 1. UI Labels & Guard Type Labels
# ==============================================================================

def test_guard_replies_labeled_by_type(monkeypatch):
    import backend.api.chat as chat_module

    # Mock models to ensure they are NOT called
    mock_local = MagicMock()
    mock_local.default_model = "gemma3:4b"
    mock_api = MagicMock()

    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    # 1. Sensitive-data guard
    res_sens = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "My secret password is SuperSecret123!"}],
        "stream": False
    })
    assert res_sens.status_code == 200
    sens_data = res_sens.json()
    assert sens_data["backend"] == "guard"
    assert sens_data["model"] == "sensitive-data guard"

    # 2. Live-data guard
    res_live = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "What is the current stock price of Apple right now?"}],
        "stream": False
    })
    assert res_live.status_code == 200
    live_data = res_live.json()
    assert live_data["backend"] == "guard"
    assert live_data["model"] == "live-data guard"


# ==============================================================================
# 2. Approval Gate: Confirmation Required for Promotion
# ==============================================================================

def test_approval_gate_prevents_unconfirmed_promotion(tmp_path):
    promoter = ModelPromoter(data_dir=tmp_path / "data", models_dir=tmp_path / "models")

    # Promoting without confirmed=True MUST raise ValueError
    with pytest.raises(ValueError, match="Approval gate"):
        promoter.promote(
            version="2026-10",
            candidate_score=0.95,
            current_local_score=0.80,
            confirmed=False
        )

    # With confirmed=True, promotion succeeds
    rec = promoter.promote(
        version="2026-10",
        candidate_score=0.95,
        current_local_score=0.80,
        confirmed=True
    )
    assert rec["status"] == "active"
    assert rec["version"] == "2026-10"

def test_api_promote_endpoint_requires_explicit_confirmation():
    # Calling /api/training/promote without confirmed=True fails with 400
    res_fail = client.post("/api/training/promote", json={
        "version": "2026-10",
        "candidate_score": 0.95,
        "current_local_score": 0.80,
        "confirmed": False
    })
    assert res_fail.status_code == 400
    assert "Approval gate" in res_fail.json()["detail"]


# ==============================================================================
# 3. Eval Set: >= 50 prompts, 2x Evaluation, 3+ Prompts Margin Rule
# ==============================================================================

def test_eval_golden_set_size_and_categories():
    golden_path = ROOT_DIR / "eval" / "golden.jsonl"
    assert golden_path.exists()

    items = []
    for line in golden_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(json.loads(line))

    assert len(items) >= 50, f"Expected at least 50 prompts, found {len(items)}"

    required_categories = {"persona", "honesty", "accuracy", "support", "boundaries", "privacy", "memory"}
    found_categories = {item.get("category") for item in items}
    assert required_categories.issubset(found_categories), f"Missing categories: {required_categories - found_categories}"

    for it in items:
        assert "must_include" in it and isinstance(it["must_include"], list)
        assert "must_avoid" in it and isinstance(it["must_avoid"], list)

def test_evaluator_two_runs_and_prompts_advantage_rule(tmp_path):
    golden_path = tmp_path / "golden.jsonl"
    sample_items = [
        {"id": f"q{i}", "category": "accuracy" if i % 2 == 0 else "persona", "prompt": f"Question {i}", "ideal": "answer", "must_include": [], "must_avoid": []}
        for i in range(10)
    ]
    with open(golden_path, "w", encoding="utf-8") as f:
        for it in sample_items:
            f.write(json.dumps(it) + "\n")

    harness = EvaluationHarness(golden_file=golden_path)

    # Candidate wins 4 more questions than local (margin = +4 >= 3)
    def cand_gen(prompt, mems=None):
        return "I am HINAKU, calm and composed answer."

    def local_gen(prompt, mems=None):
        if any(prompt.endswith(str(x)) for x in (0, 1, 2, 3)):
            return ""  # Local fails these 4 questions
        return "I am HINAKU, calm and composed answer."

    comp = harness.run_full_comparison(cand_gen, local_gen, runs=2)
    assert comp["candidate_wins"] == 4
    assert comp["local_wins"] == 0
    assert comp["prompts_margin"] == 4
    assert comp["no_category_worse"] is True
    assert comp["promotable"] is True
    assert len(comp["side_by_side"]) >= 10


# ==============================================================================
# 4. API Data in Training: Curation Settings & Source Attribution
# ==============================================================================

def test_curation_api_rules_and_source_tagging(tmp_path):
    db_path = tmp_path / "test_curate.db"
    hm = ChatHistoryManager(db_path)

    # 1. Create a conversation
    conv = hm.create_conversation("Curate Test")
    cid = conv["id"]

    # Message 1: Local message with thumbs-up
    m1 = hm.add_message(cid, "user", "What is my GPU?")
    m2 = hm.add_message(cid, "assistant", "RTX 4050", model="gemma3:4b", backend="local")
    hm.log_interaction(cid, "What is my GPU?", "RTX 4050", model="gemma3:4b", backend="local", feedback="thumbs_up", message_id=m2["id"])

    # Message 2: API message with thumbs-up
    m3 = hm.add_message(cid, "assistant", "API answer with thumbs up", model="api-model", backend="api")
    hm.log_interaction(cid, "Explain recursion", "API answer with thumbs up", model="api-model", backend="api", feedback="thumbs_up", message_id=m3["id"])

    # Message 3: API message without thumbs-up (feedback=None)
    m4 = hm.add_message(cid, "assistant", "API answer unthumbed", model="api-model", backend="api")
    hm.log_interaction(cid, "Explain closures", "API answer unthumbed", model="api-model", backend="api", feedback=None, message_id=m4["id"])

    # Message 4: Owner-edited message
    m5 = hm.add_message(cid, "assistant", "Original answer", model="gemma3:4b", backend="local")
    hm.log_interaction(cid, "My favorite editor", "Original answer", model="gemma3:4b", backend="local", edited_answer="VS Code edited", message_id=m5["id"])

    curator = DatasetCurator(history_manager=hm)

    # Case A: api_answers_require_thumbs_up=True -> unthumbed API answer excluded
    with patch("backend.training.curate.get_settings") as mock_settings:
        mock_s = MagicMock()
        mock_s.curation_api_answers_require_thumbs_up = True
        mock_s.curation_exclude_api_answers = False
        mock_settings.return_value = mock_s

        candidates = curator.get_candidate_interactions()
        prompts = [c["user_prompt"] for c in candidates]
        sources = {c["user_prompt"]: c["source"] for c in candidates}

        assert "What is my GPU?" in prompts
        assert sources["What is my GPU?"] == "local"

        assert "Explain recursion" in prompts
        assert sources["Explain recursion"] == "API"

        assert "Explain closures" not in prompts  # Unthumbed API answer was excluded!

        assert "My favorite editor" in prompts
        assert sources["My favorite editor"] == "owner-edited"

    # Case B: exclude_api_answers=True -> all unedited API answers excluded
    with patch("backend.training.curate.get_settings") as mock_settings:
        mock_s = MagicMock()
        mock_s.curation_api_answers_require_thumbs_up = True
        mock_s.curation_exclude_api_answers = True
        mock_settings.return_value = mock_s

        candidates_no_api = curator.get_candidate_interactions()
        prompts_no_api = [c["user_prompt"] for c in candidates_no_api]
        assert "Explain recursion" not in prompts_no_api
        assert "What is my GPU?" in prompts_no_api


# ==============================================================================
# 5. Scheduler Catch-Up: Store Date & Never Auto-Start Training
# ==============================================================================

def test_scheduler_persists_last_run_and_due_prompt(tmp_path):
    db_path = tmp_path / "scheduler_test.db"
    hm = ChatHistoryManager(db_path)

    # Initially, no last_run recorded -> due=True
    scheduler = SelfBuildScheduler(history_manager=hm)
    due_info = scheduler.check_run_due()
    assert due_info["due"] is True
    assert due_info["last_run"] is None

    # Record a run date 7 months ago
    seven_months_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=215)).isoformat()
    hm.set_metadata("last_self_build_date", seven_months_ago)

    scheduler2 = SelfBuildScheduler(history_manager=hm)
    assert scheduler2.last_run == seven_months_ago
    due_info2 = scheduler2.check_run_due()
    assert due_info2["due"] is True
    assert "due" in due_info2["message"].lower()

    # Record a run date 1 month ago
    one_month_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
    hm.set_metadata("last_self_build_date", one_month_ago)

    scheduler3 = SelfBuildScheduler(history_manager=hm)
    due_info3 = scheduler3.check_run_due()
    assert due_info3["due"] is False

    # Calling start() does NOT run training automatically
    scheduler3.start()
    assert scheduler3._is_running is True
    scheduler3.stop()


# ==============================================================================
# 6. Memory Extraction: Plural Multi-Value, Updates, Typo Correction
# ==============================================================================

def test_multi_value_facts_stored_as_single_plural_memory():
    split_facts = [
        "Favorite color is black",
        "Favorite color is red",
        "Favorite color is blue"
    ]
    consolidated = consolidate_multi_value_facts(split_facts)
    assert len(consolidated) == 1
    assert consolidated[0] == "Favorite colors are black, red, and blue"

def test_memory_update_on_new_values(tmp_path):
    db_path = tmp_path / "mem.db"
    chroma_path = tmp_path / "chroma"
    storage = MemoryStorage(
        db_path, chroma_path,
        custom_embedder=lambda m, texts: [[0.1] * 1024 for _ in texts]
    )
    extractor = MemoryExtractor(local_adapter=MagicMock(), storage=storage)

    # 1. Add initial memory
    storage.add_memory("Favorite colors are black and red")
    assert len(storage.get_memories()) == 1

    # 2. Process exchange with new colors
    mock_local = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "Favorite colors are purple and orange"
    mock_local.stream_chat = mock_stream
    extractor.local_adapter = mock_local

    import asyncio
    saved = asyncio.run(extractor.process_exchange("conv-1", "My favorite colors are purple and orange now", "Got it."))
    assert len(saved) == 1
    assert "purple and orange" in saved[0]["text"]

    # Verify existing memory was updated, NOT duplicated
    all_mems = storage.get_memories()
    assert len(all_mems) == 1
    assert "purple and orange" in all_mems[0]["text"]

def test_memory_typo_correction_reembeds(tmp_path):
    db_path = tmp_path / "typo.db"
    chroma_path = tmp_path / "chroma"

    # Custom embedder that reflects text content in vector
    def mock_embed(model, texts):
        vecs = []
        for t in texts:
            val = 0.9 if "vscode" in t.lower().replace(" ", "") else 0.1
            vecs.append([val] * 1024)
        return vecs

    storage = MemoryStorage(db_path, chroma_path, custom_embedder=mock_embed)

    # 1. Add with typo: "VS Cod"
    mem = storage.add_memory("Favorite editor is VS Cod")
    mem_id = mem["id"]

    # 2. Fix typo in drawer: "Favorite editor is VS Code"
    updated = storage.update_memory(mem_id, "Favorite editor is VS Code")
    assert updated["text"] == "Favorite editor is VS Code"

    # 3. Query Chroma to verify re-embedding occurred
    matches = storage.query_memories("VS Code", top_k=1, min_similarity=0.40)
    assert len(matches) > 0
    assert matches[0][0]["text"] == "Favorite editor is VS Code"


# ==============================================================================
# 7. Personal-Statement Routing: Personal vs Plain Task Requests
# ==============================================================================

def test_broadened_personal_statements_route_local():
    personal_queries = [
        "I feel completely overwhelmed with everything right now",
        "I'm worried about my medical diagnosis",
        "my family is visiting from out of town next week",
        "my health has been declining lately",
        "my salary was delayed by two weeks",
        "I live in Hyderabad near the tech corridor",
        "my job has been extremely stressful",
        "I just got hired at a new startup",
        "my girlfriend and I are celebrating our anniversary",
        "I'm planning to move to another apartment in June",
        "I just bought a new laptop with an RTX 4050"
    ]
    for q in personal_queries:
        assert is_personal_statement(q) is True, f"Failed to detect as personal: '{q}'"
        assert classify_prompt(q, is_private=False) == "local", f"Failed to route local: '{q}'"

def test_plain_task_requests_route_to_api():
    plain_tasks = [
        "I want to learn Python, can you help?",
        "I want to build a web scraper using BeautifulSoup",
        "I want to write a regex to validate email addresses",
        "Can you explain how Dijkstra's algorithm works?",
        "I need to debug this SQL query for finding duplicate rows",
        "Help me write a Python function to sort a list of dictionaries"
    ]
    for t in plain_tasks:
        assert is_personal_statement(t) is False, f"Incorrectly marked personal: '{t}'"
        assert classify_prompt(t, is_private=False) == "api", f"Failed to route to API: '{t}'"
