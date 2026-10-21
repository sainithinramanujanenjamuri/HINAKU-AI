"""
scripts/migrate_hard_delete.py

One-time migration script to permanently purge any rows marked deleted in SQLite,
sync vectors in ChromaDB, and VACUUM the database file so no raw bytes remain.
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("migrate_hard_delete")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def inspect_deleted_rows(db_path: Path) -> Dict[str, Any]:
    """Inspect the SQLite database and count rows marked deleted or orphaned."""
    if not db_path.exists():
        return {
            "exists": False,
            "deleted_memories": 0,
            "deleted_memory_ids": [],
            "orphan_messages": 0,
            "orphan_interactions": 0
        }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        
        deleted_memories = 0
        deleted_memory_ids: List[str] = []
        if "memories" in tables:
            cols = [c["name"] for c in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if "deleted" in cols:
                rows = conn.execute("SELECT id FROM memories WHERE deleted != 0").fetchall()
                deleted_memory_ids = [r["id"] for r in rows]
                deleted_memories = len(deleted_memory_ids)

        orphan_messages = 0
        if "messages" in tables and "conversations" in tables:
            orphan_messages = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)"
            ).fetchone()[0]

        orphan_interactions = 0
        if "interactions" in tables and "conversations" in tables:
            orphan_interactions = conn.execute(
                "SELECT COUNT(*) FROM interactions WHERE conversation_id IS NOT NULL AND conversation_id != '' AND conversation_id NOT IN (SELECT id FROM conversations)"
            ).fetchone()[0]

        return {
            "exists": True,
            "deleted_memories": deleted_memories,
            "deleted_memory_ids": deleted_memory_ids,
            "orphan_messages": orphan_messages,
            "orphan_interactions": orphan_interactions
        }
    finally:
        conn.close()


def migrate_hard_delete(
    db_path: Path,
    chroma_dir: Optional[Path] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Permanently deletes all rows marked deleted in SQLite,
    removes their embeddings from ChromaDB, and runs VACUUM.
    """
    stats = inspect_deleted_rows(db_path)
    if not stats["exists"]:
        return {"status": "db_not_found", "removed_memories": 0, "vacuumed": False}

    deleted_ids = stats["deleted_memory_ids"]
    removed_memories = len(deleted_ids)
    orphan_messages = stats["orphan_messages"]
    orphan_interactions = stats["orphan_interactions"]

    if dry_run:
        return {
            "status": "dry_run",
            "removed_memories": removed_memories,
            "orphan_messages": orphan_messages,
            "orphan_interactions": orphan_interactions,
            "vacuumed": False
        }

    # 1. Clean ChromaDB if chroma_dir is provided and deleted IDs exist
    if chroma_dir and chroma_dir.exists() and deleted_ids:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(chroma_dir))
            try:
                col = client.get_collection("owner_memories")
                col.delete(ids=deleted_ids)
                logger.info(f"Removed {len(deleted_ids)} deleted vectors from ChromaDB collection 'owner_memories'.")
            except Exception as e:
                logger.warning(f"Chroma collection clean note: {e}")
        except Exception as e:
            logger.error(f"Error accessing ChromaDB at {chroma_dir}: {e}")

    # 2. Hard-delete from SQLite
    conn = sqlite3.connect(str(db_path))
    try:
        if removed_memories > 0:
            conn.execute("DELETE FROM memories WHERE deleted != 0")
        if orphan_messages > 0:
            conn.execute("DELETE FROM messages WHERE conversation_id NOT IN (SELECT id FROM conversations)")
        if orphan_interactions > 0:
            conn.execute("DELETE FROM interactions WHERE conversation_id IS NOT NULL AND conversation_id != '' AND conversation_id NOT IN (SELECT id FROM conversations)")
        conn.commit()

        # 3. VACUUM to reclaim disk space and purge deleted text
        old_iso = conn.isolation_level
        conn.isolation_level = None
        conn.execute("VACUUM")
        conn.isolation_level = old_iso
        logger.info(f"VACUUM successfully completed on {db_path}.")
    finally:
        conn.close()

    return {
        "status": "migrated",
        "removed_memories": removed_memories,
        "orphan_messages": orphan_messages,
        "orphan_interactions": orphan_interactions,
        "vacuumed": True
    }


def main():
    parser = argparse.ArgumentParser(description="One-time migration to permanently remove deleted rows and VACUUM SQLite.")
    parser.add_argument("--db", default="data/hinaku.db", help="Path to SQLite database")
    parser.add_argument("--chroma", default="data/chroma", help="Path to ChromaDB directory")
    parser.add_argument("--apply", action="store_true", help="Apply the migration")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirm execution without interactive prompt")
    args = parser.parse_args()

    db_path = Path(args.db)
    chroma_path = Path(args.chroma)

    print(f"\n--- Checking database: {db_path} ---")
    stats = inspect_deleted_rows(db_path)
    if not stats["exists"]:
        print(f"Error: Database {db_path} does not exist.")
        sys.exit(1)

    print(f"Memories marked deleted (`deleted != 0`): {stats['deleted_memories']}")
    print(f"Orphaned messages: {stats['orphan_messages']}")
    print(f"Orphaned interactions: {stats['orphan_interactions']}")

    total_to_purge = stats["deleted_memories"] + stats["orphan_messages"] + stats["orphan_interactions"]

    if not args.apply:
        print("\nDry-run complete. No changes were made.")
        print("To apply this migration, run with --apply")
        return

    if not args.yes:
        confirm = input(f"\nPermanently purge {total_to_purge} row(s) and VACUUM {db_path}? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted by user.")
            return

    res = migrate_hard_delete(db_path, chroma_path, dry_run=False)
    print(f"\nMigration complete: removed {res['removed_memories']} memory row(s), {res['orphan_messages']} message(s), {res['orphan_interactions']} interaction(s). VACUUM executed.")


if __name__ == "__main__":
    main()
