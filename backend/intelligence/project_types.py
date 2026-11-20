"""
backend/intelligence/project_types.py

Data structures, enums, and models for the HINAKU Project Intelligence Engine.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional

from .types import (
    KnowledgeDomain,
    SourceAuthority,
    ImplementationStatus,
    KnowledgeProvenance,
)
from .errors import ProvenanceError


class ProjectStatus(str, Enum):
    """Lifecycle states for registered projects."""
    PROVISIONAL = "provisional"  # Inferred or candidate project pending confirmation
    ACTIVE = "active"            # Ongoing, currently maintained project
    PAUSED = "paused"            # Temporarily suspended
    COMPLETED = "completed"      # Successfully finished project
    ARCHIVED = "archived"        # Historical record; read-only reference


class ProjectConfidentiality(str, Enum):
    """Confidentiality classification for project intelligence."""
    INTERNAL = "internal"        # Standard internal project; local-first, requires explicit owner approval for API
    CONFIDENTIAL = "confidential" # Strict local-only; external API routing is strictly forbidden
    RESTRICTED = "restricted"     # Air-gapped / sensitive IP; strictly local, redacted from logs and exports


class KnowledgeCategory(str, Enum):
    """Structured categories of project knowledge."""
    IDENTITY_PURPOSE = "identity_purpose"
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    TECH_STACK = "tech_stack"
    DECISIONS = "decisions"
    IMPLEMENTATION = "implementation"
    BUGS_FIXES = "bugs_fixes"
    TASKS_MILESTONES = "tasks_milestones"
    DEPENDENCIES = "dependencies"
    OPEN_QUESTIONS = "open_questions"
    PROJECT_HISTORY = "project_history"
    COMPONENTS_FILES = "components_files"


@dataclass
class ProjectRecord:
    """Persistent entity representing a registered project."""
    project_id: str
    name: str
    description: str
    purpose: str
    owner: str = "owner"
    status: ProjectStatus = ProjectStatus.PROVISIONAL
    tech_stack: List[str] = field(default_factory=list)
    repo_path: Optional[str] = None
    confidentiality: ProjectConfidentiality = ProjectConfidentiality.INTERNAL
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    deleted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "purpose": self.purpose,
            "owner": self.owner,
            "status": self.status.value,
            "tech_stack": self.tech_stack,
            "repo_path": self.repo_path,
            "confidentiality": self.confidentiality.value,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectRecord":
        return cls(
            project_id=data["project_id"],
            name=data["name"],
            description=data.get("description", ""),
            purpose=data.get("purpose", ""),
            owner=data.get("owner", "owner"),
            status=ProjectStatus(data.get("status", ProjectStatus.PROVISIONAL.value)),
            tech_stack=data.get("tech_stack", []),
            repo_path=data.get("repo_path"),
            confidentiality=ProjectConfidentiality(
                data.get("confidentiality", ProjectConfidentiality.INTERNAL.value)
            ),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            deleted=data.get("deleted", 0),
        )


@dataclass
class ProjectKnowledgeItem:
    """A discrete unit of structured knowledge associated with a project."""
    item_id: str
    project_id: str
    category: KnowledgeCategory
    title: str
    content: str
    provenance: KnowledgeProvenance
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision: int = 1
    deleted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "project_id": self.project_id,
            "category": self.category.value,
            "title": self.title,
            "content": self.content,
            "provenance": self.provenance.to_dict(),
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectKnowledgeItem":
        return cls(
            item_id=data["item_id"],
            project_id=data["project_id"],
            category=KnowledgeCategory(data["category"]),
            title=data["title"],
            content=data["content"],
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            revision=data.get("revision", 1),
            deleted=data.get("deleted", 0),
        )


@dataclass
class ProjectKnowledgeRevision:
    """An immutable audit record of changes to a project knowledge item."""
    revision_id: str
    item_id: str
    project_id: str
    previous_content: str
    new_content: str
    provenance: KnowledgeProvenance
    changed_by: str = "owner"
    reason: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "item_id": self.item_id,
            "project_id": self.project_id,
            "previous_content": self.previous_content,
            "new_content": self.new_content,
            "provenance": self.provenance.to_dict(),
            "changed_by": self.changed_by,
            "reason": self.reason,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectKnowledgeRevision":
        return cls(
            revision_id=data["revision_id"],
            item_id=data["item_id"],
            project_id=data["project_id"],
            previous_content=data["previous_content"],
            new_content=data["new_content"],
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            changed_by=data.get("changed_by", "owner"),
            reason=data.get("reason", ""),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class RepositoryFileIndex:
    """Indexed file reference connecting project knowledge to codebase ground truth."""
    file_id: str
    project_id: str
    relative_path: str
    file_extension: str
    size_bytes: int
    content_hash: str
    last_modified: float
    indexed_at: float = field(default_factory=time.time)
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "project_id": self.project_id,
            "relative_path": self.relative_path,
            "file_extension": self.file_extension,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "last_modified": self.last_modified,
            "indexed_at": self.indexed_at,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryFileIndex":
        return cls(
            file_id=data["file_id"],
            project_id=data["project_id"],
            relative_path=data["relative_path"],
            file_extension=data["file_extension"],
            size_bytes=data["size_bytes"],
            content_hash=data["content_hash"],
            last_modified=data["last_modified"],
            indexed_at=data.get("indexed_at", time.time()),
            summary=data.get("summary"),
        )


@dataclass
class ProjectDiscoveryCandidate:
    """Inferred project context detected from conversational interactions."""
    candidate_name: str
    matched_project_id: Optional[str] = None
    confidence: float = 0.0  # 0.0 to 1.0
    is_new_project: bool = False
    evidence_terms: List[str] = field(default_factory=list)
    suggested_purpose: Optional[str] = None
    needs_owner_confirmation: bool = True
