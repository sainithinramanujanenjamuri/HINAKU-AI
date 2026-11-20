"""
backend/intelligence/project_engine.py

Project Intelligence Engine for HINAKU.
Coordinates project lifecycle, structured knowledge, repository grounding,
conversational project discovery, and domain-isolated context retrieval.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid

from .context import IntelligenceContext
from .errors import (
    DomainIsolationViolation,
    IntelligenceError,
    ProjectConfidentialityViolation,
    ProjectNotFoundError,
    ProvenanceError,
)
from .project_discovery import ProjectDiscovery
from .project_store import ProjectStore
from .project_types import (
    KnowledgeCategory,
    ProjectConfidentiality,
    ProjectDiscoveryCandidate,
    ProjectKnowledgeItem,
    ProjectKnowledgeRevision,
    ProjectRecord,
    ProjectStatus,
    RepositoryFileIndex,
)
from .repo_grounding import RepoGrounding
from .types import (
    ImplementationStatus,
    KnowledgeDomain,
    KnowledgeProvenance,
    SourceAuthority,
)


class ProjectEngine:
    """Unified engine for HINAKU Project Intelligence."""

    def __init__(self, db_path: Path):
        self.store = ProjectStore(db_path)

    # --------------------------------------------------------------------------
    # Project Identity & Lifecycle
    # --------------------------------------------------------------------------

    def register_project(
        self,
        name: str,
        purpose: str,
        description: str = "",
        tech_stack: Optional[List[str]] = None,
        repo_path: Optional[str] = None,
        confidentiality: ProjectConfidentiality = ProjectConfidentiality.INTERNAL,
        status: ProjectStatus = ProjectStatus.ACTIVE,
        project_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        """Registers a new project entity."""
        pid = project_id or name.lower().replace(" ", "-").replace("_", "-")
        record = ProjectRecord(
            project_id=pid,
            name=name,
            description=description,
            purpose=purpose,
            owner="owner",
            status=status,
            tech_stack=tech_stack or [],
            repo_path=repo_path,
            confidentiality=confidentiality,
            metadata=metadata or {},
        )
        return self.store.create_project(record)

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        return self.store.get_project(project_id)

    def list_projects(
        self,
        status: Optional[ProjectStatus] = None,
        include_deleted: bool = False,
    ) -> List[ProjectRecord]:
        return self.store.list_projects(status=status, include_deleted=include_deleted)

    def update_project(self, project_id: str, updates: Dict[str, Any]) -> ProjectRecord:
        return self.store.update_project(project_id, updates)

    def delete_project(
        self,
        project_id: str,
        hard_delete: bool = False,
        owner_confirmed: bool = False,
    ) -> bool:
        return self.store.delete_project(
            project_id=project_id,
            hard_delete=hard_delete,
            owner_confirmed=owner_confirmed,
        )

    def promote_provisional_project(
        self,
        project_id: str,
        owner_confirmed: bool = True,
    ) -> ProjectRecord:
        """Promotes a PROVISIONAL project to ACTIVE upon owner confirmation."""
        if not owner_confirmed:
            raise IntelligenceError("Project promotion requires explicit owner confirmation.")
        return self.update_project(project_id, {"status": ProjectStatus.ACTIVE})

    # --------------------------------------------------------------------------
    # Structured Project Knowledge & Decisions
    # --------------------------------------------------------------------------

    def add_knowledge(
        self,
        project_id: str,
        category: KnowledgeCategory,
        title: str,
        content: str,
        provenance: KnowledgeProvenance,
        tags: Optional[List[str]] = None,
    ) -> ProjectKnowledgeItem:
        """Adds a structured knowledge item with explicit provenance."""
        item = ProjectKnowledgeItem(
            item_id=str(uuid.uuid4()),
            project_id=project_id,
            category=category,
            title=title,
            content=content,
            provenance=provenance,
            tags=tags or [],
        )
        return self.store.add_knowledge_item(item)

    def record_decision(
        self,
        project_id: str,
        title: str,
        decision_content: str,
        authority: SourceAuthority = SourceAuthority.OWNER_DIRECTIVE,
        confidence: float = 1.0,
    ) -> ProjectKnowledgeItem:
        """
        Records an accepted architecture or design decision.
        ARCHITECTURAL INVARIANT: An accepted decision has status ACCEPTED, strictly NOT IMPLEMENTED.
        """
        provenance = KnowledgeProvenance(
            source_authority=authority,
            claim_confidence=confidence,
            verification_status=ImplementationStatus.ACCEPTED,
            implementation_evidence=None,
        )
        return self.add_knowledge(
            project_id=project_id,
            category=KnowledgeCategory.DECISIONS,
            title=title,
            content=decision_content,
            provenance=provenance,
            tags=["decision", "architecture"],
        )

    def record_implementation(
        self,
        project_id: str,
        title: str,
        implementation_content: str,
        evidence: Dict[str, Any],
        authority: SourceAuthority = SourceAuthority.ASSISTANT_SUGGESTION,
        confidence: float = 1.0,
        status: ImplementationStatus = ImplementationStatus.IMPLEMENTED,
    ) -> ProjectKnowledgeItem:
        """
        Records an implemented component or change.
        ARCHITECTURAL INVARIANT: Claiming IMPLEMENTED or VERIFIED strictly requires non-empty evidence.
        """
        if not evidence or not isinstance(evidence, dict):
            raise ProvenanceError("Implementation record requires concrete evidence.")

        provenance = KnowledgeProvenance(
            source_authority=authority,
            claim_confidence=confidence,
            verification_status=status,
            implementation_evidence=evidence,
        )
        return self.add_knowledge(
            project_id=project_id,
            category=KnowledgeCategory.IMPLEMENTATION,
            title=title,
            content=implementation_content,
            provenance=provenance,
            tags=["implementation", "codebase"],
        )

    def update_knowledge(
        self,
        item_id: str,
        new_content: str,
        provenance: KnowledgeProvenance,
        changed_by: str = "owner",
        reason: str = "",
    ) -> ProjectKnowledgeItem:
        """Updates a knowledge item and appends to the immutable audit revision log."""
        return self.store.update_knowledge_item(
            item_id=item_id,
            new_content=new_content,
            provenance=provenance,
            changed_by=changed_by,
            reason=reason,
        )

    def list_knowledge(
        self,
        project_id: str,
        category: Optional[KnowledgeCategory] = None,
    ) -> List[ProjectKnowledgeItem]:
        return self.store.list_knowledge_items(project_id, category=category)

    def get_revisions(self, item_id: str) -> List[ProjectKnowledgeRevision]:
        return self.store.get_knowledge_revisions(item_id)

    # --------------------------------------------------------------------------
    # Repository Grounding
    # --------------------------------------------------------------------------

    def index_project_repository(
        self,
        project_id: str,
        max_files: int = 500,
    ) -> List[RepositoryFileIndex]:
        """Indexes the files of an authorized repository for a project."""
        project = self.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")
        if not project.repo_path:
            raise IntelligenceError(f"Project '{project_id}' does not have a configured repo_path.")

        files = RepoGrounding.index_repository(
            project_id=project_id,
            repo_path=project.repo_path,
            max_files=max_files,
        )
        self.store.upsert_repo_files(project_id, files)
        return files

    def check_repository_staleness(self, project_id: str) -> Dict[str, List[str]]:
        """Detects whether indexed repository files are out-of-date compared to disk."""
        project = self.get_project(project_id)
        if not project or not project.repo_path:
            return {"modified": [], "deleted": []}

        indexed = self.store.list_repo_files(project_id)
        return RepoGrounding.detect_stale_files(project.repo_path, indexed)

    def generate_file_evidence_for_project(
        self,
        project_id: str,
        relative_path: str,
    ) -> Dict[str, Any]:
        """Generates implementation evidence for a file within the project repository."""
        project = self.get_project(project_id)
        if not project or not project.repo_path:
            raise IntelligenceError(f"Project '{project_id}' has no configured repository path.")
        return RepoGrounding.generate_file_evidence(project.repo_path, relative_path)

    # --------------------------------------------------------------------------
    # Conversational Project Discovery
    # --------------------------------------------------------------------------

    def discover_project_from_text(self, text: str) -> Optional[ProjectDiscoveryCandidate]:
        """Analyzes conversational text against existing projects or potential new declarations."""
        existing = self.list_projects()
        return ProjectDiscovery.analyze_conversation(text, existing)

    # --------------------------------------------------------------------------
    # Project Context Retrieval
    # --------------------------------------------------------------------------

    def retrieve_project_context(
        self,
        project_id: str,
        intelligence_context: IntelligenceContext,
        max_tokens: int = 1500,
    ) -> str:
        """
        Retrieves formatted project context for an intelligence operation.
        Strictly enforces domain isolation and project confidentiality rules.
        """
        # 1. Enforce domain boundary isolation
        intelligence_context.validate_domain_access(KnowledgeDomain.PROJECT)

        # 2. Verify project existence
        project = self.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")

        # 3. Confidentiality enforcement:
        # If project is CONFIDENTIAL or RESTRICTED, external API routing is prohibited
        if project.confidentiality in (ProjectConfidentiality.CONFIDENTIAL, ProjectConfidentiality.RESTRICTED):
            if intelligence_context.operation_constraints.get("allow_external_api", False):
                raise ProjectConfidentialityViolation(
                    f"Project '{project.name}' is classified as {project.confidentiality.value.upper()}. "
                    "External API transmission is strictly prohibited for confidential project intelligence."
                )

        # 4. Gather knowledge items
        knowledge_items = self.store.list_knowledge_items(project_id)

        # Group items by category
        decisions = [k for k in knowledge_items if k.category == KnowledgeCategory.DECISIONS]
        architecture = [k for k in knowledge_items if k.category == KnowledgeCategory.ARCHITECTURE]
        milestones = [k for k in knowledge_items if k.category == KnowledgeCategory.TASKS_MILESTONES]
        implementations = [k for k in knowledge_items if k.category == KnowledgeCategory.IMPLEMENTATION]

        # 5. Format compact markdown summary
        lines: List[str] = [
            f"### Project Context: {project.name} [{project.status.value.upper()}]",
            f"- **Purpose**: {project.purpose}",
            f"- **Confidentiality**: {project.confidentiality.value.upper()}",
        ]
        if project.tech_stack:
            lines.append(f"- **Tech Stack**: {', '.join(project.tech_stack)}")

        if architecture:
            lines.append("\n#### Architecture Notes:")
            for a in architecture[:3]:
                lines.append(f"- **{a.title}**: {a.content} (Conf: {a.provenance.claim_confidence})")

        if decisions:
            lines.append("\n#### Accepted Decisions:")
            for d in decisions[:4]:
                lines.append(
                    f"- **{d.title}**: {d.content} [{d.provenance.verification_status.value.upper()}, "
                    f"Authority: {d.provenance.source_authority.value}]"
                )

        if milestones:
            lines.append("\n#### Active Tasks & Milestones:")
            for m in milestones[:3]:
                lines.append(f"- **{m.title}**: {m.content}")

        if implementations:
            lines.append("\n#### Verified Implementation Records:")
            for imp in implementations[:3]:
                ev_str = "evidence attached" if imp.provenance.implementation_evidence else "no evidence"
                lines.append(f"- **{imp.title}**: {imp.content} [{imp.provenance.verification_status.value.upper()}, {ev_str}]")

        return "\n".join(lines)
