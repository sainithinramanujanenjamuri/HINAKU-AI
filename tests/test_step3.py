import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.history import ChatHistoryManager, trim_history, generate_title, estimate_tokens

client = TestClient(app)

def test_history_manager_create_and_load(tmp_path):
    db_file = tmp_path / "test_hinaku.db"
    manager = ChatHistoryManager(db_file)

    conv = manager.create_conversation("First Chat")
    assert conv["id"] is not None
    assert conv["title"] == "First Chat"

    # Add messages
    m1 = manager.add_message(conv["id"], "user", "Hello there")
    assert m1["role"] == "user"
    assert m1["content"] == "Hello there"

    m2 = manager.add_message(conv["id"], "assistant", "I am listening", model="qwen3.5:4b")
    assert m2["role"] == "assistant"
    assert m2["model"] == "qwen3.5:4b"

    # Load conversation
    loaded = manager.get_conversation(conv["id"])
    assert loaded is not None
    assert loaded["title"] == "First Chat"
    assert len(loaded["messages"]) == 2
    assert loaded["messages"][0]["content"] == "Hello there"
    assert loaded["messages"][1]["content"] == "I am listening"

def test_history_manager_auto_title(tmp_path):
    db_file = tmp_path / "test_hinaku.db"
    manager = ChatHistoryManager(db_file)

    # Creating a conversation without title defaults to "New conversation"
    conv = manager.create_conversation()
    assert conv["title"] == "New conversation"

    # First user message should auto-title the conversation
    manager.add_message(conv["id"], "user", "What is the nature of the void?")
    loaded = manager.get_conversation(conv["id"])
    assert "What is the nature" in loaded["title"]

def test_history_manager_rename(tmp_path):
    db_file = tmp_path / "test_hinaku.db"
    manager = ChatHistoryManager(db_file)

    conv = manager.create_conversation("Old Title")
    renamed = manager.rename_conversation(conv["id"], "New Renamed Title")
    assert renamed["title"] == "New Renamed Title"

    loaded = manager.get_conversation(conv["id"])
    assert loaded["title"] == "New Renamed Title"

def test_history_manager_delete_permanently_removes_messages(tmp_path):
    db_file = tmp_path / "test_hinaku.db"
    manager = ChatHistoryManager(db_file)

    conv = manager.create_conversation("To be deleted")
    manager.add_message(conv["id"], "user", "Message 1")
    manager.add_message(conv["id"], "assistant", "Message 2")

    # Ensure messages exist
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv["id"],))
    count = cur.fetchone()[0]
    assert count == 2
    conn.close()

    # Delete conversation
    success = manager.delete_conversation(conv["id"])
    assert success is True
    assert manager.get_conversation(conv["id"]) is None

    # Check that messages are permanently deleted
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv["id"],))
    count_after = cur.fetchone()[0]
    conn.close()
    assert count_after == 0

def test_trim_history():
    messages = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "Old message 1 " * 20},      # ~84 tokens
        {"role": "assistant", "content": "Old reply 1 " * 20},     # ~84 tokens
        {"role": "user", "content": "Mid message 2 " * 20},      # ~84 tokens
        {"role": "assistant", "content": "Mid reply 2 " * 20},     # ~84 tokens
        {"role": "user", "content": "Recent question here"}       # ~10 tokens
    ]

    # Total tokens is ~350+. If max_tokens is 120:
    # System message (~8 tokens) + recent question (~10 tokens) = 18 tokens.
    # Mid reply 2 (~84 tokens) brings it to ~102 tokens.
    # Adding Mid message 2 would exceed 120, so older messages must be excluded!
    trimmed = trim_history(messages, max_tokens=120)

    # 1. System message preserved
    assert trimmed[0]["role"] == "system"
    assert trimmed[0]["content"] == "You are HINAKU."

    # 2. Latest message preserved
    assert trimmed[-1]["content"] == "Recent question here"

    # 3. Oldest messages excluded
    contents = [m["content"] for m in trimmed]
    assert "Old message 1 " * 20 not in contents

    # 4. Chronological order preserved
    if len(trimmed) > 2:
        assert trimmed[1]["content"] == "Mid reply 2 " * 20

def test_conversations_api_lifecycle():
    # 1. Create
    res = client.post("/api/conversations", json={"title": "Test Chat API"})
    assert res.status_code == 200
    conv = res.json()
    cid = conv["id"]
    assert conv["title"] == "Test Chat API"

    # 2. List
    res = client.get("/api/conversations")
    assert res.status_code == 200
    ids = [c["id"] for c in res.json()]
    assert cid in ids

    # 3. Get
    res = client.get(f"/api/conversations/{cid}")
    assert res.status_code == 200
    assert res.json()["title"] == "Test Chat API"
    assert res.json()["messages"] == []

    # 4. Rename
    res = client.patch(f"/api/conversations/{cid}", json={"title": "Updated API Title"})
    assert res.status_code == 200
    assert res.json()["title"] == "Updated API Title"

    # 5. Delete
    res = client.delete(f"/api/conversations/{cid}")
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"

    # 6. Verify 404 after delete
    res = client.get(f"/api/conversations/{cid}")
    assert res.status_code == 404

def test_chat_endpoint_stores_history(monkeypatch):
    import backend.api.chat as chat_module

    async def fake_stream_chat(messages, model=None, options=None, think=None):
        yield "Saved response chunk"

    monkeypatch.setattr(chat_module.adapter, "stream_chat", fake_stream_chat)

    # Create new conversation via chat
    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "Persistent query"}],
        "stream": False
    })
    assert res.status_code == 200
    data = res.json()
    cid = data["conversation_id"]
    assert cid is not None

    # Verify conversation and messages stored in history manager
    conv = chat_module.history_manager.get_conversation(cid)
    assert conv is not None
    assert len(conv["messages"]) >= 2
    roles = [m["role"] for m in conv["messages"]]
    assert "user" in roles
    assert "assistant" in roles
