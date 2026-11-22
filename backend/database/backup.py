"""
backend/database/backup.py

Coordinated Multi-Database Integrity, Backup, and Recovery Engine for HINAKU.

Manages persistent state across HINAKU's two SQLite databases:
1. Primary Relational Store: `data/hinaku.db`
2. Vector Index Metadata Store: `data/chroma/chroma.sqlite3` (plus HNSW segment indices)

Core Capabilities:
1. Multi-path write coordination: drains and pauses all active writers across both databases.
2. Dual-database integrity checking (`PRAGMA integrity_check;`) on startup (fail-closed).
3. Coordinated recovery sets using the official SQLite Online Backup API (`sqlite3.Connection.backup()`).
4. Staged snapshots (.tmp) with dual independent verification before atomic promotion.
5. Safe retention pruning: never deletes the last verified known-good recovery set.
6. Safe restore & rollback: preserves live state, restores paired databases, runs post-restore
   integrity verification, and executes automated rollback if either database replacement fails.
"""

from contextlib import contextmanager, asynccontextmanager
import datetime
from datetime import timezone
import functools
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.config import get_settings
from backend.security.auth import assert_owner_session_required

logger = logging.getLogger("hinaku.database.backup")


class DatabaseIntegrityError(Exception):
    """Raised when an integrity check fails on one or more databases."""
    pass


class DatabaseBackupError(Exception):
    """Raised when backup creation or staging fails."""
    pass


class DatabaseRestoreError(Exception):
    """Raised when restoration fails and a safe rollback was executed."""
    pass


class DatabaseRestoreFatalError(Exception):
    """Raised when restoration fails AND automated rollback also fails."""
    pass


class DatabaseWriteCoordinator:
    """
    Coordinates application write paths across relational and ChromaDB storage layers.
    Provides a global coordination mechanism to safely drain in-flight writes and pause
    incoming writes during the coordinated backup snapshot window or restoration.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._active_writers: int = 0
        self._paused: bool = False
        self._pause_callbacks: List[Callable[[], None]] = []
        self._resume_callbacks: List[Callable[[], None]] = []
        self._handle_release_callbacks: List[Callable[[], None]] = []
        self._handle_reopen_callbacks: List[Callable[[], None]] = []
        self._registered_writers: Set[str] = set()

    def register_writer_subsystem(self, name: str) -> None:
        """Register a known application write path or subsystem."""
        with self._lock:
            self._registered_writers.add(name)

    def register_pause_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to pause a background writer or scheduler."""
        with self._lock:
            self._pause_callbacks.append(callback)

    def register_resume_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to resume a background writer or scheduler."""
        with self._lock:
            self._resume_callbacks.append(callback)

    def register_handle_release_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to release database/Chroma handles before restore."""
        with self._lock:
            self._handle_release_callbacks.append(callback)

    def register_handle_reopen_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to re-initialize database/Chroma handles after restore."""
        with self._lock:
            self._handle_reopen_callbacks.append(callback)

    def release_all_handles(self) -> None:
        """Safely release and close all active database and Chroma client handles."""
        with self._lock:
            logger.info("DatabaseWriteCoordinator: releasing all active database and Chroma handles...")
            for cb in self._handle_release_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.warning(f"Error in handle release callback {cb}: {e}")

    def reopen_all_handles(self) -> None:
        """Re-initialize database and Chroma handles after restoration or maintenance."""
        with self._lock:
            logger.info("DatabaseWriteCoordinator: re-initializing database and Chroma handles...")
            for cb in self._handle_reopen_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.warning(f"Error in handle reopen callback {cb}: {e}")

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def active_writers_count(self) -> int:
        with self._lock:
            return self._active_writers

    @contextmanager
    def write_permit(self, subsystem: Optional[str] = None):
        """
        Synchronous context manager for database write operations.
        If write operations are currently paused (e.g., during snapshotting or restore),
        incoming writes are queued and wait until the pause is lifted.
        """
        with self._lock:
            while self._paused:
                self._cond.wait()
            self._active_writers += 1
            if subsystem:
                self._registered_writers.add(subsystem)

        try:
            yield
        finally:
            with self._lock:
                self._active_writers -= 1
                if self._active_writers == 0:
                    self._cond.notify_all()

    @asynccontextmanager
    async def async_write_permit(self, subsystem: Optional[str] = None):
        """
        Asynchronous context manager for async FastAPI endpoints performing writes.
        """
        # Acquire permit synchronously in thread-safe manner
        with self._lock:
            while self._paused:
                self._cond.wait()
            self._active_writers += 1
            if subsystem:
                self._registered_writers.add(subsystem)

        try:
            yield
        finally:
            with self._lock:
                self._active_writers -= 1
                if self._active_writers == 0:
                    self._cond.notify_all()

    def quiesce_writers(self, timeout: float = 10.0) -> None:
        """
        Pauses incoming writes and drains all active in-flight writes.
        Invokes registered pause callbacks on background subsystems.
        """
        with self._lock:
            self._paused = True
            logger.info("DatabaseWriteCoordinator: incoming writes paused. Draining in-flight writers...")
            start_time = time.time()
            while self._active_writers > 0:
                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    self._paused = False
                    self._cond.notify_all()
                    raise TimeoutError(
                        f"Timed out after {timeout:.1f}s waiting for {self._active_writers} active database writers to drain."
                    )
                self._cond.wait(timeout=remaining)

            # Invoke pause callbacks
            for cb in self._pause_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.warning(f"Error invoking pause callback {cb}: {e}")

            logger.info("DatabaseWriteCoordinator: all database writers successfully quiesced.")

    def resume_writers(self) -> None:
        """
        Resumes database write operations and notifies all queued writers.
        Invokes registered resume callbacks on background subsystems.
        """
        with self._lock:
            for cb in self._resume_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.warning(f"Error invoking resume callback {cb}: {e}")

            self._paused = False
            self._cond.notify_all()
            logger.info("DatabaseWriteCoordinator: database writes resumed.")


# Global singleton write coordinator
write_coordinator = DatabaseWriteCoordinator()


def get_write_coordinator() -> DatabaseWriteCoordinator:
    return write_coordinator


def coordinated_write(subsystem: str):
    """
    Decorator that acquires a write permit from DatabaseWriteCoordinator
    for the duration of the wrapped database-mutating method.
    If database writes are currently paused (e.g. during snapshotting or restore),
    execution waits safely on the condition variable.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with write_coordinator.write_permit(subsystem):
                return fn(*args, **kwargs)
        return wrapper
    return decorator


def compute_file_sha256(path: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


class DatabaseBackupManager:
    """
    Manages coordinated backups and recovery sets for HINAKU's SQLite databases:
    - Primary relational: data/hinaku.db
    - Chroma vector metadata: data/chroma/chroma.sqlite3
    """

    def __init__(
        self,
        hinaku_db_path: Optional[Path] = None,
        chroma_db_path: Optional[Path] = None,
        chroma_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        retention_count: int = 5,
        coordinator: Optional[DatabaseWriteCoordinator] = None,
    ):
        settings = get_settings()
        self.hinaku_db_path = Path(hinaku_db_path or settings.sqlite_path)

        if chroma_db_path:
            self.chroma_db_path = Path(chroma_db_path)
        else:
            self.chroma_db_path = Path(settings.chroma_path) / "chroma.sqlite3"

        if chroma_dir:
            self.chroma_dir = Path(chroma_dir)
        else:
            self.chroma_dir = Path(settings.chroma_path)

        env_backup = os.environ.get("HINAKU_BACKUP_DIR")
        if backup_dir:
            self.backup_dir = Path(backup_dir)
        elif env_backup:
            self.backup_dir = Path(env_backup)
        else:
            self.backup_dir = settings.data_dir / "backups"

        self.retention_count = max(1, retention_count)
        self.coordinator = coordinator or write_coordinator
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def verify_database_integrity(self, path: Path) -> Tuple[bool, str]:
        """
        Executes PRAGMA integrity_check; against a specific SQLite database file.
        Returns (True, 'ok') if healthy, (False, details) otherwise.
        """
        if not path.exists():
            return False, f"File does not exist: {path}"

        # Magic header check: SQLite database files must begin with the standard 16-byte magic header
        try:
            with open(path, "rb") as f:
                header = f.read(16)
                if header != b"SQLite format 3\x00":
                    return False, "File is not a valid SQLite database (invalid magic header)"
        except Exception as e:
            return False, f"Failed to read database header: {e}"

        try:
            conn = sqlite3.connect(str(path))
            try:
                cursor = conn.cursor()
                rows = cursor.execute("PRAGMA integrity_check;").fetchall()
                if not rows:
                    return False, "integrity_check returned no rows"
                if len(rows) == 1 and str(rows[0][0]).lower() == "ok":
                    return True, "ok"
                details = "; ".join(str(r[0]) for r in rows)
                return False, details
            finally:
                conn.close()
        except Exception as e:
            return False, f"Integrity check exception: {e}"

    def verify_startup_integrity(self) -> Dict[str, Any]:
        """
        Verifies both data/hinaku.db and data/chroma/chroma.sqlite3.
        Fail-closed: if either file is missing or corrupted, logs a critical error,
        preserves any damaged file untouched, and returns ok=False.
        Does NOT silently recreate missing files as empty databases.
        """
        results: Dict[str, Any] = {
            "ok": True,
            "hinaku": {"path": str(self.hinaku_db_path), "status": "unknown"},
            "chroma": {"path": str(self.chroma_db_path), "status": "unknown"},
            "failed_databases": [],
        }

        # 1. Primary Relational DB: check existence first (do NOT connect to non-existent file)
        if not self.hinaku_db_path.exists():
            results["ok"] = False
            results["failed_databases"].append("hinaku")
            results["hinaku"]["status"] = "missing_database_file"
            logger.critical(
                f"STARTUP INTEGRITY FAILED: Primary database file does not exist at {self.hinaku_db_path}. "
                "Fail-closed: will not silently recreate empty database."
            )
        else:
            h_ok, h_msg = self.verify_database_integrity(self.hinaku_db_path)
            results["hinaku"]["status"] = h_msg
            if not h_ok:
                results["ok"] = False
                results["failed_databases"].append("hinaku")
                logger.critical(
                    f"STARTUP INTEGRITY FAILED for primary database {self.hinaku_db_path}: {h_msg}. "
                    "File preserved in place; do not delete or overwrite."
                )

        # 2. Chroma Vector DB: check existence first (do NOT connect to non-existent file)
        if not self.chroma_db_path.exists():
            results["ok"] = False
            results["failed_databases"].append("chroma")
            results["chroma"]["status"] = "missing_database_file"
            logger.critical(
                f"STARTUP INTEGRITY FAILED: Chroma vector database file does not exist at {self.chroma_db_path}. "
                "Fail-closed: will not silently recreate empty database."
            )
        else:
            c_ok, c_msg = self.verify_database_integrity(self.chroma_db_path)
            results["chroma"]["status"] = c_msg
            if not c_ok:
                results["ok"] = False
                results["failed_databases"].append("chroma")
                logger.critical(
                    f"STARTUP INTEGRITY FAILED for chroma database {self.chroma_db_path}: {c_msg}. "
                    "File preserved in place; do not delete or overwrite."
                )

        return results

    def _copy_sqlite_online(self, src_path: Path, dst_path: Path) -> None:
        """
        Performs an online backup using sqlite3.Connection.backup().
        """
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        src_conn = sqlite3.connect(str(src_path))
        try:
            dst_conn = sqlite3.connect(str(dst_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

    def create_coordinated_backup(self, description: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a paired, coordinated recovery set of both databases:
        1. Quiesces in-flight writers via DatabaseWriteCoordinator.
        2. Snapshots both databases to staging directory (.tmp).
        3. Snapshots any Chroma vector segments.
        4. Runs PRAGMA integrity_check; on both staged databases.
        5. Atomically promotes to recovery_set_<timestamp> if both pass.
        6. Prunes older recovery sets while preserving the last known-good.
        7. Resumes writers in a finally block.
        """
        ts = datetime.datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        recovery_set_id = f"recovery_set_{ts}"
        staging_dir = self.backup_dir / f".tmp_{recovery_set_id}"
        promoted_dir = self.backup_dir / recovery_set_id

        # Quiesce writers across all application write paths
        self.coordinator.quiesce_writers(timeout=10.0)
        try:
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged_hinaku = staging_dir / "hinaku.db"
            staged_chroma = staging_dir / "chroma.sqlite3"

            # 1. Snapshot primary relational DB
            if not self.hinaku_db_path.exists():
                raise DatabaseBackupError(f"Primary database does not exist: {self.hinaku_db_path}")
            self._copy_sqlite_online(self.hinaku_db_path, staged_hinaku)

            # 2. Snapshot chroma vector DB
            if not self.chroma_db_path.exists():
                raise DatabaseBackupError(f"Chroma database does not exist: {self.chroma_db_path}")
            self._copy_sqlite_online(self.chroma_db_path, staged_chroma)

            # 3. Snapshot chroma segment directories if present
            staged_segments = staging_dir / "chroma_segments"
            if self.chroma_dir and self.chroma_dir.exists():
                for item in self.chroma_dir.iterdir():
                    if item.is_dir() and item.name != "__pycache__":
                        dest_sub = staged_segments / item.name
                        shutil.copytree(item, dest_sub, dirs_exist_ok=True)

            # 4. Dual independent integrity verification on staged copies
            h_ok, h_msg = self.verify_database_integrity(staged_hinaku)
            c_ok, c_msg = self.verify_database_integrity(staged_chroma)

            if not h_ok or not c_ok:
                err_msg = f"Staged backup integrity check failed: hinaku={h_msg}, chroma={c_msg}"
                logger.error(err_msg)
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise DatabaseBackupError(err_msg)

            # 5. Build and save metadata
            hinaku_hash = compute_file_sha256(staged_hinaku)
            chroma_hash = compute_file_sha256(staged_chroma)
            now_iso = datetime.datetime.now(timezone.utc).isoformat()

            metadata = {
                "recovery_set_id": recovery_set_id,
                "created_at": now_iso,
                "description": description or "Coordinated multi-database recovery snapshot",
                "status": "verified",
                "databases": {
                    "hinaku": {
                        "filename": "hinaku.db",
                        "sha256": hinaku_hash,
                        "size_bytes": staged_hinaku.stat().st_size,
                        "integrity": h_msg,
                    },
                    "chroma": {
                        "filename": "chroma.sqlite3",
                        "sha256": chroma_hash,
                        "size_bytes": staged_chroma.stat().st_size,
                        "integrity": c_msg,
                        "has_segments": staged_segments.exists(),
                    },
                },
            }

            with open(staging_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            # 6. Atomic promotion (rename directory)
            staging_dir.rename(promoted_dir)
            logger.info(f"Coordinated recovery set successfully promoted: {recovery_set_id}")

            # 7. Safe retention pruning
            self.prune_backups()

            return metadata

        except Exception as e:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            logger.error(f"Coordinated backup failed: {e}")
            raise
        finally:
            # Always resume writers safely
            self.coordinator.resume_writers()

    def list_recovery_sets(self) -> List[Dict[str, Any]]:
        """
        Lists all available recovery sets, sorted newest to oldest.
        Only returns sets that have a valid metadata.json file.
        """
        sets: List[Dict[str, Any]] = []
        if not self.backup_dir.exists():
            return sets

        for entry in self.backup_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("recovery_set_"):
                meta_file = entry / "metadata.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            sets.append(data)
                    except Exception as e:
                        logger.warning(f"Error reading recovery set metadata in {entry}: {e}")

        # Sort newest first
        sets.sort(key=lambda s: s.get("created_at", ""), reverse=True)
        return sets

    def get_recovery_set(self, recovery_set_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve details for a specific recovery set ID."""
        target_dir = self.backup_dir / recovery_set_id
        meta_file = target_dir / "metadata.json"
        if not target_dir.exists() or not meta_file.exists():
            return None

        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def prune_backups(self) -> List[str]:
        """
        Prunes recovery sets according to retention_count.
        INVIOLABLE SAFETY INVARIANT: Never deletes the last verified known-good recovery set.
        """
        all_sets = self.list_recovery_sets()
        verified_sets = [s for s in all_sets if s.get("status") == "verified"]

        if len(all_sets) <= self.retention_count:
            return []

        # Sets beyond retention limit (oldest candidates)
        to_consider = all_sets[self.retention_count:]
        pruned_ids: List[str] = []

        for candidate in to_consider:
            cid = candidate["recovery_set_id"]
            # If candidate is verified, check if deleting it would leave 0 verified sets
            if candidate.get("status") == "verified":
                remaining_verified = [
                    s for s in verified_sets if s["recovery_set_id"] != cid and s["recovery_set_id"] not in pruned_ids
                ]
                if not remaining_verified:
                    logger.warning(
                        f"Pruning blocked for {cid}: preserving the last verified known-good recovery set."
                    )
                    continue

            target_path = self.backup_dir / cid
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)
                pruned_ids.append(cid)
                logger.info(f"Pruned older recovery set: {cid}")

        return pruned_ids

    def restore_recovery_set(
        self,
        recovery_set_id: str,
        reason: str = "",
        has_owner_session: bool = True,
    ) -> Dict[str, Any]:
        """
        Restores both databases as a coordinated pair from the designated recovery set:
        1. Enforces active owner desktop session authorization.
        2. Quiesces all writers.
        3. Preserves both current live databases to .pre_restore.<timestamp>.
        4. Replaces both live database files from the recovery set.
        5. Verifies integrity of both restored files.
        6. If either replacement fails or fails integrity check:
           - Initiates controlled rollback to preserved original files.
           - Verifies rollback integrity.
           - If rollback fails, halts permanently and alerts owner.
        """
        assert_owner_session_required("restore_backup", has_owner_session)

        target_set_dir = self.backup_dir / recovery_set_id
        if not target_set_dir.exists():
            raise FileNotFoundError(f"Recovery set '{recovery_set_id}' not found in {self.backup_dir}")

        meta = self.get_recovery_set(recovery_set_id)
        if not meta or meta.get("status") != "verified":
            raise ValueError(f"Recovery set '{recovery_set_id}' is not a verified recovery set.")

        backup_hinaku = target_set_dir / "hinaku.db"
        backup_chroma = target_set_dir / "chroma.sqlite3"
        backup_segments = target_set_dir / "chroma_segments"

        if not backup_hinaku.exists() or not backup_chroma.exists():
            raise FileNotFoundError(
                f"Recovery set '{recovery_set_id}' is incomplete (missing hinaku.db or chroma.sqlite3)."
            )

        now_ts = datetime.datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        pre_restore_hinaku = self.hinaku_db_path.parent / f"hinaku.pre_restore.{now_ts}.db"
        pre_restore_chroma = self.chroma_db_path.parent / f"chroma.pre_restore.{now_ts}.sqlite3"
        pre_restore_segments = self.chroma_dir.parent / f"chroma_segments.pre_restore.{now_ts}"

        # Quiesce writers during the entire restoration window
        self.coordinator.quiesce_writers(timeout=10.0)
        try:
            logger.info(f"Initiating coordinated restore from recovery set '{recovery_set_id}'. Reason: {reason}")

            # Safely close and release active database and Chroma client handles
            self.coordinator.release_all_handles()
            try:
                # 1. Preserve current live state before modification
                if self.hinaku_db_path.exists():
                    shutil.copy2(self.hinaku_db_path, pre_restore_hinaku)
                if self.chroma_db_path.exists():
                    shutil.copy2(self.chroma_db_path, pre_restore_chroma)
                if self.chroma_dir and self.chroma_dir.exists():
                    shutil.copytree(self.chroma_dir, pre_restore_segments, dirs_exist_ok=True)

                logger.info("Pre-restoration live state preserved successfully.")

                # 2. Restore paired databases
                restore_failed = False
                fail_reason = ""

                try:
                    # Copy hinaku.db
                    shutil.copy2(backup_hinaku, self.hinaku_db_path)
                    # Copy chroma.sqlite3
                    self.chroma_db_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_chroma, self.chroma_db_path)

                    # Copy segments if present
                    if backup_segments.exists():
                        shutil.copytree(backup_segments, self.chroma_dir, dirs_exist_ok=True)

                    # 3. Post-restoration integrity checks
                    h_ok, h_msg = self.verify_database_integrity(self.hinaku_db_path)
                    c_ok, c_msg = self.verify_database_integrity(self.chroma_db_path)

                    if not h_ok or not c_ok:
                        restore_failed = True
                        fail_reason = f"Post-restore integrity check failed: hinaku={h_msg}, chroma={c_msg}"
                except Exception as e:
                    restore_failed = True
                    fail_reason = f"Exception during database file restoration: {e}"

                # 4. Handle failure and execute controlled rollback
                if restore_failed:
                    logger.critical(f"RESTORE FAILED: {fail_reason}. Initiating automated controlled rollback...")
                    rollback_ok = self._rollback_from_preserved(
                        pre_restore_hinaku, pre_restore_chroma, pre_restore_segments
                    )
                    if rollback_ok:
                        raise DatabaseRestoreError(
                            f"Restoration failed and was safely rolled back to pre-restoration state. Error: {fail_reason}"
                        )
                    else:
                        raise DatabaseRestoreFatalError(
                            f"FATAL: Restoration failed ({fail_reason}) AND automated rollback failed. "
                            "System stopped; manual forensic recovery required."
                        )

                logger.info(f"Coordinated restoration of recovery set '{recovery_set_id}' completed successfully.")
                return {
                    "status": "restored",
                    "recovery_set_id": recovery_set_id,
                    "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
                    "reason": reason,
                    "preserved_hinaku": str(pre_restore_hinaku),
                    "preserved_chroma": str(pre_restore_chroma),
                }
            finally:
                # Reopen handles before resuming writers
                self.coordinator.reopen_all_handles()

        finally:
            self.coordinator.resume_writers()

    def _rollback_from_preserved(
        self,
        preserved_hinaku: Path,
        preserved_chroma: Path,
        preserved_segments: Path,
    ) -> bool:
        """
        Rolls back both databases from the preserved pre-restore copies.
        Returns True if rollback succeeds and both databases pass integrity checks.
        """
        try:
            if preserved_hinaku.exists():
                shutil.copy2(preserved_hinaku, self.hinaku_db_path)
            if preserved_chroma.exists():
                shutil.copy2(preserved_chroma, self.chroma_db_path)
            if preserved_segments.exists() and self.chroma_dir:
                shutil.copytree(preserved_segments, self.chroma_dir, dirs_exist_ok=True)

            # Verify rolled back databases
            h_ok, _ = self.verify_database_integrity(self.hinaku_db_path)
            c_ok, _ = self.verify_database_integrity(self.chroma_db_path)

            return h_ok and c_ok
        except Exception as e:
            logger.critical(f"Exception during rollback execution: {e}")
            return False


# Global singleton backup manager
_backup_manager: Optional[DatabaseBackupManager] = None


def get_backup_manager() -> DatabaseBackupManager:
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = DatabaseBackupManager()
    return _backup_manager


def set_backup_manager(manager: DatabaseBackupManager) -> None:
    global _backup_manager
    _backup_manager = manager
