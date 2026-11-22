"""
backend/intelligence/weakness_catalog.py

Weakness Cataloging engine for HINAKU Controlled Learning.
Maintains systemic weakness records, aggregates recurring interaction failure modes,
manages weakness lifecycle states, and correlates experience records.

SAFETY INVARIANTS:
1. Data, Not Permissions: Weakness records describe failure patterns for analysis.
   They NEVER grant autonomous authority to execute or deploy system modifications.
2. Controlled Lifecycle: Status transitions (IDENTIFIED -> UNDER_REVIEW -> PROPOSED_FIX -> RESOLVED/IGNORED)
   are audit-tracked and require explicit review to transition out of candidate states.
3. Decoupled Architecture: The catalog operates on structured WeaknessRecord data
   persisted in SQLite without altering core prompts or models.
"""

import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from .learning_types import (
    ErrorCategory,
    ExperienceRecord,
    WeaknessRecord,
    WeaknessSeverity,
    WeaknessStatus,
)
from backend.database.backup import coordinated_write

logger = logging.getLogger("hinaku.intelligence.weakness_catalog")


class WeaknessCatalog:
    """
    Manages persistence, clustering, frequency tracking, and status transitions
    for cataloged systemic weaknesses.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initializes weakness_records SQLite table and indexes."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS weakness_records (
                    weakness_id TEXT PRIMARY KEY,
                    error_category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    frequency INTEGER NOT NULL DEFAULT 1,
                    severity TEXT NOT NULL,
                    supporting_experience_ids TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    first_observed_at REAL NOT NULL,
                    last_observed_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_weakness_category ON weakness_records (error_category);
                CREATE INDEX IF NOT EXISTS idx_weakness_status ON weakness_records (status);
                CREATE INDEX IF NOT EXISTS idx_weakness_severity ON weakness_records (severity);
                CREATE INDEX IF NOT EXISTS idx_weakness_freq ON weakness_records (frequency DESC);
            """)

    def register_weakness(self, record: WeaknessRecord) -> WeaknessRecord:
        """
        Validates and persists a new or updated WeaknessRecord.
        """
        record.validate()
        exp_ids_json = json.dumps(record.supporting_experience_ids)
        meta_json = json.dumps(record.metadata)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO weakness_records (
                    weakness_id, error_category, description, frequency, severity,
                    supporting_experience_ids, confidence, first_observed_at,
                    last_observed_at, status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.weakness_id,
                    record.error_category.value,
                    record.description,
                    record.frequency,
                    record.severity.value,
                    exp_ids_json,
                    record.confidence,
                    record.first_observed_at,
                    record.last_observed_at,
                    record.status.value,
                    meta_json,
                ),
            )

        return record

    @coordinated_write("weakness_catalog")
    def catalog_experience(
        self,
        experience: ExperienceRecord,
        auto_cluster: bool = True,
    ) -> Optional[WeaknessRecord]:
        """
        Analyzes an incoming ExperienceRecord:
        1. If a matching active weakness exists for the error category, increments frequency
           and appends the experience ID.
        2. If no active weakness exists and auto_cluster is True, creates a new WeaknessRecord.
        """
        if not experience.error_category:
            return None

        # Look for existing active weakness (not resolved or ignored) with the same error category
        active_weakness = self._find_active_by_category(experience.error_category)

        if active_weakness:
            # Update existing weakness
            supporting_ids = list(active_weakness.supporting_experience_ids)
            if experience.experience_id not in supporting_ids:
                supporting_ids.append(experience.experience_id)

            new_freq = active_weakness.frequency + 1
            # Recalculate severity dynamically based on recurrence
            new_severity = self._compute_severity(new_freq, active_weakness.severity)
            new_last_observed = max(active_weakness.last_observed_at, experience.created_at)

            updated_record = WeaknessRecord(
                weakness_id=active_weakness.weakness_id,
                error_category=active_weakness.error_category,
                description=active_weakness.description,
                frequency=new_freq,
                severity=new_severity,
                supporting_experience_ids=supporting_ids,
                confidence=active_weakness.confidence,
                first_observed_at=active_weakness.first_observed_at,
                last_observed_at=new_last_observed,
                status=active_weakness.status,
                metadata=dict(active_weakness.metadata),
            )
            return self.register_weakness(updated_record)

        elif auto_cluster:
            # Create a new weakness record
            desc = (
                experience.inferred_failure_mode
                or f"Recurring failure in category {experience.error_category.value} observed from interaction feedback."
            )
            new_record = WeaknessRecord(
                weakness_id=f"weak_{uuid.uuid4().hex[:12]}",
                error_category=experience.error_category,
                description=desc,
                frequency=1,
                severity=WeaknessSeverity.MEDIUM,
                supporting_experience_ids=[experience.experience_id],
                confidence=experience.confidence,
                first_observed_at=experience.created_at,
                last_observed_at=experience.created_at,
                status=WeaknessStatus.IDENTIFIED,
                metadata={"auto_clustered": True},
            )
            return self.register_weakness(new_record)

        return None

    def get_weakness(self, weakness_id: str) -> Optional[WeaknessRecord]:
        """Retrieves a weakness record by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM weakness_records WHERE weakness_id = ?;",
                (weakness_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def list_weaknesses(
        self,
        status: Optional[WeaknessStatus] = None,
        error_category: Optional[ErrorCategory] = None,
        severity: Optional[WeaknessSeverity] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WeaknessRecord]:
        """Lists weakness records matching optional filters."""
        query = "SELECT * FROM weakness_records WHERE 1=1"
        params: List[Any] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if error_category is not None:
            query += " AND error_category = ?"
            params.append(error_category.value)
        if severity is not None:
            query += " AND severity = ?"
            params.append(severity.value)

        query += " ORDER BY frequency DESC, last_observed_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def update_status(
        self,
        weakness_id: str,
        new_status: WeaknessStatus,
        resolution_note: Optional[str] = None,
    ) -> WeaknessRecord:
        """
        Updates the lifecycle status of a weakness record.
        """
        record = self.get_weakness(weakness_id)
        if not record:
            raise KeyError(f"Weakness record '{weakness_id}' not found.")

        metadata = dict(record.metadata)
        if resolution_note:
            metadata["resolution_note"] = resolution_note
        metadata["status_updated_at"] = time.time()

        updated = WeaknessRecord(
            weakness_id=record.weakness_id,
            error_category=record.error_category,
            description=record.description,
            frequency=record.frequency,
            severity=record.severity,
            supporting_experience_ids=record.supporting_experience_ids,
            confidence=record.confidence,
            first_observed_at=record.first_observed_at,
            last_observed_at=record.last_observed_at,
            status=new_status,
            metadata=metadata,
        )
        return self.register_weakness(updated)

    def count_weaknesses(
        self,
        status: Optional[WeaknessStatus] = None,
        error_category: Optional[ErrorCategory] = None,
    ) -> int:
        """Returns total count of weaknesses matching optional filters."""
        query = "SELECT COUNT(*) FROM weakness_records WHERE 1=1"
        params: List[Any] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        if error_category is not None:
            query += " AND error_category = ?"
            params.append(error_category.value)

        with self._get_connection() as conn:
            return conn.execute(query, params).fetchone()[0]

    @coordinated_write("weakness_catalog")
    def delete_weakness(self, weakness_id: str) -> bool:
        """Deletes a weakness record by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM weakness_records WHERE weakness_id = ?;",
                (weakness_id,),
            )
            return cursor.rowcount > 0

    @coordinated_write("weakness_catalog")
    def unlink_experience(self, experience_id: str) -> int:
        """
        Removes an experience ID from all weakness records' supporting_experience_ids.
        Maintains referential integrity when an experience is deleted for privacy or cleanup.
        Returns the number of weakness records updated.
        """
        updated_count = 0
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM weakness_records;").fetchall()
            for row in rows:
                rec = self._row_to_record(row)
                if experience_id in rec.supporting_experience_ids:
                    new_ids = [eid for eid in rec.supporting_experience_ids if eid != experience_id]
                    conn.execute(
                        "UPDATE weakness_records SET supporting_experience_ids = ? WHERE weakness_id = ?;",
                        (json.dumps(new_ids), rec.weakness_id)
                    )
                    updated_count += 1
        return updated_count

    @coordinated_write("weakness_catalog")
    def clear_all_weaknesses(self) -> int:
        """Removes all weakness records (privacy / full data wipe)."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM weakness_records;")
            return cursor.rowcount

    def _find_active_by_category(self, category: ErrorCategory) -> Optional[WeaknessRecord]:
        """Finds an existing non-terminal (IDENTIFIED or UNDER_REVIEW) weakness for this category."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM weakness_records
                WHERE error_category = ?
                  AND status IN (?, ?)
                ORDER BY frequency DESC, last_observed_at DESC
                LIMIT 1;
                """,
                (
                    category.value,
                    WeaknessStatus.IDENTIFIED.value,
                    WeaknessStatus.UNDER_REVIEW.value,
                ),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def _compute_severity(self, frequency: int, current_severity: WeaknessSeverity) -> WeaknessSeverity:
        """Escalates severity if recurrence frequency crosses thresholds."""
        if frequency >= 10:
            return WeaknessSeverity.CRITICAL
        elif frequency >= 5:
            return WeaknessSeverity.HIGH
        elif frequency >= 3:
            return WeaknessSeverity.MEDIUM
        return current_severity

    def _row_to_record(self, row: sqlite3.Row) -> WeaknessRecord:
        exp_ids = []
        if row["supporting_experience_ids"]:
            try:
                exp_ids = json.loads(row["supporting_experience_ids"])
            except Exception:
                pass

        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                pass

        return WeaknessRecord(
            weakness_id=row["weakness_id"],
            error_category=ErrorCategory(row["error_category"]),
            description=row["description"],
            frequency=row["frequency"],
            severity=WeaknessSeverity(row["severity"]),
            supporting_experience_ids=exp_ids,
            confidence=row["confidence"],
            first_observed_at=row["first_observed_at"],
            last_observed_at=row["last_observed_at"],
            status=WeaknessStatus(row["status"]),
            metadata=meta,
        )
