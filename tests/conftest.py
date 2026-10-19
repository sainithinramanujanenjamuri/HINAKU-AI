import hashlib
import os
import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

REAL_DB_PATH = root_dir / "data" / "hinaku.db"

def get_file_hash(path: Path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

INITIAL_DB_EXISTS = REAL_DB_PATH.exists()
INITIAL_DB_HASH = get_file_hash(REAL_DB_PATH)

@pytest.fixture(autouse=True)
def isolate_test_database(tmp_path, monkeypatch):
    """
    Guarantees every test runs against a temporary SQLite database
    and never modifies data/hinaku.db.
    """
    test_db = tmp_path / "test_isolated.db"
    monkeypatch.setenv("HINAKU_DB_PATH", str(test_db))

    import backend.config as cfg
    monkeypatch.setattr(cfg.Settings, "sqlite_path", property(lambda self: test_db))

    from backend.history import ChatHistoryManager
    test_manager = ChatHistoryManager(test_db)

    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module, "history_manager", test_manager)

    import backend.api.conversations as conv_module
    monkeypatch.setattr(conv_module, "history_manager", test_manager)

    yield test_manager
