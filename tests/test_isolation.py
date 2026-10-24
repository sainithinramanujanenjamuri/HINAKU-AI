from fastapi.testclient import TestClient
from backend.main import app
from tests.conftest import REAL_DB_PATH, INITIAL_DB_EXISTS, INITIAL_DB_HASH, get_file_hash, REAL_DATA_DIR, INITIAL_DATA_SNAPSHOT, get_data_dir_snapshot

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

    # Verify that the real Chroma path data/chroma was not created by tests
    real_chroma = REAL_DB_PATH.parent / "chroma"
    if not INITIAL_DB_EXISTS:
        assert not real_chroma.exists() or len(list(real_chroma.iterdir())) == 0



def test_no_test_touches_or_modifies_data_directory():
    # Fails if any test touched, added, or modified files in the real data/ directory
    current_snapshot = get_data_dir_snapshot(REAL_DATA_DIR)
    initial_files = set(INITIAL_DATA_SNAPSHOT.keys())
    current_files = set(current_snapshot.keys())

    new_files = current_files - initial_files
    deleted_files = initial_files - current_files

    assert not new_files, f"Test suite created files in real data/ directory: {new_files}"
    assert not deleted_files, f"Test suite deleted files in real data/ directory: {deleted_files}"

    modified_files = []
    for f in initial_files & current_files:
        if (current_snapshot[f]["size"] != INITIAL_DATA_SNAPSHOT[f]["size"] or
            current_snapshot[f]["mtime"] != INITIAL_DATA_SNAPSHOT[f]["mtime"]):
            modified_files.append(f)

    assert not modified_files, f"Test suite modified files in real data/ directory: {modified_files}"
