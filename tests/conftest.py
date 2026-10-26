import hashlib
import os
import sys
from pathlib import Path
import pytest

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

REAL_DB_PATH = root_dir / "data" / "hinaku.db"
REAL_DATA_DIR = root_dir / "data"

def get_data_dir_snapshot(data_dir: Path):
    snapshot = {}
    if not data_dir.exists():
        return snapshot
    for p in data_dir.rglob("*"):
        if p.is_file():
            try:
                stat = p.stat()
                snapshot[str(p.relative_to(data_dir))] = {
                    "size": stat.st_size,
                    "mtime": stat.st_mtime_ns
                }
            except Exception:
                pass
    return snapshot

INITIAL_DATA_SNAPSHOT = get_data_dir_snapshot(REAL_DATA_DIR)

def get_file_hash(path: Path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

INITIAL_DB_EXISTS = REAL_DB_PATH.exists()
INITIAL_DB_HASH = get_file_hash(REAL_DB_PATH)

@pytest.fixture(scope="session", autouse=True)
def verify_data_dir_untouched_at_session_end():
    yield
    final_snapshot = get_data_dir_snapshot(REAL_DATA_DIR)
    initial_files = set(INITIAL_DATA_SNAPSHOT.keys())
    final_files = set(final_snapshot.keys())
    new_files = final_files - initial_files
    assert not new_files, f"Test suite created files in real data/ directory: {new_files}"

@pytest.fixture(autouse=True)
def isolate_test_database(request, tmp_path, monkeypatch):
    """
    Guarantees every test runs against a temporary SQLite database
    and never modifies data/hinaku.db.
    """
    test_db = tmp_path / "test_isolated.db"
    test_chroma = tmp_path / "test_chroma"
    test_datasets = tmp_path / "test_datasets"
    test_models = tmp_path / "test_models"
    monkeypatch.setenv("HINAKU_DB_PATH", str(test_db))
    monkeypatch.setenv("HINAKU_CHROMA_PATH", str(test_chroma))
    monkeypatch.setenv("HINAKU_DATASETS_DIR", str(test_datasets))
    monkeypatch.setenv("HINAKU_MODELS_DIR", str(test_models))

    import backend.config as cfg
    cfg._settings_instance = None
    monkeypatch.setattr(cfg.Settings, "sqlite_path", property(lambda self: test_db))
    monkeypatch.setattr(cfg.Settings, "chroma_path", property(lambda self: test_chroma))
    monkeypatch.setattr(cfg.Settings, "datasets_dir", property(lambda self: test_datasets))
    monkeypatch.setattr(cfg.Settings, "models_dir", property(lambda self: test_models))

    from backend.history import ChatHistoryManager
    test_manager = ChatHistoryManager(test_db)

    import backend.api.chat as chat_module
    monkeypatch.setattr(chat_module, "history_manager", test_manager)

    import backend.api.conversations as conv_module
    monkeypatch.setattr(conv_module, "history_manager", test_manager)

    import backend.api.interactions as interactions_module
    monkeypatch.setattr(interactions_module, "get_history_mgr", lambda: test_manager)

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

    # Isolate attachment storage and manager
    from backend.attachments import AttachmentStorage, AttachmentManager
    test_uploads = tmp_path / "test_uploads"
    test_att_storage = AttachmentStorage(
        db_path=test_db,
        uploads_dir=test_uploads,
        chroma_dir=test_chroma / "attachments",
        embed_fn=lambda texts: [[0.1] * 128 for _ in texts]
    )
    test_att_manager = AttachmentManager(storage=test_att_storage)
    import backend.api.attachments as att_module
    monkeypatch.setattr(att_module, "attachment_manager", test_att_manager)

    if "prewarm" not in request.node.name:
        import backend.models.prewarm as prewarm_mod
        async def _mock_prewarm():
            return
        monkeypatch.setattr(prewarm_mod, "prewarm_local_models", _mock_prewarm)

    yield test_manager
    try:
        from chromadb.api.shared_system_client import SharedSystemClient
        SharedSystemClient.clear()
    except Exception:
        pass
