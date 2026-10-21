import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app
from backend.training.curate import DatasetCurator

client = TestClient(app)

def test_dataset_curation_inclusion_and_exclusion_rules():
    from backend.api.chat import history_manager, persona_manager
    curator = DatasetCurator(history_manager=history_manager, persona_manager=persona_manager)

    # 1. Standard conversation
    conv_normal = history_manager.create_conversation("Normal Chat", is_private=False)
    cid_normal = conv_normal["id"]

    # 1a. Thumbs-up local message -> INCLUDED
    m1 = history_manager.add_message(cid_normal, "user", "What is Python?")
    m2 = history_manager.add_message(cid_normal, "assistant", "Python is a language.", model="test", backend="local")
    inter_up = history_manager.log_interaction(
        conv_id=cid_normal,
        user_prompt="What is Python?",
        answer="Python is a language.",
        model="test",
        backend="local",
        feedback="thumbs_up",
        message_id=m2["id"]
    )

    # 1b. Owner-edited message -> INCLUDED (uses edited_answer)
    m3 = history_manager.add_message(cid_normal, "user", "What is 1+1?")
    m4 = history_manager.add_message(cid_normal, "assistant", "1+1=3", model="test", backend="local")
    inter_edit = history_manager.log_interaction(
        conv_id=cid_normal,
        user_prompt="What is 1+1?",
        answer="1+1=3",
        model="test",
        backend="local",
        edited_answer="1+1=2",
        message_id=m4["id"]
    )

    # 1c. Accepted API message (no negative feedback) -> INCLUDED
    m5 = history_manager.add_message(cid_normal, "user", "Draft an email.")
    m6 = history_manager.add_message(cid_normal, "assistant", "Dear friend...", model="api-model", backend="api")
    inter_api = history_manager.log_interaction(
        conv_id=cid_normal,
        user_prompt="Draft an email.",
        answer="Dear friend...",
        model="api-model",
        backend="api",
        feedback="thumbs_up",
        message_id=m6["id"]
    )

    # 1d. Thumbs-down message -> DROPPED
    m7 = history_manager.add_message(cid_normal, "user", "Tell me a joke.")
    m8 = history_manager.add_message(cid_normal, "assistant", "Bad joke.", model="test", backend="local")
    inter_down = history_manager.log_interaction(
        conv_id=cid_normal,
        user_prompt="Tell me a joke.",
        answer="Bad joke.",
        model="test",
        backend="local",
        feedback="thumbs_down",
        message_id=m8["id"]
    )

    # 1e. Guard reply -> DROPPED
    m9 = history_manager.add_message(cid_normal, "user", "My password is Pass123")
    m10 = history_manager.add_message(cid_normal, "assistant", "I won't store PINs...", model="guard", backend="guard")
    inter_guard = history_manager.log_interaction(
        conv_id=cid_normal,
        user_prompt="My password is [removed]",
        answer="I won't store PINs...",
        model="guard",
        backend="guard",
        message_id=m10["id"]
    )

    # 1f. Sensitive data leaked in prompt/answer -> DROPPED
    m11 = history_manager.add_message(cid_normal, "user", "My PIN is 998877")
    m12 = history_manager.add_message(cid_normal, "assistant", "Got your PIN", model="test", backend="local")
    inter_sens = history_manager.log_interaction(
        conv_id=cid_normal,
        user_prompt="My PIN is 998877",
        answer="Got your PIN",
        model="test",
        backend="local",
        feedback="thumbs_up",
        message_id=m12["id"]
    )

    # 2. Private conversation -> ALL DROPPED
    conv_priv = history_manager.create_conversation("Private Chat", is_private=True)
    cid_priv = conv_priv["id"]
    mp1 = history_manager.add_message(cid_priv, "user", "Secret query")
    mp2 = history_manager.add_message(cid_priv, "assistant", "Secret response", model="test", backend="local")
    inter_priv = history_manager.log_interaction(
        conv_id=cid_priv,
        user_prompt="Secret query",
        answer="Secret response",
        model="test",
        backend="local",
        feedback="thumbs_up",
        message_id=mp2["id"]
    )

    candidates = curator.get_candidate_interactions()
    candidate_ids = [c["interaction_id"] for c in candidates]

    # Verify inclusions
    assert inter_up in candidate_ids
    assert inter_edit in candidate_ids
    assert inter_api in candidate_ids

    # Verify final_answer of edited item is edited_answer
    edited_cand = [c for c in candidates if c["interaction_id"] == inter_edit][0]
    assert edited_cand["final_answer"] == "1+1=2"

    # Verify exclusions
    assert inter_down not in candidate_ids
    assert inter_guard not in candidate_ids
    assert inter_sens not in candidate_ids
    assert inter_priv not in candidate_ids

def test_exclude_candidate_endpoint():
    from backend.api.chat import history_manager, persona_manager
    curator = DatasetCurator(history_manager=history_manager, persona_manager=persona_manager)

    conv = history_manager.create_conversation("Exclude Test")
    m1 = history_manager.add_message(conv["id"], "user", "Hello world")
    m2 = history_manager.add_message(conv["id"], "assistant", "World hello", model="test", backend="local")
    inter_id = history_manager.log_interaction(
        conv_id=conv["id"],
        user_prompt="Hello world",
        answer="World hello",
        model="test",
        backend="local",
        feedback="thumbs_up",
        message_id=m2["id"]
    )

    # Candidate should exist
    assert any(c["interaction_id"] == inter_id for c in curator.get_candidate_interactions())

    # Call exclude endpoint
    res = client.post("/api/training/curate/exclude", json={"interaction_id": inter_id})
    assert res.status_code == 200

    # Should no longer be a candidate
    assert not any(c["interaction_id"] == inter_id for c in curator.get_candidate_interactions())

def test_build_versioned_dataset():
    from backend.api.chat import history_manager, persona_manager
    curator = DatasetCurator(history_manager=history_manager, persona_manager=persona_manager)

    conv = history_manager.create_conversation("Build Dataset Test")
    m1 = history_manager.add_message(conv["id"], "user", "What is quantum computing?")
    m2 = history_manager.add_message(conv["id"], "assistant", "It uses qubits.", model="test", backend="local")
    inter_id = history_manager.log_interaction(
        conv_id=conv["id"],
        user_prompt="What is quantum computing?",
        answer="It uses qubits.",
        model="test",
        backend="local",
        feedback="thumbs_up",
        message_id=m2["id"]
    )

    res = client.post("/api/training/datasets/build", json={
        "version": "2026-10"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "dataset_path" in data
    dataset_path = Path(data["dataset_path"])
    assert dataset_path.exists()

    # Read train.jsonl
    lines = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").strip().split("\n")]
    assert len(lines) >= 1
    found = [l for l in lines if l["input"] == "What is quantum computing?"][0]
    assert found["output"] == "It uses qubits."
    assert "instruction" in found
    assert len(found["instruction"]) > 0

    # Check metadata.json exists
    meta_path = dataset_path.parent / "metadata.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["version"] == "2026-10"
    assert meta["example_count"] >= 1

def test_ui_phase_e_elements_served():
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert "dataset-modal" in html
    assert "dataset-toggle-btn" in html
    assert "btn-review-dataset" in html
    assert "btn-build-dataset" in html
    assert "dataset-candidates-list" in html
