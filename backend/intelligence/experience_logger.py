"""
backend/intelligence/experience_logger.py

SQLite-backed experience persistence and redaction engine for HINAKU Controlled Learning.
Logs user corrections, negative ratings, and interaction failures while ensuring:
1. All sensitive credentials, tokens, and secrets are redacted before persistence.
2. Inferred classifications remain decoupled from verified owner feedback.
3. Strict transactional execution and schema integrity.
4. Support for owner data review and deletion (GDPR / privacy full-wipe).
"""

import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from backend.guards import check_and_redact_sensitive_data
from .learning_types import (
    ErrorCategory,
    ExperienceRecord,
    FeedbackType,
)
from .types import KnowledgeProvenance

logger = logging.getLogger("hinaku.intelligence.experience_logger")


class ExperienceLogger:
    """
    Manages persistence, querying, and sanitization of experience records.
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
        """Initializes experience_records SQLite table and indexes."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS experience_records (
                    experience_id TEXT PRIMARY KEY,
                    feedback_type TEXT NOT NULL,
                    error_category TEXT,
                    task_id TEXT,
                    interaction_id TEXT,
                    project_id TEXT,
                    observed_user_feedback TEXT NOT NULL,
                    original_output_summary TEXT NOT NULL,
                    inferred_failure_mode TEXT,
                    provenance TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    redacted INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_exp_feedback ON experience_records (feedback_type);
                CREATE INDEX IF NOT EXISTS idx_exp_error ON experience_records (error_category);
                CREATE INDEX IF NOT EXISTS idx_exp_project ON experience_records (project_id);
                CREATE INDEX IF NOT EXISTS idx_exp_task ON experience_records (task_id);
                CREATE INDEX IF NOT EXISTS idx_exp_created ON experience_records (created_at DESC);
            """)

    def log_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """
        Sanitizes sensitive data and transactionally persists an ExperienceRecord.
        """
        # 1. Sanitize observed feedback
        det_feedback, clean_feedback = check_and_redact_sensitive_data(record.observed_user_feedback)
        # 2. Sanitize original output summary
        det_summary, clean_summary = check_and_redact_sensitive_data(record.original_output_summary)

        is_redacted = bool(record.redacted or det_feedback or det_summary)

        sanitized_record = ExperienceRecord(
            experience_id=record.experience_id,
            feedback_type=record.feedback_type,
            error_category=record.error_category,
            task_id=record.task_id,
            interaction_id=record.interaction_id,
            project_id=record.project_id,
            observed_user_feedback=clean_feedback,
            original_output_summary=clean_summary,
            inferred_failure_mode=record.inferred_failure_mode,
            provenance=record.provenance,
            confidence=record.confidence,
            redacted=is_redacted,
            metadata=dict(record.metadata),
            created_at=record.created_at,
        )

        sanitized_record.validate()

        prov_json = json.dumps(sanitized_record.provenance.to_dict()) if sanitized_record.provenance else None
        meta_json = json.dumps(sanitized_record.metadata)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experience_records (
                    experience_id, feedback_type, error_category, task_id, interaction_id,
                    project_id, observed_user_feedback, original_output_summary,
                    inferred_failure_mode, provenance, confidence, redacted, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    sanitized_record.experience_id,
                    sanitized_record.feedback_type.value,
                    sanitized_record.error_category.value if sanitized_record.error_category else None,
                    sanitized_record.task_id,
                    sanitized_record.interaction_id,
                    sanitized_record.project_id,
                    sanitized_record.observed_user_feedback,
                    sanitized_record.original_output_summary,
                    sanitized_record.inferred_failure_mode,
                    prov_json,
                    sanitized_record.confidence,
                    1 if sanitized_record.redacted else 0,
                    meta_json,
                    sanitized_record.created_at,
                ),
            )

        return sanitized_record

    def log_from_feedback(
        self,
        feedback_type: FeedbackType,
        observed_feedback: str,
        original_output: str,
        interaction_id: Optional[str] = None,
        task_id: Optional[str] = None,
        project_id: Optional[str] = None,
        inferred_error: Optional[ErrorCategory] = None,
        inferred_mode: Optional[str] = None,
        provenance: Optional[KnowledgeProvenance] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExperienceRecord:
        """
        Convenience constructor: creates, redacts, and persists an ExperienceRecord.
        """
        record_id = f"exp_{uuid.uuid4().hex[:12]}"
        record = ExperienceRecord(
            experience_id=record_id,
            feedback_type=feedback_type,
            error_category=inferred_error,
            task_id=task_id,
            interaction_id=interaction_id,
            project_id=project_id,
            observed_user_feedback=observed_feedback,
            original_output_summary=original_output[:500] if original_output else "",
            inferred_failure_mode=inferred_mode,
            provenance=provenance,
            confidence=confidence,
            metadata=metadata or {},
            created_at=time.time(),
        )
        return self.log_experience(record)

    def get_experience(self, experience_id: str) -> Optional[ExperienceRecord]:
        """Retrieves an experience record by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM experience_records WHERE experience_id = ?;",
                (experience_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def list_experiences(
        self,
        feedback_type: Optional[FeedbackType] = None,
        error_category: Optional[ErrorCategory] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ExperienceRecord]:
        """Lists experience records matching optional filters."""
        query = "SELECT * FROM experience_records WHERE 1=1"
        params: List[Any] = []

        if feedback_type is not None:
            query += " AND feedback_type = ?"
            params.append(feedback_type.value)
        if error_category is not None:
            query += " AND error_category = ?"
            params.append(error_category.value)
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def count_experiences(
        self,
        feedback_type: Optional[FeedbackType] = None,
        error_category: Optional[ErrorCategory] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Returns total count of experience records matching filters."""
        query = "SELECT COUNT(*) FROM experience_records WHERE 1=1"
        params: List[Any] = []

        if feedback_type is not None:
            query += " AND feedback_type = ?"
            params.append(feedback_type.value)
        if error_category is not None:
            query += " AND error_category = ?"
            params.append(error_category.value)
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)

        with self._get_connection() as conn:
            return conn.execute(query, params).fetchone()[0]

    def delete_experience(self, experience_id: str) -> bool:
        """Deletes an experience record by ID (supports owner data wipe)."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM experience_records WHERE experience_id = ?;",
                (experience_id,),
            )
            return cursor.rowcount > 0

    def clear_all_experiences(self) -> int:
        """Removes all experience records (privacy full-wipe support)."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM experience_records;")
            return cursor.rowcount

    def _row_to_record(self, row: sqlite3.Row) -> ExperienceRecord:
        prov = None
        if row["provenance"]:
            try:
                prov_data = json.loads(row["provenance"])
                prov = KnowledgeProvenance.from_dict(prov_data)
            except Exception:
                pass

        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except Exception:
                pass

        err_cat = ErrorCategory(row["error_category"]) if row["error_category"] else None

        return ExperienceRecord(
            experience_id=row["experience_id"],
            feedback_type=FeedbackType(row["feedback_type"]),
            error_category=err_cat,
            task_id=row["task_id"],
            interaction_id=row["interaction_id"],
            project_id=row["project_id"],
            observed_user_feedback=row["observed_user_feedback"],
            original_output_summary=row["original_output_summary"],
            inferred_failure_mode=row["inferred_failure_mode"],
            provenance=prov,
            confidence=row["confidence"],
            redacted=bool(row["redacted"]),
            metadata=meta,
            created_at=row["created_at"],
        )
