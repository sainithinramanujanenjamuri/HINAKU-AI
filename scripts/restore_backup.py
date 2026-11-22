#!/usr/bin/env python
"""
scripts/restore_backup.py

Offline/Cold Restoration CLI for HINAKU Coordinated Multi-Database Recovery Sets.

Executes safe restoration when the HINAKU application server is stopped,
guaranteeing that no active SQLite connection pools, ChromaDB clients,
or HNSW index file handles are holding open locks on database files.

Usage:
    python scripts/restore_backup.py --list
    python scripts/restore_backup.py --recovery-set <recovery_set_id> --confirm [--reason "Emergency restore"]
"""

import argparse
import datetime
import json
import logging
import os
from pathlib import Path
import sys
import urllib.request

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import get_settings
from backend.database.backup import DatabaseBackupManager, DatabaseRestoreError, DatabaseRestoreFatalError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hinaku.restore_cli")


def check_if_server_running(host: str = "127.0.0.1", port: int = 8000) -> bool:
    """Check if the live HINAKU server is currently running."""
    try:
        url = f"http://{host}:{port}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="HINAKU Offline Multi-Database Restore CLI")
    parser.add_argument("--list", action="store_true", help="List all available verified recovery sets")
    parser.add_argument("--recovery-set", type=str, help="Recovery set ID to restore (e.g., recovery_set_20261121_193000)")
    parser.add_argument("--confirm", action="store_true", help="Explicit confirmation of destructive restore")
    parser.add_argument("--reason", type=str, default="Offline CLI restoration", help="Reason for restoration")
    parser.add_argument("--ignore-running-check", action="store_true", help="Bypass running server check (advanced/override)")

    args = parser.parse_args()
    settings = get_settings()

    manager = DatabaseBackupManager(
        hinaku_db_path=settings.sqlite_path,
        chroma_db_path=settings.chroma_path / "chroma.sqlite3",
        chroma_dir=settings.chroma_path,
        backup_dir=settings.data_dir / "backups",
    )

    if args.list:
        sets = manager.list_recovery_sets()
        print(f"\nAvailable Recovery Sets ({len(sets)} total):")
        print("-" * 75)
        for s in sets:
            print(f"ID:          {s.get('recovery_set_id')}")
            print(f"Created:     {s.get('created_at')}")
            print(f"Status:      {s.get('status')}")
            print(f"Description: {s.get('description', '')}")
            print("-" * 75)
        return

    if not args.recovery_set:
        parser.error("Either --list or --recovery-set <id> must be specified.")

    if not args.confirm:
        parser.error("Restoration is destructive. You must pass --confirm to execute.")

    # Check server state
    if not args.ignore_running_check and check_if_server_running():
        logger.error(
            "FAIL-CLOSED: HINAKU application server appears to be actively running on port 8000. "
            "Safe ChromaDB and SQLite restore requires the server to be stopped to prevent open file-handle locks. "
            "Please stop the HINAKU process before running this restore script."
        )
        sys.exit(1)

    logger.info(f"Starting offline restoration of {args.recovery_set}...")
    try:
        result = manager.restore_recovery_set(
            recovery_set_id=args.recovery_set,
            reason=args.reason,
            has_owner_session=True,
        )
        logger.info("Restoration completed successfully.")
        print("\nRestore Result:")
        print(json.dumps(result, indent=2))
    except DatabaseRestoreError as e:
        logger.error(f"Restoration failed and was safely rolled back: {e}")
        sys.exit(2)
    except DatabaseRestoreFatalError as e:
        logger.critical(f"FATAL: Restoration and rollback failed: {e}")
        sys.exit(3)
    except Exception as e:
        logger.error(f"Restoration failed: {e}")
        sys.exit(4)


if __name__ == "__main__":
    main()
