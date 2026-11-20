"""
backend/intelligence/decision_types.py

Data structures, enums, and models for the HINAKU Decision Engine.
Supports structured evaluation of objectives, alternatives, uncertainty, and recommendations.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional

from .types import (
    ImplementationStatus,
    KnowledgeDomain,
    KnowledgeProvenance,
    SourceAuthority,
)


class DecisionStatus(str, Enum):
    """Lifecycle states for structured decision records."""
    PROPOSED = "proposed"       # Initial decision topic framed
    EVALUATING = "evaluating"   # Under active alternative and uncertainty analysis
    RECOMMENDED = "recommended" # Formal recommendation generated; awaiting owner decision
    APPROVED = "approved"       # Explicitly approved by owner (strictly NOT implemented yet)
    REJECTED = "rejected"       # Declined or dismissed by owner
    SUPERSEDED = "superseded"   # Replaced by newer or updated decision


class UncertaintyLevel(str, Enum):
    """Calibrated levels of evidential uncertainty."""
    LOW = "low"            # Established facts dominate; proceed with high confidence
    MODERATE = "moderate"  # Working assumptions present; investigation useful
    HIGH = "high"          # Significant unknowns or conflicting evidence; clarification needed
    CRITICAL = "critical"  # Severe lack of evidence or high risk; owner decision mandatory


class CriticalActionCategory(str, Enum):
    """The six mandatory owner-approval categories that unconditionally require explicit consent."""
    FILE_MODIFICATION_OR_DELETION = "file_modification_or_deletion"
    FINANCIAL_TRANSACTION = "financial_transaction"
    EXTERNAL_COMMUNICATION = "external_communication"
    SYSTEM_OPERATION = "system_operation"
    SECURITY_OR_CREDENTIAL_CHANGE = "security_or_credential_change"
    SELF_MODIFICATION = "self_modification"


@dataclass
class AlternativeEvaluation:
    """An analyzed option or solution under consideration."""
    alternative_id: str
    title: str
    description: str
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    risk_assessment: str = ""
    reversibility: str = "high"  # "high", "medium", "low"
    resource_cost: str = "low"   # "low", "medium", "high"
    alignment_with_goals: str = ""
    score: float = 0.0
    score_explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alternative_id": self.alternative_id,
            "title": self.title,
            "description": self.description,
            "pros": self.pros,
            "cons": self.cons,
            "risk_assessment": self.risk_assessment,
            "reversibility": self.reversibility,
            "resource_cost": self.resource_cost,
            "alignment_with_goals": self.alignment_with_goals,
            "score": self.score,
            "score_explanation": self.score_explanation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlternativeEvaluation":
        return cls(
            alternative_id=data["alternative_id"],
            title=data["title"],
            description=data["description"],
            pros=data.get("pros", []),
            cons=data.get("cons", []),
            risk_assessment=data.get("risk_assessment", ""),
            reversibility=data.get("reversibility", "high"),
            resource_cost=data.get("resource_cost", "low"),
            alignment_with_goals=data.get("alignment_with_goals", ""),
            score=float(data.get("score", 0.0)),
            score_explanation=data.get("score_explanation"),
        )


@dataclass
class UncertaintyAssessment:
    """Rigorous evidential classification of facts, assumptions, and unknowns."""
    level: UncertaintyLevel
    known_facts: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    conflicting_evidence: List[str] = field(default_factory=list)
    clarification_needed: bool = False
    suggested_investigation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "known_facts": self.known_facts,
            "assumptions": self.assumptions,
            "unknowns": self.unknowns,
            "conflicting_evidence": self.conflicting_evidence,
            "clarification_needed": self.clarification_needed,
            "suggested_investigation": self.suggested_investigation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UncertaintyAssessment":
        return cls(
            level=UncertaintyLevel(data["level"]),
            known_facts=data.get("known_facts", []),
            assumptions=data.get("assumptions", []),
            unknowns=data.get("unknowns", []),
            conflicting_evidence=data.get("conflicting_evidence", []),
            clarification_needed=bool(data.get("clarification_needed", False)),
            suggested_investigation=data.get("suggested_investigation"),
        )


@dataclass
class DecisionRecommendation:
    """Synthesized conclusion and recommended path forward."""
    recommended_alternative_id: str
    summary: str
    justification: str
    contingencies: List[str] = field(default_factory=list)
    key_risks: List[str] = field(default_factory=list)
    requires_owner_approval: bool = False
    critical_action_category: Optional[CriticalActionCategory] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_alternative_id": self.recommended_alternative_id,
            "summary": self.summary,
            "justification": self.justification,
            "contingencies": self.contingencies,
            "key_risks": self.key_risks,
            "requires_owner_approval": self.requires_owner_approval,
            "critical_action_category": (
                self.critical_action_category.value if self.critical_action_category else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionRecommendation":
        cat = (
            CriticalActionCategory(data["critical_action_category"])
            if data.get("critical_action_category")
            else None
        )
        return cls(
            recommended_alternative_id=data["recommended_alternative_id"],
            summary=data["summary"],
            justification=data["justification"],
            contingencies=data.get("contingencies", []),
            key_risks=data.get("key_risks", []),
            requires_owner_approval=bool(data.get("requires_owner_approval", False)),
            critical_action_category=cat,
        )


@dataclass
class DecisionRecord:
    """Persistent entity representing a structured decision problem, evaluation, and outcome."""
    decision_id: str
    title: str
    problem_statement: str
    status: DecisionStatus
    uncertainty: UncertaintyAssessment
    alternatives: List[AlternativeEvaluation]
    recommendation: Optional[DecisionRecommendation]
    provenance: KnowledgeProvenance
    project_id: Optional[str] = None
    owner_decision: Optional[str] = None  # e.g. "approved", "rejected", "overridden"
    owner_notes: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision: int = 1
    deleted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "project_id": self.project_id,
            "title": self.title,
            "problem_statement": self.problem_statement,
            "status": self.status.value,
            "uncertainty": self.uncertainty.to_dict(),
            "alternatives": [a.to_dict() for a in self.alternatives],
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
            "owner_decision": self.owner_decision,
            "owner_notes": self.owner_notes,
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionRecord":
        return cls(
            decision_id=data["decision_id"],
            project_id=data.get("project_id"),
            title=data["title"],
            problem_statement=data["problem_statement"],
            status=DecisionStatus(data["status"]),
            uncertainty=UncertaintyAssessment.from_dict(data["uncertainty"]),
            alternatives=[AlternativeEvaluation.from_dict(a) for a in data.get("alternatives", [])],
            recommendation=(
                DecisionRecommendation.from_dict(data["recommendation"])
                if data.get("recommendation")
                else None
            ),
            owner_decision=data.get("owner_decision"),
            owner_notes=data.get("owner_notes"),
            provenance=KnowledgeProvenance.from_dict(data["provenance"]),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            revision=data.get("revision", 1),
            deleted=data.get("deleted", 0),
        )
