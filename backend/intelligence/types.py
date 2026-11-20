"""
backend/intelligence/types.py

Foundational types, enums, and data contracts for the HINAKU Intelligence Core.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Set

from .errors import ProvenanceError


class KnowledgeDomain(str, Enum):
    """Isolated knowledge domains supported by HINAKU."""
    PERSONAL = "personal"       # Owner habits, preferences, hardware specs (strictly local)
    PROJECT = "project"         # Project architectures, decisions, requirements, tasks
    GENERAL = "general"         # Ingested reference documentation, library APIs, research
    DECISION = "decision"       # Append-only ledger of choices, trade-offs, and historical outcomes


class SourceAuthority(str, Enum):
    """The authoritative origin of a specific piece of knowledge or assertion."""
    OWNER_DIRECTIVE = "owner_directive"       # Owner-sourced assertion; not automatically an independently verified fact
    ASSISTANT_SUGGESTION = "assistant_suggestion" # HINAKU-generated working proposal or recommendation
    EXTERNAL_SOURCE = "external_source"       # External documentation, specifications, or codebase files


class ImplementationStatus(str, Enum):
    """The lifecycle and implementation state of a decision, feature, or knowledge claim."""
    PROPOSED = "proposed"       # Initial working idea or suggestion
    ACCEPTED = "accepted"       # Owner-approved decision; strictly NOT an implemented change
    IN_PROGRESS = "in_progress" # Implementation active but incomplete
    IMPLEMENTED = "implemented" # Implementation claimed; requires verifiable evidence
    VERIFIED = "verified"       # Independently verified through tests, file existence, or execution


class TaskPriority(str, Enum):
    """Priority levels for cognitive planning and tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    """Lifecycle states for planned tasks."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    PENDING_APPROVAL = "pending_approval"


@dataclass
class KnowledgeProvenance:
    """
    Decoupled provenance properties for knowledge items, decisions, and claims.
    Enforces that source authority, claim confidence, verification status, and evidence
    remain independent, orthogonal properties.
    """
    source_authority: SourceAuthority
    claim_confidence: float  # Evidential certainty in this specific claim (0.0 to 1.0)
    verification_status: ImplementationStatus = ImplementationStatus.PROPOSED
    implementation_evidence: Optional[Dict[str, Any]] = None
    source_turn_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        # Validate confidence range
        if not (0.0 <= self.claim_confidence <= 1.0):
            raise ProvenanceError(f"Claim confidence must be between 0.0 and 1.0, got {self.claim_confidence}")

        # Invariant: Claiming IMPLEMENTED or VERIFIED strictly requires non-empty implementation evidence
        if self.verification_status in (ImplementationStatus.IMPLEMENTED, ImplementationStatus.VERIFIED):
            if not self.implementation_evidence or not isinstance(self.implementation_evidence, dict):
                raise ProvenanceError(
                    f"Implementation status '{self.verification_status.value}' strictly requires concrete implementation evidence (e.g. test proofs, file hashes)."
                )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_authority": self.source_authority.value,
            "claim_confidence": self.claim_confidence,
            "verification_status": self.verification_status.value,
            "implementation_evidence": self.implementation_evidence,
            "source_turn_id": self.source_turn_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeProvenance":
        return cls(
            source_authority=SourceAuthority(data["source_authority"]),
            claim_confidence=float(data["claim_confidence"]),
            verification_status=ImplementationStatus(data.get("verification_status", ImplementationStatus.PROPOSED.value)),
            implementation_evidence=data.get("implementation_evidence"),
            source_turn_id=data.get("source_turn_id"),
            created_at=data.get("created_at", time.time()),
        )


@dataclass
class CognitiveTask:
    """Represents a discrete planned task or sub-objective."""
    task_id: str
    title: str
    domain: KnowledgeDomain
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    description: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    assigned_model: Optional[str] = None
    provenance: Optional[KnowledgeProvenance] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "domain": self.domain.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "description": self.description,
            "dependencies": self.dependencies,
            "assigned_model": self.assigned_model,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveTask":
        prov = KnowledgeProvenance.from_dict(data["provenance"]) if data.get("provenance") else None
        return cls(
            task_id=data["task_id"],
            title=data["title"],
            domain=KnowledgeDomain(data["domain"]),
            priority=TaskPriority(data.get("priority", TaskPriority.MEDIUM.value)),
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            description=data.get("description"),
            dependencies=data.get("dependencies", []),
            assigned_model=data.get("assigned_model"),
            provenance=prov,
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class ReasoningStep:
    """A single cognitive reasoning milestone or hypothesis evaluation."""
    step_number: int
    sub_goal: str
    hypotheses: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    findings: str = ""
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "sub_goal": self.sub_goal,
            "hypotheses": self.hypotheses,
            "assumptions": self.assumptions,
            "unknowns": self.unknowns,
            "findings": self.findings,
            "confidence": self.confidence,
        }


@dataclass
class ReasoningResult:
    """The synthesized conclusion and findings from a multi-step reasoning plan."""
    plan_id: str
    conclusion: str
    steps: List[ReasoningStep] = field(default_factory=list)
    assumptions_made: List[str] = field(default_factory=list)
    unresolved_unknowns: List[str] = field(default_factory=list)
    confidence_score: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "conclusion": self.conclusion,
            "steps": [s.to_dict() for s in self.steps],
            "assumptions_made": self.assumptions_made,
            "unresolved_unknowns": self.unresolved_unknowns,
            "confidence_score": self.confidence_score,
        }
