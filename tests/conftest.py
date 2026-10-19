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
    test_chroma = tmp_path / "test_chroma"
    monkeypatch.setenv("HINAKU_DB_PATH", str(test_db))
    monkeypatch.setenv("HINAKU_CHROMA_PATH", str(test_chroma))

    import backend.config as cfg
    monkeypatch.setattr(cfg.Settings, "sqlite_path", property(lambda self: test_db))
    monkeypatch.setattr(cfg.Settings, "chroma_path", property(lambda self: test_chroma))

    from backend.history import ChatHistoryManager
    test_manager = ChatHistoryManager(test_db)

    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module, "history_manager", test_manager)

    import backend.api.conversations as conv_module
    monkeypatch.setattr(conv_module, "history_manager", test_manager)

    from backend.memory import MemoryStorage, MemoryExtractor, MemoryManager
    test_memory_storage = MemoryStorage(
        db_path=test_db,
        chroma_path=test_chroma,
        embedding_model=cfg.get_settings().memory_embedding_model,
        embedding_dims=cfg.get_settings().memory_embedding_dims,
        query_prefix=cfg.get_settings().memory_query_prefix,
        document_prefix=cfg.get_settings().memory_document_prefix,
        ollama_host=cfg.get_settings().local_host
    )
    test_memory_extractor = MemoryExtractor(
        local_adapter=chat_module.local_adapter,
        storage=test_memory_storage,
        never_store_categories=cfg.get_settings().memory_never_store,
        merge_threshold=cfg.get_settings().memory_merge_threshold
    )
    test_memory_manager = MemoryManager(
        storage=test_memory_storage,
        extractor=test_memory_extractor,
        enabled=cfg.get_settings().memory_enabled,
        learn_from_private_chats=cfg.get_settings().memory_learn_from_private_chats,
        retrieve_top_k=cfg.get_settings().memory_retrieve_top_k,
        min_similarity=cfg.get_settings().memory_min_similarity
    )
    monkeypatch.setattr(chat_module, "memory_storage", test_memory_storage)
    monkeypatch.setattr(chat_module, "memory_extractor", test_memory_extractor)
    monkeypatch.setattr(chat_module, "memory_manager", test_memory_manager)

    yield test_manager
