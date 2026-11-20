"""
backend/intelligence/graph_types.py

Data structures, enums, and models for the HINAKU Knowledge Graph and Multi-Domain Context Bundles.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional

from .types import KnowledgeDomain


class EdgeRelationship(str, Enum):
    """Semantic relationship types between knowledge entities across or within domains."""
    DEPENDS_ON = "depends_on"    # Entity A requires Entity B to function or be completed
    IMPLEMENTS = "implements"    # Code / component A realizes decision / requirement B
    SUPERSEDES = "supersedes"    # Newer fact A replaces / invalidates older fact B
    CONTRADICTS = "contradicts"  # Fact A directly conflicts with Fact B
    RELATES_TO = "relates_to"    # General semantic association


@dataclass
class KnowledgeEdge:
    """Directed semantic edge connecting knowledge entities across or within domains."""
    edge_id: str
    source_id: str
    source_domain: KnowledgeDomain
    target_id: str
    target_domain: KnowledgeDomain
    relationship: EdgeRelationship
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "source_domain": self.source_domain.value,
            "target_id": self.target_id,
            "target_domain": self.target_domain.value,
            "relationship": self.relationship.value,
            "weight": self.weight,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeEdge":
        return cls(
            edge_id=data["edge_id"],
            source_id=data["source_id"],
            source_domain=KnowledgeDomain(data["source_domain"]),
            target_id=data["target_id"],
            target_domain=KnowledgeDomain(data["target_domain"]),
            relationship=EdgeRelationship(data["relationship"]),
            weight=float(data.get("weight", 1.0)),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class ContextBundle:
    """Domain-segregated contextual payload assembled for reasoning or prompt synthesis."""
    query: str
    personal_context: Optional[str] = None
    project_context: Optional[str] = None
    general_context: Optional[str] = None
    decision_context: Optional[str] = None
    active_project_id: Optional[str] = None
    provenance_records: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "personal_context": self.personal_context,
            "project_context": self.project_context,
            "general_context": self.general_context,
            "decision_context": self.decision_context,
            "active_project_id": self.active_project_id,
            "provenance_records": self.provenance_records,
            "created_at": self.created_at,
        }

    def render_prompt_context(self) -> str:
        """Renders cleanly segregated markdown sections for model prompting without cross-domain pollution."""
        sections: List[str] = []

        if self.personal_context and self.personal_context.strip():
            sections.append(f"### Personal Memory (Owner Context)\n{self.personal_context.strip()}")

        if self.project_context and self.project_context.strip():
            sections.append(f"### Project Context\n{self.project_context.strip()}")

        if self.general_context and self.general_context.strip():
            sections.append(f"### Reference Documentation\n{self.general_context.strip()}")

        if self.decision_context and self.decision_context.strip():
            sections.append(f"### Decision History\n{self.decision_context.strip()}")

        return "\n\n".join(sections)
