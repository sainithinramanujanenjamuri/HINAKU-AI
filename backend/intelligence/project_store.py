"""
backend/intelligence/project_store.py

Persistent SQLite storage for HINAKU Project Intelligence.
Manages projects, structured knowledge items, audit revisions, and repository file indexing.
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from .errors import (
    DuplicateProjectError,
    IntelligenceError,
    ProjectNotFoundError,
    ProvenanceError,
)
from .project_types import (
    KnowledgeCategory,
    ProjectConfidentiality,
    ProjectKnowledgeItem,
    ProjectKnowledgeRevision,
    ProjectRecord,
    ProjectStatus,
    RepositoryFileIndex,
)
from .types import (
    ImplementationStatus,
    KnowledgeProvenance,
    SourceAuthority,
)


class ProjectStore:
    """SQLite-backed storage manager for projects and structured project knowledge."""

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
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    purpose TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT 'owner',
                    status TEXT NOT NULL,
                    tech_stack TEXT NOT NULL DEFAULT '[]',
                    repo_path TEXT,
                    confidentiality TEXT NOT NULL DEFAULT 'internal',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS project_knowledge (
                    item_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    claim_confidence REAL NOT NULL,
                    verification_status TEXT NOT NULL,
                    implementation_evidence TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS project_knowledge_revisions (
                    revision_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    previous_content TEXT NOT NULL,
                    new_content TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    claim_confidence REAL NOT NULL,
                    verification_status TEXT NOT NULL,
                    implementation_evidence TEXT,
                    changed_by TEXT NOT NULL DEFAULT 'owner',
                    reason TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS project_repo_files (
                    file_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    file_extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    last_modified REAL NOT NULL,
                    indexed_at REAL NOT NULL,
                    summary TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status, deleted);
                CREATE INDEX IF NOT EXISTS idx_projects_name ON projects (name);
                CREATE INDEX IF NOT EXISTS idx_project_knowledge_cat ON project_knowledge (project_id, category, deleted);
                CREATE INDEX IF NOT EXISTS idx_project_revisions_item ON project_knowledge_revisions (item_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_project_repo_files_proj ON project_repo_files (project_id, relative_path);
            """)

    # --------------------------------------------------------------------------
    # Project Identity & Registration
    # --------------------------------------------------------------------------

    def create_project(self, record: ProjectRecord) -> ProjectRecord:
        """Registers a new project, preventing duplicates by id or name."""
        with self._get_connection() as conn:
            # Check for existing project with same ID
            existing_id = conn.execute(
                "SELECT project_id FROM projects WHERE project_id = ? AND deleted = 0",
                (record.project_id,)
            ).fetchone()
            if existing_id:
                raise DuplicateProjectError(f"Project with ID '{record.project_id}' already exists.")

            # Check for existing project with same name (case-insensitive)
            existing_name = conn.execute(
                "SELECT project_id FROM projects WHERE LOWER(name) = LOWER(?) AND deleted = 0",
                (record.name,)
            ).fetchone()
            if existing_name:
                raise DuplicateProjectError(
                    f"Project with name '{record.name}' already exists (ID: {existing_name['project_id']})."
                )

            now = time.time()
            record.created_at = record.created_at or now
            record.updated_at = record.updated_at or now

            conn.execute(
                """
                INSERT INTO projects (
                    project_id, name, description, purpose, owner, status,
                    tech_stack, repo_path, confidentiality, metadata,
                    created_at, updated_at, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.project_id,
                    record.name,
                    record.description,
                    record.purpose,
                    record.owner,
                    record.status.value,
                    json.dumps(record.tech_stack),
                    record.repo_path,
                    record.confidentiality.value,
                    json.dumps(record.metadata),
                    record.created_at,
                    record.updated_at,
                    record.deleted,
                )
            )
        return record

    def get_project(self, project_id: str, include_deleted: bool = False) -> Optional[ProjectRecord]:
        """Retrieves a project record by ID."""
        with self._get_connection() as conn:
            query = "SELECT * FROM projects WHERE project_id = ?"
            if not include_deleted:
                query += " AND deleted = 0"
            row = conn.execute(query, (project_id,)).fetchone()
            if not row:
                return None
            return self._row_to_project(row)

    def list_projects(
        self,
        status: Optional[ProjectStatus] = None,
        include_deleted: bool = False,
    ) -> List[ProjectRecord]:
        """Lists registered projects, optionally filtered by status."""
        with self._get_connection() as conn:
            query = "SELECT * FROM projects WHERE 1=1"
            params: List[Any] = []
            if not include_deleted:
                query += " AND deleted = 0"
            if status is not None:
                query += " AND status = ?"
                params.append(status.value)
            query += " ORDER BY updated_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_project(r) for r in rows]

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> ProjectRecord:
        """Updates project properties and updates updated_at timestamp."""
        existing = self.get_project(project_id)
        if not existing:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")

        allowed_fields = {
            "name", "description", "purpose", "status", "tech_stack",
            "repo_path", "confidentiality", "metadata"
        }
        set_clauses = []
        params = []
        for k, v in updates.items():
            if k not in allowed_fields:
                continue
            if k == "status" and isinstance(v, ProjectStatus):
                v = v.value
            elif k == "confidentiality" and isinstance(v, ProjectConfidentiality):
                v = v.value
            elif k in ("tech_stack", "metadata"):
                v = json.dumps(v)
            set_clauses.append(f"{k} = ?")
            params.append(v)

        if not set_clauses:
            return existing

        now = time.time()
        set_clauses.append("updated_at = ?")
        params.append(now)
        params.append(project_id)

        with self._get_connection() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(set_clauses)} WHERE project_id = ?",
                params
            )
        return self.get_project(project_id)  # type: ignore

    def delete_project(
        self,
        project_id: str,
        hard_delete: bool = False,
        owner_confirmed: bool = False,
    ) -> bool:
        """
        Deletes a project.
        By default, performs a non-destructive soft delete (deleted=1), preserving knowledge history.
        Hard delete requires explicit owner_confirmed=True.
        """
        existing = self.get_project(project_id, include_deleted=True)
        if not existing:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")

        with self._get_connection() as conn:
            if hard_delete:
                if not owner_confirmed:
                    raise IntelligenceError(
                        "Hard deletion of a project strictly requires explicit owner confirmation."
                    )
                # Remove repo files first (safe to delete)
                conn.execute("DELETE FROM project_repo_files WHERE project_id = ?", (project_id,))
                # Remove knowledge and revisions if owner explicitly confirmed
                conn.execute("DELETE FROM project_knowledge_revisions WHERE project_id = ?", (project_id,))
                conn.execute("DELETE FROM project_knowledge WHERE project_id = ?", (project_id,))
                conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
            else:
                # Soft delete
                conn.execute(
                    "UPDATE projects SET deleted = 1, updated_at = ? WHERE project_id = ?",
                    (time.time(), project_id)
                )
        return True

    # --------------------------------------------------------------------------
    # Structured Project Knowledge
    # --------------------------------------------------------------------------

    def add_knowledge_item(self, item: ProjectKnowledgeItem) -> ProjectKnowledgeItem:
        """Adds a structured project knowledge item and records its initial revision."""
        project = self.get_project(item.project_id)
        if not project:
            raise ProjectNotFoundError(
                f"Cannot add knowledge: project '{item.project_id}' does not exist."
            )

        now = time.time()
        item.created_at = item.created_at or now
        item.updated_at = item.updated_at or now
        item.item_id = item.item_id or str(uuid.uuid4())

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO project_knowledge (
                    item_id, project_id, category, title, content,
                    source_authority, claim_confidence, verification_status,
                    implementation_evidence, tags, revision, created_at, updated_at, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.item_id,
                    item.project_id,
                    item.category.value,
                    item.title,
                    item.content,
                    item.provenance.source_authority.value,
                    item.provenance.claim_confidence,
                    item.provenance.verification_status.value,
                    json.dumps(item.provenance.implementation_evidence) if item.provenance.implementation_evidence else None,
                    json.dumps(item.tags),
                    item.revision,
                    item.created_at,
                    item.updated_at,
                    item.deleted,
                )
            )

            # Record initial revision
            revision_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO project_knowledge_revisions (
                    revision_id, item_id, project_id, previous_content, new_content,
                    source_authority, claim_confidence, verification_status,
                    implementation_evidence, changed_by, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    item.item_id,
                    item.project_id,
                    "",
                    item.content,
                    item.provenance.source_authority.value,
                    item.provenance.claim_confidence,
                    item.provenance.verification_status.value,
                    json.dumps(item.provenance.implementation_evidence) if item.provenance.implementation_evidence else None,
                    "owner",
                    "Initial knowledge creation",
                    now,
                )
            )
        return item

    def get_knowledge_item(self, item_id: str, include_deleted: bool = False) -> Optional[ProjectKnowledgeItem]:
        """Retrieves a single knowledge item by ID."""
        with self._get_connection() as conn:
            query = "SELECT * FROM project_knowledge WHERE item_id = ?"
            if not include_deleted:
                query += " AND deleted = 0"
            row = conn.execute(query, (item_id,)).fetchone()
            if not row:
                return None
            return self._row_to_knowledge_item(row)

    def list_knowledge_items(
        self,
        project_id: str,
        category: Optional[KnowledgeCategory] = None,
        include_deleted: bool = False,
    ) -> List[ProjectKnowledgeItem]:
        """Lists knowledge items for a project, optionally filtered by category."""
        with self._get_connection() as conn:
            query = "SELECT * FROM project_knowledge WHERE project_id = ?"
            params: List[Any] = [project_id]
            if not include_deleted:
                query += " AND deleted = 0"
            if category is not None:
                query += " AND category = ?"
                params.append(category.value)
            query += " ORDER BY updated_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_knowledge_item(r) for r in rows]

    def update_knowledge_item(
        self,
        item_id: str,
        new_content: str,
        provenance: KnowledgeProvenance,
        changed_by: str = "owner",
        reason: str = "",
    ) -> ProjectKnowledgeItem:
        """
        Updates an existing knowledge item, bumping its revision and appending
        an immutable audit record to project_knowledge_revisions.
        """
        existing = self.get_knowledge_item(item_id)
        if not existing:
            raise IntelligenceError(f"Knowledge item '{item_id}' not found.")

        now = time.time()
        new_revision = existing.revision + 1

        with self._get_connection() as conn:
            # Update knowledge item
            conn.execute(
                """
                UPDATE project_knowledge SET
                    content = ?,
                    source_authority = ?,
                    claim_confidence = ?,
                    verification_status = ?,
                    implementation_evidence = ?,
                    revision = ?,
                    updated_at = ?
                WHERE item_id = ?
                """,
                (
                    new_content,
                    provenance.source_authority.value,
                    provenance.claim_confidence,
                    provenance.verification_status.value,
                    json.dumps(provenance.implementation_evidence) if provenance.implementation_evidence else None,
                    new_revision,
                    now,
                    item_id,
                )
            )

            # Record audit revision
            revision_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO project_knowledge_revisions (
                    revision_id, item_id, project_id, previous_content, new_content,
                    source_authority, claim_confidence, verification_status,
                    implementation_evidence, changed_by, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    item_id,
                    existing.project_id,
                    existing.content,
                    new_content,
                    provenance.source_authority.value,
                    provenance.claim_confidence,
                    provenance.verification_status.value,
                    json.dumps(provenance.implementation_evidence) if provenance.implementation_evidence else None,
                    changed_by,
                    reason,
                    now,
                )
            )

        return self.get_knowledge_item(item_id)  # type: ignore

    def delete_knowledge_item(
        self,
        item_id: str,
        hard_delete: bool = False,
        owner_confirmed: bool = False,
    ) -> bool:
        """Deletes a knowledge item (soft delete by default, preserving revisions)."""
        existing = self.get_knowledge_item(item_id, include_deleted=True)
        if not existing:
            raise IntelligenceError(f"Knowledge item '{item_id}' not found.")

        with self._get_connection() as conn:
            if hard_delete:
                if not owner_confirmed:
                    raise IntelligenceError("Hard delete strictly requires explicit owner confirmation.")
                conn.execute("DELETE FROM project_knowledge_revisions WHERE item_id = ?", (item_id,))
                conn.execute("DELETE FROM project_knowledge WHERE item_id = ?", (item_id,))
            else:
                conn.execute(
                    "UPDATE project_knowledge SET deleted = 1, updated_at = ? WHERE item_id = ?",
                    (time.time(), item_id)
                )
        return True

    def get_knowledge_revisions(self, item_id: str) -> List[ProjectKnowledgeRevision]:
        """Retrieves the full revision history for a knowledge item."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM project_knowledge_revisions WHERE item_id = ? ORDER BY created_at ASC",
                (item_id,)
            ).fetchall()
            return [self._row_to_revision(r) for r in rows]

    # --------------------------------------------------------------------------
    # Repository Grounding Index
    # --------------------------------------------------------------------------

    def upsert_repo_files(self, project_id: str, files: List[RepositoryFileIndex]) -> None:
        """Batch upserts indexed files for a project repository."""
        with self._get_connection() as conn:
            for f in files:
                conn.execute(
                    """
                    INSERT INTO project_repo_files (
                        file_id, project_id, relative_path, file_extension,
                        size_bytes, content_hash, last_modified, indexed_at, summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(file_id) DO UPDATE SET
                        relative_path = excluded.relative_path,
                        file_extension = excluded.file_extension,
                        size_bytes = excluded.size_bytes,
                        content_hash = excluded.content_hash,
                        last_modified = excluded.last_modified,
                        indexed_at = excluded.indexed_at,
                        summary = excluded.summary
                    """,
                    (
                        f.file_id,
                        f.project_id,
                        f.relative_path,
                        f.file_extension,
                        f.size_bytes,
                        f.content_hash,
                        f.last_modified,
                        f.indexed_at,
                        f.summary,
                    )
                )

    def list_repo_files(self, project_id: str) -> List[RepositoryFileIndex]:
        """Lists all indexed files for a project repository."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM project_repo_files WHERE project_id = ? ORDER BY relative_path ASC",
                (project_id,)
            ).fetchall()
            return [self._row_to_repo_file(r) for r in rows]

    def get_repo_file(self, project_id: str, relative_path: str) -> Optional[RepositoryFileIndex]:
        """Retrieves a single indexed repo file by relative path."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM project_repo_files WHERE project_id = ? AND relative_path = ?",
                (project_id, relative_path)
            ).fetchone()
            if not row:
                return None
            return self._row_to_repo_file(row)

    # --------------------------------------------------------------------------
    # Row Deserialization Helpers
    # --------------------------------------------------------------------------

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            project_id=row["project_id"],
            name=row["name"],
            description=row["description"],
            purpose=row["purpose"],
            owner=row["owner"],
            status=ProjectStatus(row["status"]),
            tech_stack=json.loads(row["tech_stack"]),
            repo_path=row["repo_path"],
            confidentiality=ProjectConfidentiality(row["confidentiality"]),
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted=row["deleted"],
        )

    @staticmethod
    def _row_to_knowledge_item(row: sqlite3.Row) -> ProjectKnowledgeItem:
        evidence = json.loads(row["implementation_evidence"]) if row["implementation_evidence"] else None
        provenance = KnowledgeProvenance(
            source_authority=SourceAuthority(row["source_authority"]),
            claim_confidence=row["claim_confidence"],
            verification_status=ImplementationStatus(row["verification_status"]),
            implementation_evidence=evidence,
            created_at=row["created_at"],
        )
        return ProjectKnowledgeItem(
            item_id=row["item_id"],
            project_id=row["project_id"],
            category=KnowledgeCategory(row["category"]),
            title=row["title"],
            content=row["content"],
            provenance=provenance,
            tags=json.loads(row["tags"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            revision=row["revision"],
            deleted=row["deleted"],
        )

    @staticmethod
    def _row_to_revision(row: sqlite3.Row) -> ProjectKnowledgeRevision:
        evidence = json.loads(row["implementation_evidence"]) if row["implementation_evidence"] else None
        provenance = KnowledgeProvenance(
            source_authority=SourceAuthority(row["source_authority"]),
            claim_confidence=row["claim_confidence"],
            verification_status=ImplementationStatus(row["verification_status"]),
            implementation_evidence=evidence,
            created_at=row["created_at"],
        )
        return ProjectKnowledgeRevision(
            revision_id=row["revision_id"],
            item_id=row["item_id"],
            project_id=row["project_id"],
            previous_content=row["previous_content"],
            new_content=row["new_content"],
            provenance=provenance,
            changed_by=row["changed_by"],
            reason=row["reason"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_repo_file(row: sqlite3.Row) -> RepositoryFileIndex:
        return RepositoryFileIndex(
            file_id=row["file_id"],
            project_id=row["project_id"],
            relative_path=row["relative_path"],
            file_extension=row["file_extension"],
            size_bytes=row["size_bytes"],
            content_hash=row["content_hash"],
            last_modified=row["last_modified"],
            indexed_at=row["indexed_at"],
            summary=row["summary"],
        )
