"""
backend/intelligence/contradiction_manager.py

Contradiction detection and factual reconciliation manager for HINAKU knowledge.
Enforces non-destructive factual updates by superseding outdated claims and linking
contradictory/superseding entities in the Knowledge Graph with full audit provenance.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from .errors import ContradictionResolutionError
from .graph_types import EdgeRelationship, KnowledgeEdge
from .knowledge_graph import KnowledgeGraph
from .types import ImplementationStatus, KnowledgeDomain, KnowledgeProvenance


class ContradictionManager:
    """Manages contradiction detection, audit logging, and factual superseding."""

    @classmethod
    def detect_direct_conflict(cls, claim_a: str, claim_b: str) -> bool:
        """
        Heuristic detection of direct contradiction between two statements.
        Detects common negation pairs, mutually exclusive settings, or conflicting directives.
        """
        a_clean = claim_a.lower().strip()
        b_clean = claim_b.lower().strip()

        if not a_clean or not b_clean or a_clean == b_clean:
            return False

        # 1. Direct explicit negation pairs (e.g. "prefers dark" vs "prefers light", "use postgres" vs "use sqlite")
        direct_negations = [
            (r"\benable\b", r"\bdisable\b"),
            (r"\ballow\b", r"\bforbid\b"),
            (r"\ballow\b", r"\bblock\b"),
            (r"\bdark\b", r"\blight\b"),
            (r"\blocal[-_ ]only\b", r"\bexternal[-_ ]api\b"),
            (r"\bsqlite\b", r"\bpostgres\b"),
            (r"\bsqlite\b", r"\bmysql\b"),
        ]

        for pos, neg in direct_negations:
            if (re.search(pos, a_clean) and re.search(neg, b_clean)) or (
                re.search(neg, a_clean) and re.search(pos, b_clean)
            ):
                return True

        # 2. Polar negation of identical phrases ("is X" vs "is not X")
        words_a = set(re.findall(r"\w+", a_clean))
        words_b = set(re.findall(r"\w+", b_clean))
        common = words_a.intersection(words_b)

        if len(common) >= 3:
            has_not_a = "not" in words_a or "never" in words_a
            has_not_b = "not" in words_b or "never" in words_b
            if has_not_a != has_not_b:
                return True

        return False

    @classmethod
    def record_contradiction(
        cls,
        graph: KnowledgeGraph,
        item_id_a: str,
        domain_a: KnowledgeDomain,
        item_id_b: str,
        domain_b: KnowledgeDomain,
        details: str = "",
    ) -> KnowledgeEdge:
        """Records an explicit contradiction edge between two conflicting knowledge entities."""
        edge = KnowledgeEdge(
            edge_id="",
            source_id=item_id_a,
            source_domain=domain_a,
            target_id=item_id_b,
            target_domain=domain_b,
            relationship=EdgeRelationship.CONTRADICTS,
            weight=1.0,
            metadata={"details": details},
        )
        return graph.add_edge(edge)

    @classmethod
    def resolve_by_superseding(
        cls,
        graph: KnowledgeGraph,
        old_id: str,
        old_domain: KnowledgeDomain,
        new_id: str,
        new_domain: KnowledgeDomain,
        resolution_reason: str,
    ) -> KnowledgeEdge:
        """
        Resolves a factual contradiction or outdated claim by marking the new entity
        as superseding the old entity.
        Returns the created SUPERSEDES KnowledgeEdge.
        """
        if old_id == new_id:
            raise ContradictionResolutionError("Cannot supersede an entity with itself.")

        # Create SUPERSEDES edge: new -> supersedes -> old
        return graph.record_superseded(
            old_id=old_id,
            old_domain=old_domain,
            new_id=new_id,
            new_domain=new_domain,
            reason=resolution_reason,
        )
