from fastapi.testclient import TestClient
from backend.main import app
from tests.conftest import REAL_DB_PATH, INITIAL_DB_EXISTS, INITIAL_DB_HASH, get_file_hash

client = TestClient(app)

def test_database_isolation_preserves_real_db():
    # Perform database-heavy operations via API
    res = client.post("/api/conversations", json={"title": "Test Isolation Conv"})
    assert res.status_code == 200
    cid = res.json()["id"]

    res_chat = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "Checking isolation"}],
        "conversation_id": cid,
        "stream": False
    })
    assert res_chat.status_code == 200

    # Verify that the real database data/hinaku.db was never touched or modified
    assert REAL_DB_PATH.exists() == INITIAL_DB_EXISTS, "Real database existence status changed!"
    current_hash = get_file_hash(REAL_DB_PATH)
    assert current_hash == INITIAL_DB_HASH, "Real database data/hinaku.db was modified during test run!"

