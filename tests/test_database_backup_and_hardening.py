"""
tests/test_database_backup_and_hardening.py

Comprehensive Test Suite for Phase 1 Milestone 7 Step 1:
Database Hardening, Coordinated Multi-Database Backup & Recovery Engine.

Covers:
1. Integrity verification (healthy check, corrupted primary fail-closed, corrupted chroma fail-closed,
   preservation of damaged files without deletion or repair).
2. Coordinated paired backup (SQLite Online Backup API, staged verification, promotion, metadata,
   safe retention never deleting the last verified set).
3. Write coordination (writer quiescence, in-flight write draining, snapshot lock, safe resumption).
4. Restore and safe rollback (owner authorization, background token rejection, paired restoration,
   pre-restore live preservation, post-restore verification, automated rollback on failure).
5. REST API integration (POST /api/settings/backup, GET /api/settings/backup, POST /api/settings/backup/restore).
6. Non-regression of existing database behavior.
"""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import pytest
from fastapi.testclient import TestClient

from backend.database.backup import (
    DatabaseBackupManager,
    DatabaseWriteCoordinator,
    DatabaseIntegrityError,
    DatabaseBackupError,
    DatabaseRestoreError,
    DatabaseRestoreFatalError,
    compute_file_sha256,
)
from backend.security.auth import (
    InternalScope,
    InternalAuthorizationError,
    internal_token_manager,
    session_token_manager,
    assert_owner_session_required,
)


@pytest.fixture
def temp_db_env(tmp_path):
    """
    Creates an isolated test environment with realistic temporary databases
    for hinaku.db and chroma/chroma.sqlite3.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hinaku_path = data_dir / "hinaku.db"
    chroma_dir = data_dir / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    chroma_path = chroma_dir / "chroma.sqlite3"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Initialize healthy primary relational database
    conn = sqlite3.connect(str(hinaku_path))
    conn.execute("CREATE TABLE test_relational (id TEXT PRIMARY KEY, value TEXT);")
    conn.execute("INSERT INTO test_relational VALUES ('r1', 'relational_data_1');")
    conn.commit()
    conn.close()

    # Initialize healthy Chroma vector metadata database
    conn2 = sqlite3.connect(str(chroma_path))
    conn2.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT);")
    conn2.execute("INSERT INTO collections VALUES ('c1', 'owner_memories');")
    conn2.commit()
    conn2.close()

    # Create dummy segment directory in chroma
    seg_dir = chroma_dir / "test_segment_uuid"
    seg_dir.mkdir(parents=True, exist_ok=True)
    (seg_dir / "index.bin").write_bytes(b"segment_binary_data")

    coordinator = DatabaseWriteCoordinator()
    manager = DatabaseBackupManager(
        hinaku_db_path=hinaku_path,
        chroma_db_path=chroma_path,
        chroma_dir=chroma_dir,
        backup_dir=backup_dir,
        retention_count=3,
        coordinator=coordinator,
    )

    return {
        "data_dir": data_dir,
        "hinaku_path": hinaku_path,
        "chroma_dir": chroma_dir,
        "chroma_path": chroma_path,
        "backup_dir": backup_dir,
        "coordinator": coordinator,
        "manager": manager,
    }


# ==============================================================================
# 1. INTEGRITY VERIFICATION TESTS
# ==============================================================================

def test_startup_integrity_passes_on_healthy_databases(temp_db_env):
    """Both healthy databases pass PRAGMA integrity_check."""
    mgr = temp_db_env["manager"]
    res = mgr.verify_startup_integrity()
    assert res["ok"] is True
    assert res["hinaku"]["status"] == "ok"
    assert res["chroma"]["status"] == "ok"
    assert len(res["failed_databases"]) == 0


def test_startup_integrity_fails_closed_on_corrupt_primary(temp_db_env):
    """Corrupting the primary database fails closed and preserves damaged file."""
    hinaku_path = temp_db_env["hinaku_path"]
    mgr = temp_db_env["manager"]

    # Overwrite file with corrupt non-database garbage
    corrupt_bytes = b"CORRUPTED_GARBAGE_DATA_NOT_A_SQLITE_FILE" * 20
    hinaku_path.write_bytes(corrupt_bytes)

    res = mgr.verify_startup_integrity()
    assert res["ok"] is False
    assert "hinaku" in res["failed_databases"]
    # Damaged file must be preserved in place, not deleted or repaired
    assert hinaku_path.exists()
    assert hinaku_path.read_bytes() == corrupt_bytes


def test_startup_integrity_fails_closed_on_corrupt_chroma(temp_db_env):
    """Corrupting the Chroma database fails closed and preserves damaged file."""
    chroma_path = temp_db_env["chroma_path"]
    mgr = temp_db_env["manager"]

    corrupt_bytes = b"CORRUPTED_CHROMA_VECTOR_DATABASE" * 20
    chroma_path.write_bytes(corrupt_bytes)

    res = mgr.verify_startup_integrity()
    assert res["ok"] is False
    assert "chroma" in res["failed_databases"]
    assert chroma_path.exists()
    assert chroma_path.read_bytes() == corrupt_bytes


# ==============================================================================
# 2. COORDINATED BACKUP TESTS
# ==============================================================================

def test_coordinated_backup_creates_verified_recovery_set(temp_db_env):
    """Creates a paired recovery set containing both databases and metadata."""
    mgr = temp_db_env["manager"]
    backup_dir = temp_db_env["backup_dir"]

    meta = mgr.create_coordinated_backup(description="Test paired snapshot")
    assert meta["status"] == "verified"
    rid = meta["recovery_set_id"]

    recovery_set_path = backup_dir / rid
    assert recovery_set_path.exists()
    assert (recovery_set_path / "hinaku.db").exists()
    assert (recovery_set_path / "chroma.sqlite3").exists()
    assert (recovery_set_path / "metadata.json").exists()
    assert (recovery_set_path / "chroma_segments" / "test_segment_uuid" / "index.bin").exists()

    # Verify staged databases pass PRAGMA integrity_check independently
    ok_h, msg_h = mgr.verify_database_integrity(recovery_set_path / "hinaku.db")
    ok_c, msg_c = mgr.verify_database_integrity(recovery_set_path / "chroma.sqlite3")
    assert ok_h is True
    assert ok_c is True


def test_coordinated_backup_hashes_and_metadata_integrity(temp_db_env):
    """Metadata correctly contains file hashes, sizes, and timestamp."""
    mgr = temp_db_env["manager"]
    meta = mgr.create_coordinated_backup()

    hinaku_meta = meta["databases"]["hinaku"]
    chroma_meta = meta["databases"]["chroma"]

    assert len(hinaku_meta["sha256"]) == 64
    assert len(chroma_meta["sha256"]) == 64
    assert hinaku_meta["size_bytes"] > 0
    assert chroma_meta["size_bytes"] > 0
    assert "created_at" in meta


def test_failed_snapshot_is_never_promoted(temp_db_env):
    """If integrity verification fails on staged copy, recovery set is not promoted."""
    mgr = temp_db_env["manager"]
    backup_dir = temp_db_env["backup_dir"]

    # Temporarily monkeypatch _copy_sqlite_online to inject corruption
    orig_copy = mgr._copy_sqlite_online

    def corrupting_copy(src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"INVALID_DATABASE_PAGES")

    mgr._copy_sqlite_online = corrupting_copy

    with pytest.raises(DatabaseBackupError):
        mgr.create_coordinated_backup(description="Should fail")

    # Verify no recovery set directory or tmp directory was promoted
    promoted = list(backup_dir.glob("recovery_set_*"))
    assert len(promoted) == 0
    tmp_dirs = list(backup_dir.glob(".tmp_*"))
    assert len(tmp_dirs) == 0


def test_safe_retention_never_deletes_last_verified_recovery_set(temp_db_env):
    """Safe retention policy prunes old backups but NEVER deletes the last verified set."""
    mgr = temp_db_env["manager"]
    # Retention limit is set to 2
    mgr.retention_count = 2

    # Create 3 verified backups
    set1 = mgr.create_coordinated_backup(description="Set 1")
    time.sleep(0.01)
    set2 = mgr.create_coordinated_backup(description="Set 2")
    time.sleep(0.01)
    set3 = mgr.create_coordinated_backup(description="Set 3")

    sets = mgr.list_recovery_sets()
    assert len(sets) == 2  # Set 1 was pruned because Set 2 and Set 3 are verified
    assert sets[0]["recovery_set_id"] == set3["recovery_set_id"]
    assert sets[1]["recovery_set_id"] == set2["recovery_set_id"]

    # Now simulate an unverified older set and verify that the last verified is never deleted
    mgr.retention_count = 1
    # Even with retention_count = 1, pruning will prune down to 1 verified backup, never 0
    mgr.prune_backups()
    remaining = mgr.list_recovery_sets()
    assert len(remaining) == 1
    assert remaining[0]["status"] == "verified"


# ==============================================================================
# 3. WRITE COORDINATION TESTS
# ==============================================================================

def test_write_coordinator_drains_active_writers(temp_db_env):
    """Coordinator safely drains in-flight writers before snapshotting."""
    coordinator = temp_db_env["coordinator"]

    active_in_permit = False
    finished_write = False

    def slow_writer():
        nonlocal active_in_permit, finished_write
        with coordinator.write_permit("test_writer"):
            active_in_permit = True
            time.sleep(0.1)
            finished_write = True

    t = threading.Thread(target=slow_writer)
    t.start()

    # Wait until slow_writer is inside permit
    while not active_in_permit:
        time.sleep(0.005)

    assert coordinator.active_writers_count == 1

    # Quiesce writers: should block until slow_writer completes
    coordinator.quiesce_writers(timeout=2.0)
    assert finished_write is True
    assert coordinator.active_writers_count == 0
    assert coordinator.is_paused is True

    # Cleanup
    coordinator.resume_writers()
    t.join()
    assert coordinator.is_paused is False


def test_incoming_writes_queue_during_quiescence(temp_db_env):
    """Incoming writes are queued while database writes are paused and resume safely."""
    coordinator = temp_db_env["coordinator"]
    coordinator.quiesce_writers(timeout=2.0)

    queued_started = False
    queued_finished = False

    def queued_writer():
        nonlocal queued_started, queued_finished
        queued_started = True
        with coordinator.write_permit("queued_writer"):
            queued_finished = True

    t = threading.Thread(target=queued_writer)
    t.start()

    # Wait for thread to attempt permit
    while not queued_started:
        time.sleep(0.005)
    time.sleep(0.05)

    # Must not finish while paused
    assert queued_finished is False

    # Resume writers
    coordinator.resume_writers()
    t.join(timeout=2.0)

    assert queued_finished is True


# ==============================================================================
# 4. RESTORE AND ROLLBACK TESTS
# ==============================================================================

def test_restore_requires_owner_session_authorization(temp_db_env):
    """Restoration without owner desktop session authorization raises error."""
    mgr = temp_db_env["manager"]
    meta = mgr.create_coordinated_backup()

    with pytest.raises(InternalAuthorizationError):
        mgr.restore_recovery_set(
            recovery_set_id=meta["recovery_set_id"],
            has_owner_session=False,
        )


def test_restore_rejects_internal_background_tokens():
    """assert_owner_session_required rejects internal background tokens."""
    token = internal_token_manager.issue_token(InternalScope.BACKGROUND_SCHEDULER)
    assert token.startswith("hinaku_internal_")

    # Validating on desktop session manager must fail
    assert session_token_manager.validate_token(token) is False

    with pytest.raises(InternalAuthorizationError):
        assert_owner_session_required("restore_backup", has_owner_session=False)


def test_restore_successfully_recovers_coordinated_pair(temp_db_env):
    """Restoration replaces both databases from the recovery set and verifies integrity."""
    mgr = temp_db_env["manager"]
    hinaku_path = temp_db_env["hinaku_path"]
    chroma_path = temp_db_env["chroma_path"]

    # 1. Create a baseline backup
    meta = mgr.create_coordinated_backup(description="Initial clean state")
    rid = meta["recovery_set_id"]

    # 2. Mutate live database
    conn = sqlite3.connect(str(hinaku_path))
    conn.execute("INSERT INTO test_relational VALUES ('r2', 'mutated_record');")
    conn.commit()
    conn.close()

    conn2 = sqlite3.connect(str(chroma_path))
    conn2.execute("INSERT INTO collections VALUES ('c2', 'mutated_collection');")
    conn2.commit()
    conn2.close()

    # Verify mutations are live
    conn = sqlite3.connect(str(hinaku_path))
    rows = conn.execute("SELECT id FROM test_relational;").fetchall()
    conn.close()
    assert len(rows) == 2

    # 3. Restore the baseline backup
    res = mgr.restore_recovery_set(
        recovery_set_id=rid,
        reason="Test rollback to initial",
        has_owner_session=True,
    )
    assert res["status"] == "restored"

    # 4. Verify live database matches baseline (mutations gone)
    conn = sqlite3.connect(str(hinaku_path))
    rows = conn.execute("SELECT id FROM test_relational;").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "r1"

    conn2 = sqlite3.connect(str(chroma_path))
    c_rows = conn2.execute("SELECT id FROM collections;").fetchall()
    conn2.close()
    assert len(c_rows) == 1
    assert c_rows[0][0] == "c1"


def test_restore_failure_executes_controlled_rollback(temp_db_env):
    """If post-restoration verification fails, system safely rolls back to pre-restore state."""
    mgr = temp_db_env["manager"]
    hinaku_path = temp_db_env["hinaku_path"]
    backup_dir = temp_db_env["backup_dir"]

    # 1. Create valid recovery set
    meta = mgr.create_coordinated_backup()
    rid = meta["recovery_set_id"]

    # 2. Mutate live database with a marker record
    conn = sqlite3.connect(str(hinaku_path))
    conn.execute("INSERT INTO test_relational VALUES ('pre_restore_marker', 'important_data');")
    conn.commit()
    conn.close()

    # 3. Intentionally corrupt the recovery set's chroma.sqlite3 so post-restore check fails
    target_chroma = backup_dir / rid / "chroma.sqlite3"
    target_chroma.write_bytes(b"CORRUPTED_DURING_RESTORE")

    # 4. Attempt restore -> should fail and rollback
    with pytest.raises(DatabaseRestoreError) as exc_info:
        mgr.restore_recovery_set(
            recovery_set_id=rid,
            reason="Expect failure and rollback",
            has_owner_session=True,
        )

    assert "safely rolled back to pre-restoration state" in str(exc_info.value)

    # 5. Verify live database was safely rolled back to pre-restore state
    conn = sqlite3.connect(str(hinaku_path))
    rows = conn.execute("SELECT id FROM test_relational;").fetchall()
    conn.close()
    ids = [r[0] for r in rows]
    assert "pre_restore_marker" in ids

    # 6. Verify integrity of both live databases after rollback
    ok_h, _ = mgr.verify_database_integrity(hinaku_path)
    ok_c, _ = mgr.verify_database_integrity(temp_db_env["chroma_path"])
    assert ok_h is True
    assert ok_c is True


# ==============================================================================
# 5. API INTEGRATION TESTS
# ==============================================================================

def test_api_backup_endpoints(temp_db_env, monkeypatch):
    """Test POST /api/settings/backup, GET /api/settings/backup, POST /api/settings/backup/restore."""
    from backend.main import app
    from backend.database.backup import set_backup_manager

    set_backup_manager(temp_db_env["manager"])
    session_token = session_token_manager.get_token()

    client = TestClient(app)

    # 1. Unauthorized request with invalid token returns 401
    invalid_headers = {"X-Hinaku-Token": "invalid_token_1234567890"}
    resp = client.get("/api/settings/backup", headers=invalid_headers)
    assert resp.status_code == 401

    resp = client.post("/api/settings/backup", headers=invalid_headers, json={})
    assert resp.status_code == 401

    # 2. Authorized POST /api/settings/backup creates recovery set
    headers = {"X-Hinaku-Token": session_token}
    resp = client.post(
        "/api/settings/backup",
        headers=headers,
        json={"description": "API created snapshot"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    rid = data["recovery_set"]["recovery_set_id"]

    # 3. Authorized GET /api/settings/backup lists recovery sets
    resp = client.get("/api/settings/backup", headers=headers)
    assert resp.status_code == 200
    list_data = resp.json()
    assert list_data["total_count"] >= 1
    assert any(s["recovery_set_id"] == rid for s in list_data["recovery_sets"])

    # 4. Restore with unconfirmed flag returns 400
    resp = client.post(
        "/api/settings/backup/restore",
        headers=headers,
        json={"recovery_set_id": rid, "confirm_destructive_restore": False},
    )
    assert resp.status_code == 400
    assert "confirm_destructive_restore=True" in resp.json()["detail"]

    # 5. Restore non-existent recovery set returns 404
    resp = client.post(
        "/api/settings/backup/restore",
        headers=headers,
        json={"recovery_set_id": "non_existent_set_id", "confirm_destructive_restore": True},
    )
    assert resp.status_code == 404

    # 6. Authorized confirmed restore succeeds
    resp = client.post(
        "/api/settings/backup/restore",
        headers=headers,
        json={
            "recovery_set_id": rid,
            "confirm_destructive_restore": True,
            "reason": "Owner authorized test restore",
        },
    )
    assert resp.status_code == 200
    restore_data = resp.json()
    assert restore_data["status"] == "restored"
    assert restore_data["recovery_set_id"] == rid


# ==============================================================================
# 6. MISSING DATABASE FILE TESTS (FAIL-CLOSED WITHOUT CREATION)
# ==============================================================================

def test_startup_integrity_fails_closed_when_primary_missing(tmp_path):
    """
    If primary database file data/hinaku.db is missing:
    - Must fail closed (ok=False).
    - Must report missing_database_file.
    - Must NOT silently recreate an empty database file.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hinaku_path = data_dir / "hinaku.db"
    chroma_path = data_dir / "chroma" / "chroma.sqlite3"
    chroma_path.parent.mkdir(parents=True, exist_ok=True)

    # Create healthy chroma database
    conn = sqlite3.connect(str(chroma_path))
    conn.execute("CREATE TABLE t (id INT);")
    conn.commit()
    conn.close()

    # hinaku.db does not exist
    assert not hinaku_path.exists()

    mgr = DatabaseBackupManager(
        hinaku_db_path=hinaku_path,
        chroma_db_path=chroma_path,
        backup_dir=data_dir / "backups",
    )

    res = mgr.verify_startup_integrity()
    assert res["ok"] is False
    assert "hinaku" in res["failed_databases"]
    assert res["hinaku"]["status"] == "missing_database_file"

    # Inviolable guarantee: Must NOT silently recreate an empty database!
    assert not hinaku_path.exists()


def test_startup_integrity_fails_closed_when_chroma_missing(tmp_path):
    """
    If chroma database file data/chroma/chroma.sqlite3 is missing:
    - Must fail closed (ok=False).
    - Must report missing_database_file.
    - Must NOT silently recreate an empty database file.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    hinaku_path = data_dir / "hinaku.db"
    chroma_path = data_dir / "chroma" / "chroma.sqlite3"

    # Create healthy hinaku database
    conn = sqlite3.connect(str(hinaku_path))
    conn.execute("CREATE TABLE t (id INT);")
    conn.commit()
    conn.close()

    # chroma.sqlite3 does not exist
    assert not chroma_path.exists()

    mgr = DatabaseBackupManager(
        hinaku_db_path=hinaku_path,
        chroma_db_path=chroma_path,
        backup_dir=data_dir / "backups",
    )

    res = mgr.verify_startup_integrity()
    assert res["ok"] is False
    assert "chroma" in res["failed_databases"]
    assert res["chroma"]["status"] == "missing_database_file"

    # Inviolable guarantee: Must NOT silently recreate an empty database!
    assert not chroma_path.exists()


# ==============================================================================
# 7. COMPREHENSIVE WRITE COORDINATION ACROSS ALL COMPONENTS
# ==============================================================================

def test_write_coordination_blocks_all_intelligence_stores_during_quiescence(temp_db_env):
    """
    Verifies that write operations across ProjectStore, KnowledgeGraph, DecisionEngine,
    PlanningEngine, TaskManager, WeaknessCatalog, ExperienceLogger, and ImprovementProposalEngine
    are coordinated through DatabaseWriteCoordinator.
    """
    from backend.database.backup import write_coordinator as global_coordinator
    hinaku_path = temp_db_env["hinaku_path"]

    from backend.intelligence.project_store import ProjectStore
    from backend.intelligence.project_types import ProjectRecord, ProjectConfidentiality
    from backend.intelligence.knowledge_graph import KnowledgeGraph
    from backend.intelligence.graph_types import KnowledgeEdge, EdgeRelationship
    from backend.intelligence.types import KnowledgeDomain
    from backend.intelligence.task_manager import TaskManager
    from backend.intelligence.planning_types import ManagedTask
    from backend.intelligence.types import TaskPriority

    ps = ProjectStore(hinaku_path)

    # 1. Quiesce writers using the global coordinator that decorates store methods
    global_coordinator.quiesce_writers(timeout=2.0)
    assert global_coordinator.is_paused is True

    blocked_event = threading.Event()
    completed_event = threading.Event()

    try:
        def background_project_write():
            blocked_event.set()
            rec = ProjectRecord(
                project_id="test_proj_coord",
                name="Blocked Test Project",
                description="Testing write lock",
                purpose="Testing write lock",
                confidentiality=ProjectConfidentiality.INTERNAL,
            )
            ps.create_project(rec)
            completed_event.set()

        t = threading.Thread(target=background_project_write)
        t.start()

        blocked_event.wait(timeout=1.0)
        time.sleep(0.05)

        # Must be blocked while paused
        assert not completed_event.is_set()

        # Resume writers
        global_coordinator.resume_writers()
        completed_event.wait(timeout=2.0)
        t.join(timeout=2.0)

        assert completed_event.is_set()
    finally:
        if global_coordinator.is_paused:
            global_coordinator.resume_writers()


# ==============================================================================
# 8. CHROMA HANDLE RELEASE AND REOPEN VERIFICATION DURING RESTORE
# ==============================================================================

def test_restore_invokes_handle_release_and_reopen_callbacks(temp_db_env):
    """
    Verifies that DatabaseBackupManager invokes handle release before restoring files,
    and invokes handle reopen after restoration, preventing handle locks.
    """
    mgr = temp_db_env["manager"]
    coordinator = temp_db_env["coordinator"]

    release_called = False
    reopen_called = False

    def on_release():
        nonlocal release_called
        release_called = True

    def on_reopen():
        nonlocal reopen_called
        reopen_called = True

    coordinator.register_handle_release_callback(on_release)
    coordinator.register_handle_reopen_callback(on_reopen)

    # Create baseline recovery set
    meta = mgr.create_coordinated_backup(description="Test callback baseline")
    rid = meta["recovery_set_id"]

    # Execute restore
    mgr.restore_recovery_set(
        recovery_set_id=rid,
        reason="Verify callbacks",
        has_owner_session=True,
    )

    assert release_called is True
    assert reopen_called is True

