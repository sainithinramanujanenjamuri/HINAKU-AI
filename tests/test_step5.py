import json
import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.memory.safety import is_safe_to_store, filter_safe_facts
from backend.memory.storage import MemoryStorage, l2_normalize
from backend.memory.extractor import MemoryExtractor
from backend.memory.manager import MemoryManager, CONTEXT_HEADER

client = TestClient(app)

def fake_word_embedder(_model: str, texts: list) -> list:
    """Deterministic offline bag-of-words embedder for fast unit tests."""
    import hashlib
    out = []
    for t in texts:
        vec = [0.0] * 64
        words = "".join(c.lower() if c.isalnum() else " " for c in t).split()
        for w in words:
            h = int(hashlib.md5(w.encode()).hexdigest(), 16) % 64
            vec[h] += 1.0
        out.append(l2_normalize(vec))
    return out

@pytest.fixture
def storage(tmp_path):
    db_file = tmp_path / "test_mem.db"
    chroma_dir = tmp_path / "test_chroma_dir"
    return MemoryStorage(
        db_path=db_file,
        chroma_path=chroma_dir,
        embedding_model="test-embed-model",
        embedding_dims=64,
        query_prefix="search_query: ",
        document_prefix="",
        custom_embedder=fake_word_embedder
    )

def test_sqlite_and_chroma_crud(storage):
    # 1. Add memory
    mem1 = storage.add_memory("Uses an RTX 4050 GPU", source_conversation_id="conv-1")
    assert mem1["id"] is not None
    assert mem1["text"] == "Uses an RTX 4050 GPU"
    assert mem1["deleted"] == 0

    # 2. Get memories
    all_mems = storage.get_memories()
    assert len(all_mems) == 1
    assert all_mems[0]["id"] == mem1["id"]

    # 3. Update memory
    updated = storage.update_memory(mem1["id"], "Uses an RTX 4050 GPU with 6 GB VRAM")
    assert updated["text"] == "Uses an RTX 4050 GPU with 6 GB VRAM"
    assert storage.get_memory(mem1["id"])["text"] == "Uses an RTX 4050 GPU with 6 GB VRAM"

    # 4. Delete memory (hard-deletes from SQLite and deletes from Chroma)
    deleted = storage.delete_memory(mem1["id"])
    assert deleted is True
    assert len(storage.get_memories(include_deleted=False)) == 0
    assert len(storage.get_memories(include_deleted=True)) == 0
    assert storage.get_memory(mem1["id"]) is None
    assert storage.collection.count() == 0

def test_auto_rebuild_and_manual_reindex(tmp_path):
    db_file = tmp_path / "rebuild_mem.db"
    chroma_dir = tmp_path / "rebuild_chroma_dir"

    # Create initial storage with model-v1
    s1 = MemoryStorage(
        db_path=db_file,
        chroma_path=chroma_dir,
        embedding_model="model-v1",
        embedding_dims=64,
        custom_embedder=fake_word_embedder
    )
    s1.add_memory("Favorite editor is VS Code")
    s1.add_memory("Studies computer science")
    assert s1.collection.count() == 2
    assert s1.collection.metadata["embedding_model"] == "model-v1"

    # Re-initialize storage with model-v2 -> triggers auto-rebuild
    s2 = MemoryStorage(
        db_path=db_file,
        chroma_path=chroma_dir,
        embedding_model="model-v2",
        embedding_dims=64,
        custom_embedder=fake_word_embedder
    )
    assert s2.collection.metadata["embedding_model"] == "model-v2"
    assert s2.collection.count() == 2

    # Manual re-index
    reindexed_count = s2.reindex_memories()
    assert reindexed_count == 2
    assert s2.collection.count() == 2

def test_never_store_safety_filters():
    # Passwords
    assert is_safe_to_store("My password is supersecret123")[0] is False
    assert is_safe_to_store("Password: AdminPass2026!")[0] is False
    assert is_safe_to_store("pwd=qwertyuiop")[0] is False

    # API Keys & Tokens
    assert is_safe_to_store("My key is sk-1234567890abcdef1234567890abcdef")[0] is False
    assert is_safe_to_store("github token: ghp_1234567890abcdef1234567890abcdef")[0] is False
    assert is_safe_to_store("api_key = 'abcdef1234567890abcdef1234'")[0] is False

    # Government IDs
    assert is_safe_to_store("SSN is 123-45-6789")[0] is False
    assert is_safe_to_store("Aadhaar: 1234 5678 9012")[0] is False
    assert is_safe_to_store("PAN card: ABCDE1234F")[0] is False

    # Bank / Card numbers
    assert is_safe_to_store("Visa card: 4111 2222 3333 4444")[0] is False
    assert is_safe_to_store("Bank account: 12345678901234")[0] is False

    # Safe facts
    assert is_safe_to_store("Uses an RTX 4050 GPU with 6 GB VRAM")[0] is True
    assert is_safe_to_store("Favorite editor is VS Code")[0] is True
    assert is_safe_to_store("Drinks green tea instead of coffee")[0] is True

    # filter_safe_facts
    dirty = [
        "Prefers VS Code",
        "password: mysecretpassword",
        "Uses Windows 11"
    ]
    safe = filter_safe_facts(dirty)
    assert safe == ["Prefers VS Code", "Uses Windows 11"]

@pytest.mark.asyncio
async def test_extractor_dedupe_and_merge(storage):
    from unittest.mock import MagicMock
    mock_local = MagicMock()
    extractor = MemoryExtractor(
        local_adapter=mock_local,
        storage=storage,
        merge_threshold=0.75
    )

    async def mock_stream(chunks):
        for c in chunks:
            yield c

    # 1. Initial fact
    mock_local.stream_chat.return_value = mock_stream(["Uses a laptop with an RTX 4050 GPU"])
    saved1 = await extractor.process_exchange("conv-1", "I have an RTX 4050 laptop", "Got it.")
    assert len(saved1) == 1
    m1_id = saved1[0]["id"]
    assert storage.get_memory(m1_id)["text"] == "Uses a laptop with an RTX 4050 GPU"

    # 2. Near-duplicate / updated fact -> should update existing row
    mock_local.stream_chat.return_value = mock_stream(["Uses a laptop with an RTX 4050 GPU and 6 GB VRAM"])
    saved2 = await extractor.process_exchange("conv-1", "It has 6 GB VRAM", "Noted.")
    assert len(saved2) == 1
    assert saved2[0]["id"] == m1_id
    assert storage.get_memory(m1_id)["text"] == "Uses a laptop with an RTX 4050 GPU and 6 GB VRAM"
    assert len(storage.get_memories()) == 1

def test_privacy_rules_and_injection(storage):
    mock_local = AsyncMock()
    extractor = MemoryExtractor(local_adapter=mock_local, storage=storage)
    manager = MemoryManager(
        storage=storage,
        extractor=extractor,
        enabled=True,
        learn_from_private_chats=False,
        retrieve_top_k=3,
        min_similarity=0.3
    )

    storage.add_memory("Favorite editor is VS Code")

    # Local request -> memories injected
    ctx_local = manager.retrieve_context("Which editor should I use?", is_private=False, is_api_request=False)
    assert CONTEXT_HEADER in ctx_local
    assert "Favorite editor is VS Code" in ctx_local

    # API request with send_personal_context=False -> NEVER injected
    ctx_api = manager.retrieve_context("Which editor should I use?", is_private=False, is_api_request=True, send_personal_context=False)
    assert ctx_api == ""

    # Private chat -> NEVER injected
    ctx_private = manager.retrieve_context("Which editor should I use?", is_private=True, is_api_request=False)
    assert ctx_private == ""

    # Memory disabled -> NEVER injected
    manager.enabled = False
    assert manager.retrieve_context("Which editor should I use?", is_private=False, is_api_request=False) == ""

def test_memory_api_endpoints():
    # 1. List
    res = client.get("/api/memories")
    assert res.status_code == 200
    initial_count = len(res.json())

    # Add memory through chat or direct storage
    from backend.api.chat import memory_storage
    new_mem = memory_storage.add_memory("Prefers dark mode in all apps")

    res = client.get("/api/memories")
    assert res.status_code == 200
    assert len(res.json()) == initial_count + 1

    # 2. Patch
    patch_res = client.patch(f"/api/memories/{new_mem['id']}", json={"text": "Prefers dark mode always"})
    assert patch_res.status_code == 200
    assert patch_res.json()["text"] == "Prefers dark mode always"

    # 3. Delete
    del_res = client.delete(f"/api/memories/{new_mem['id']}")
    assert del_res.status_code == 200

    # Confirm hard-deleted
    assert memory_storage.get_memory(new_mem['id']) is None
    assert client.get("/api/memories").json() == []

    # 4. Reindex endpoint
    reindex_res = client.post("/api/memories/reindex")
    assert reindex_res.status_code == 200
    assert "count" in reindex_res.json()

def test_retrieval_quality_12_memories():
    """
    Retrieval-quality test with 12 sample memories and reworded queries,
    verifying that top-3 recall is at least 90%.
    """
    memories = [
        "Uses an RTX 4050 GPU with 6 GB VRAM",                  # 0
        "Favorite code editor is VS Code",                     # 1
        "Is a computer science student",                       # 2
        "Prefers short, direct answers",                       # 3
        "Builds AI projects in Python 3.11",                   # 4
        "Uses Ollama to run local models",                     # 5
        "Drinks green tea instead of coffee",                  # 6
        "Lives in Telangana, India",                           # 7
        "Has a pet dog named Bruno",                           # 8
        "Prefers dark mode in every application",              # 9
        "Wakes up at 6 AM on weekdays",                        # 10
        "Is learning Japanese",                                # 11
    ]

    queries = [
        ("Which graphics card is in my laptop?", 0),
        ("What editor should I configure?", 1),
        ("What degree am I studying for?", 2),
        ("How concise should your responses be?", 3),
        ("Which Python version do I use for AI?", 4),
        ("What software runs my local LLMs?", 5),
        ("What hot beverage do I drink?", 6),
        ("Which Indian state do I live in?", 7),
        ("What is the name of my dog?", 8),
        ("Do I prefer light or dark mode theme?", 9),
        ("When do I wake up in the morning?", 10),
        ("Which language am I currently studying?", 11),
    ]

    import math

    # Check if local Ollama embedding model is reachable
    ollama_online = False
    try:
        import urllib.request
        body = json.dumps({"model": "qwen3-embedding:0.6b", "input": ["test"]}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/embed", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ollama_online = r.status == 200
    except Exception:
        ollama_online = False

    if not ollama_online:
        pytest.skip("Local Ollama embedding model qwen3-embedding:0.6b is not online or ready")

    # Live embedding test with qwen3-embedding:0.6b
    def embedder(texts, prefix=""):
        body = json.dumps({"model": "qwen3-embedding:0.6b", "input": [f"{prefix}{t}" for t in texts]}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/embed", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return [l2_normalize(v) for v in json.loads(r.read())["embeddings"]]

    q_prefix = "Instruct: Given the owner's message, retrieve stored facts about the owner that help answer it\nQuery: "
    doc_vectors = embedder(memories)
    query_vectors = embedder([q for q, _ in queries], prefix=q_prefix)

    def cosine_sim(a, b):
        return sum(x * y for x, y in zip(a, b))

    top3_hits = 0
    for (_, want_idx), qv in zip(queries, query_vectors):
        scored = sorted([(cosine_sim(qv, dv), i) for i, dv in enumerate(doc_vectors)], reverse=True)
        top3_indices = [idx for _, idx in scored[:3]]
        if want_idx in top3_indices:
            top3_hits += 1

    recall = top3_hits / len(queries)
    assert recall >= 0.90, f"Top-3 recall {recall:.1%} fell below required 90% threshold!"
