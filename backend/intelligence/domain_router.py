"""
backend/intelligence/domain_router.py

Domain-isolated memory and knowledge router for HINAKU.
Dispatches queries across the four isolated knowledge domains (PERSONAL, PROJECT, GENERAL, DECISION),
strictly preventing cross-domain leakage and unauthorized egress of personal/confidential facts.
"""

from typing import Any, Dict, List, Optional, Set

from .context import IntelligenceContext
from .errors import (
    CrossDomainLeakageError,
    DomainIsolationViolation,
    ProjectConfidentialityViolation,
)
from .graph_types import ContextBundle
from .project_engine import ProjectEngine
from .project_types import ProjectConfidentiality
from .types import KnowledgeDomain


class DomainRouter:
    """Dispatches knowledge retrieval across isolated domains and synthesizes segregated ContextBundles."""

    def __init__(
        self,
        project_engine: Optional[ProjectEngine] = None,
        memory_storage: Optional[Any] = None,
    ):
        self.project_engine = project_engine
        self.memory_storage = memory_storage

    def retrieve_context_bundle(
        self,
        query: str,
        intelligence_context: IntelligenceContext,
        target_domains: Optional[Set[KnowledgeDomain]] = None,
        project_id: Optional[str] = None,
        max_tokens_per_domain: int = 1000,
    ) -> ContextBundle:
        """
        Retrieves knowledge from authorized domains and packages them into a domain-segregated ContextBundle.
        Strictly enforces domain isolation and egress boundaries.
        """
        # Determine effective domains (intersection of permitted domains and requested domains)
        requested = target_domains or intelligence_context.permitted_domains
        effective_domains: Set[KnowledgeDomain] = set()

        for d in requested:
            domain_enum = d if isinstance(d, KnowledgeDomain) else KnowledgeDomain(str(d).lower())
            # Enforce that domain is permitted in the context
            intelligence_context.validate_domain_access(domain_enum)
            effective_domains.add(domain_enum)

        allow_api = intelligence_context.operation_constraints.get("allow_external_api", False)

        bundle = ContextBundle(
            query=query,
            active_project_id=project_id or intelligence_context.active_project_id,
        )

        # 1. PERSONAL DOMAIN (Strictly Local)
        if KnowledgeDomain.PERSONAL in effective_domains:
            if allow_api:
                raise CrossDomainLeakageError(
                    "Cross-domain security violation: Personal owner memory cannot be retrieved "
                    "or included when external API transmission is permitted."
                )
            bundle.personal_context = self._retrieve_personal_context(query)
            if bundle.personal_context:
                bundle.provenance_records.append({
                    "domain": KnowledgeDomain.PERSONAL.value,
                    "retrieved": True,
                    "egress_allowed": False,
                })

        # 2. PROJECT DOMAIN
        effective_pid = project_id or intelligence_context.active_project_id
        if KnowledgeDomain.PROJECT in effective_domains and effective_pid and self.project_engine:
            bundle.project_context = self._retrieve_project_context(
                effective_pid,
                intelligence_context,
                max_tokens=max_tokens_per_domain,
            )
            if bundle.project_context:
                bundle.provenance_records.append({
                    "domain": KnowledgeDomain.PROJECT.value,
                    "project_id": effective_pid,
                    "retrieved": True,
                })

        # 3. GENERAL DOMAIN (Reference Documents)
        if KnowledgeDomain.GENERAL in effective_domains:
            bundle.general_context = self._retrieve_general_context(query)
            if bundle.general_context:
                bundle.provenance_records.append({
                    "domain": KnowledgeDomain.GENERAL.value,
                    "retrieved": True,
                })

        # 4. DECISION DOMAIN (Historical Decisions Ledger)
        if KnowledgeDomain.DECISION in effective_domains and effective_pid and self.project_engine:
            bundle.decision_context = self._retrieve_decision_context(effective_pid)
            if bundle.decision_context:
                bundle.provenance_records.append({
                    "domain": KnowledgeDomain.DECISION.value,
                    "project_id": effective_pid,
                    "retrieved": True,
                })

        return bundle

    def _retrieve_personal_context(self, query: str) -> Optional[str]:
        """Retrieves personal owner facts using the memory storage layer."""
        if not self.memory_storage:
            return None
        try:
            # Check for memory storage retrieve_relevant or direct sqlite queries
            if hasattr(self.memory_storage, "retrieve_relevant"):
                memories = self.memory_storage.retrieve_relevant(query, limit=5)
                if memories:
                    return "\n".join(f"- {m.text if hasattr(m, 'text') else str(m)}" for m in memories)
            elif hasattr(self.memory_storage, "list_memories"):
                memories = self.memory_storage.list_memories()
                if memories:
                    return "\n".join(f"- {m.get('text', '')}" for m in memories[:5])
        except Exception:
            return None
        return None

    def _retrieve_project_context(
        self,
        project_id: str,
        context: IntelligenceContext,
        max_tokens: int,
    ) -> Optional[str]:
        """Retrieves project context via ProjectEngine while enforcing confidentiality rules."""
        if not self.project_engine:
            return None
        return self.project_engine.retrieve_project_context(
            project_id=project_id,
            intelligence_context=context,
            max_tokens=max_tokens,
        )

    def _retrieve_general_context(self, query: str) -> Optional[str]:
        """Retrieves general reference documentation (placeholder for attachment search)."""
        return None

    def _retrieve_decision_context(self, project_id: str) -> Optional[str]:
        """Retrieves recorded architectural decisions from the project engine."""
        if not self.project_engine:
            return None
        from .project_types import KnowledgeCategory
        items = self.project_engine.list_knowledge(project_id, category=KnowledgeCategory.DECISIONS)
        if not items:
            return None
        lines = []
        for d in items[:5]:
            lines.append(f"- **{d.title}**: {d.content} [{d.provenance.verification_status.value}]")
        return "\n".join(lines)
