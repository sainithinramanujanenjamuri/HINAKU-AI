"""
backend/intelligence/learning_types.py

Data contracts, enums, and validation logic for HINAKU Controlled Learning Foundation.
Provides structured tracking for user experience records, cataloged weaknesses,
and candidate improvement proposals without granting autonomous modification rights.

SAFETY INVARIANTS:
1. Data, Not Permissions: Experience records, weaknesses, and improvement proposals
   are descriptive audit data. They NEVER convey authority to modify code, prompts,
   or system configurations autonomously.
2. Inviolable Core Protection: Proposals attempting to alter core persona prompt
   (config/hinaku_persona.md), security policies, authentication, or privacy gates
   are strictly rejected with SafetyBoundaryViolation.
3. Decoupled Observation vs Inference: Observed user feedback is strictly distinguished
   from assistant-inferred failure classifications. Inferred classifications are hypotheses,
   never verified facts.
4. Secret Exclusion: Secret tokens, credentials, passwords, and private API keys
   are strictly forbidden from metadata and text fields.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
import time
from typing import Any, Dict, List, Optional, Set

from .errors import ContextSecurityViolation, SafetyBoundaryViolation
from .types import KnowledgeProvenance

# Prohibited secret key regexes (aligned with context security rules)
PROHIBITED_SECRET_KEY_REGEXES = [
    re.compile(r"(?i)(?:^|_)(?:auth|session|access|bearer|internal|id|refresh)?_?token(?:_|$)"),
    re.compile(r"(?i)^token$"),
    re.compile(r"(?i)(?:password|passwd|pwd|passcode)"),
    re.compile(r"(?i)(?:api_key|apikey|secret_key|private_key)"),
    re.compile(r"(?i)(?:^|_)secret(?:_|$)"),
    re.compile(r"(?i)^authorization$"),
    re.compile(r"(?i)^bearer$"),
]

# Inviolable protected targets that learning mechanisms can NEVER propose to modify
PROTECTED_TARGET_PATTERNS = [
    re.compile(r"(?i)hinaku_persona\.md"),
    re.compile(r"(?i)\bpersona\b.*(?:core|prompt|definition)"),
    re.compile(r"(?i)privacy_gate"),
    re.compile(r"(?i)outbound_privacy"),
    re.compile(r"(?i)\bauth(?:\.py|_service)?\b"),
    re.compile(r"(?i)critical_owner_action"),
    re.compile(r"(?i)assert_owner_session"),
]


class FeedbackType(str, Enum):
    """Categorization of explicit or observed feedback signals from the owner."""
    THUMBS_DOWN = "thumbs_down"          # Explicit negative rating
    USER_CORRECTION = "user_correction"  # Explicit conversational correction by owner
    ACCEPTED_EDIT = "accepted_edit"      # Owner edited the assistant's previous answer
    RETRIED_PROMPT = "retried_prompt"    # Owner repeated or rephrased immediately after unsatisfactory reply


class ErrorCategory(str, Enum):
    """Classified failure mode or weakness category."""
    FACTUAL_INACCURACY = "factual_inaccuracy"              # Erroneous facts or hallucinations
    TONE_DRIFT = "tone_drift"                              # Deviation from calm, observant persona
    OVER_VERBOSITY = "over_verbosity"                      # Excessive length, unnecessary filler
    INCOMPLETE_REASONING = "incomplete_reasoning"          # Missing logical steps or unsupported conclusions
    MISINTERPRETED_INSTRUCTION = "misinterpreted_instruction" # Failed to follow explicit user intent or constraint
    REPETITION = "repetition"                              # Redundant phrasing or cyclic explanations


class WeaknessSeverity(str, Enum):
    """Operational impact severity of an observed weakness."""
    LOW = "low"          # Minor stylistic imperfection or slight verbosity
    MEDIUM = "medium"    # Factual omission or partial instruction misunderstanding
    HIGH = "high"        # Significant inaccuracy, hallucinations, or repeated failure
    CRITICAL = "critical" # Safety risk or direct breach of owner preferences


class WeaknessStatus(str, Enum):
    """Lifecycle status of a cataloged weakness."""
    IDENTIFIED = "identified"      # Recognized from experience records; awaiting deeper analysis
    UNDER_REVIEW = "under_review"  # Currently undergoing pattern analysis or research
    PROPOSED_FIX = "proposed_fix"  # Linked to a formal ImprovementProposal
    RESOLVED = "resolved"          # Confirmed resolved through evaluated candidate improvement
    IGNORED = "ignored"            # Assessed and intentionally deprioritized or rejected by owner


class ProposalChangeCategory(str, Enum):
    """Target component category for candidate improvement proposals."""
    PROMPT_GUIDANCE = "prompt_guidance"        # Task-specific system instructions (non-core persona)
    RETRIEVAL_STRATEGY = "retrieval_strategy"  # Search / semantic context retrieval parameters
    FINE_TUNING_DATASET = "fine_tuning_dataset" # Curation rules for 6-month offline fine-tuning
    TOOL_USAGE = "tool_usage"                  # Tool invocation guidance or formatting
    SYSTEM_INSTRUCTION = "system_instruction"  # Non-persona operational guidance


class ProposalEvaluationStatus(str, Enum):
    """State of objective evaluation against benchmarks and golden test sets."""
    PENDING = "pending"        # Created; awaiting benchmark evaluation
    EVALUATING = "evaluating"  # Active in isolated benchmark run
    PASSED = "passed"          # Met all benchmark criteria with zero regression
    FAILED = "failed"          # Failed benchmark criteria or introduced regressions
    REJECTED = "rejected"      # Rejected during review or failed safety boundaries


class ProposalApprovalStatus(str, Enum):
    """Owner authorization status for a proposed candidate change."""
    PENDING_REVIEW = "pending_review"  # Awaiting explicit owner review
    APPROVED = "approved"              # Explicitly authorized by owner for deployment
    REJECTED = "rejected"              # Declined by owner


def _validate_safe_metadata(metadata: Dict[str, Any]) -> None:
    """Enforces that metadata does not contain sensitive tokens, passwords, or keys."""
    for key in metadata.keys():
        for pat in PROHIBITED_SECRET_KEY_REGEXES:
            if pat.search(key):
                raise ContextSecurityViolation(
                    f"Metadata key '{key}' matches forbidden secret or credential pattern."
                )


@dataclass
class ExperienceRecord:
    """
    Structured record of an observed interaction outcome or owner correction.
    Strictly decouples observed owner feedback from inferred failure classifications.
    """
    experience_id: str
    feedback_type: FeedbackType
    error_category: Optional[ErrorCategory] = None
    task_id: Optional[str] = None
    interaction_id: Optional[str] = None
    project_id: Optional[str] = None
    observed_user_feedback: str = ""       # Concrete words / action from the owner (observed fact)
    original_output_summary: str = ""      # Summary of assistant's output that prompted feedback
    inferred_failure_mode: Optional[str] = None # Working assistant hypothesis (NOT a verified fact)
    provenance: Optional[KnowledgeProvenance] = None
    confidence: float = 1.0                # Confidence in the failure classification (0.0 to 1.0)
    redacted: bool = False                 # Flag indicating text was checked for sensitive credentials
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Validates bounds, required fields, and security constraints."""
        if not self.experience_id or not self.experience_id.strip():
            raise ValueError("ExperienceRecord must have a non-empty 'experience_id'.")
        if not isinstance(self.feedback_type, FeedbackType):
            raise ValueError(f"Invalid feedback_type '{self.feedback_type}'. Must be a valid FeedbackType enum.")
        if self.error_category is not None and not isinstance(self.error_category, ErrorCategory):
            raise ValueError(f"Invalid error_category '{self.error_category}'. Must be a valid ErrorCategory enum.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence score {self.confidence} must be between 0.0 and 1.0.")
        if self.created_at <= 0:
            raise ValueError(f"Invalid timestamp {self.created_at}.")
        _validate_safe_metadata(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "feedback_type": self.feedback_type.value,
            "error_category": self.error_category.value if self.error_category else None,
            "task_id": self.task_id,
            "interaction_id": self.interaction_id,
            "project_id": self.project_id,
            "observed_user_feedback": self.observed_user_feedback,
            "original_output_summary": self.original_output_summary,
            "inferred_failure_mode": self.inferred_failure_mode,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "confidence": self.confidence,
            "redacted": self.redacted,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperienceRecord":
        prov = KnowledgeProvenance.from_dict(data["provenance"]) if data.get("provenance") else None
        err_cat = ErrorCategory(data["error_category"]) if data.get("error_category") else None
        return cls(
            experience_id=data["experience_id"],
            feedback_type=FeedbackType(data["feedback_type"]),
            error_category=err_cat,
            task_id=data.get("task_id"),
            interaction_id=data.get("interaction_id"),
            project_id=data.get("project_id"),
            observed_user_feedback=data.get("observed_user_feedback", ""),
            original_output_summary=data.get("original_output_summary", ""),
            inferred_failure_mode=data.get("inferred_failure_mode"),
            provenance=prov,
            confidence=float(data.get("confidence", 1.0)),
            redacted=bool(data.get("redacted", False)),
            metadata=data.get("metadata", {}),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass
class WeaknessRecord:
    """
    Cataloged systemic weakness or recurring failure mode aggregated from experience records.
    """
    weakness_id: str
    error_category: ErrorCategory
    description: str
    frequency: int = 1
    severity: WeaknessSeverity = WeaknessSeverity.MEDIUM
    supporting_experience_ids: List[str] = field(default_factory=list)
    confidence: float = 1.0
    first_observed_at: float = field(default_factory=time.time)
    last_observed_at: float = field(default_factory=time.time)
    status: WeaknessStatus = WeaknessStatus.IDENTIFIED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Validates consistency, timestamps, and confidence boundaries."""
        if not self.weakness_id or not self.weakness_id.strip():
            raise ValueError("WeaknessRecord must have a non-empty 'weakness_id'.")
        if not self.description or not self.description.strip():
            raise ValueError("WeaknessRecord must have a non-empty 'description'.")
        if not isinstance(self.error_category, ErrorCategory):
            raise ValueError(f"Invalid error_category '{self.error_category}'. Must be an ErrorCategory enum.")
        if not isinstance(self.severity, WeaknessSeverity):
            raise ValueError(f"Invalid severity '{self.severity}'. Must be a WeaknessSeverity enum.")
        if not isinstance(self.status, WeaknessStatus):
            raise ValueError(f"Invalid status '{self.status}'. Must be a WeaknessStatus enum.")
        if self.frequency < 1:
            raise ValueError(f"Frequency must be at least 1, got {self.frequency}.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence score {self.confidence} must be between 0.0 and 1.0.")
        if self.first_observed_at > self.last_observed_at:
            raise ValueError(
                f"first_observed_at ({self.first_observed_at}) cannot be later than "
                f"last_observed_at ({self.last_observed_at})."
            )
        _validate_safe_metadata(self.metadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weakness_id": self.weakness_id,
            "error_category": self.error_category.value,
            "description": self.description,
            "frequency": self.frequency,
            "severity": self.severity.value,
            "supporting_experience_ids": self.supporting_experience_ids,
            "confidence": self.confidence,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "status": self.status.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeaknessRecord":
        return cls(
            weakness_id=data["weakness_id"],
            error_category=ErrorCategory(data["error_category"]),
            description=data["description"],
            frequency=int(data.get("frequency", 1)),
            severity=WeaknessSeverity(data.get("severity", WeaknessSeverity.MEDIUM.value)),
            supporting_experience_ids=data.get("supporting_experience_ids", []),
            confidence=float(data.get("confidence", 1.0)),
            first_observed_at=float(data.get("first_observed_at", time.time())),
            last_observed_at=float(data.get("last_observed_at", time.time())),
            status=WeaknessStatus(data.get("status", WeaknessStatus.IDENTIFIED.value)),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ImprovementProposal:
    """
    Formal proposal for addressing cataloged weaknesses.
    
    INVARIANT: A proposal is strictly descriptive candidate data. It does NOT
    grant authority to deploy or execute changes without explicit owner confirmation.
    """
    proposal_id: str
    related_weakness_ids: List[str] = field(default_factory=list)
    description: str = ""
    change_category: ProposalChangeCategory = ProposalChangeCategory.PROMPT_GUIDANCE
    expected_benefit: str = ""
    potential_risks: str = ""
    evaluation_status: ProposalEvaluationStatus = ProposalEvaluationStatus.PENDING
    evaluation_results_ref: Optional[str] = None
    owner_approval_status: ProposalApprovalStatus = ProposalApprovalStatus.PENDING_REVIEW
    created_at: float = field(default_factory=time.time)
    provenance: Optional[KnowledgeProvenance] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Validates proposal data contracts and enforces inviolable safety boundaries."""
        if not self.proposal_id or not self.proposal_id.strip():
            raise ValueError("ImprovementProposal must have a non-empty 'proposal_id'.")
        if not isinstance(self.change_category, ProposalChangeCategory):
            raise ValueError(f"Invalid change_category '{self.change_category}'.")
        if not isinstance(self.evaluation_status, ProposalEvaluationStatus):
            raise ValueError(f"Invalid evaluation_status '{self.evaluation_status}'.")
        if not isinstance(self.owner_approval_status, ProposalApprovalStatus):
            raise ValueError(f"Invalid owner_approval_status '{self.owner_approval_status}'.")
        if self.created_at <= 0:
            raise ValueError(f"Invalid timestamp {self.created_at}.")

        _validate_safe_metadata(self.metadata)

        # Inviolable Safety Boundary Check:
        # A proposal CANNOT target core persona prompt, security policies, or privacy gates.
        combined_text = f"{self.description} {self.expected_benefit} {self.potential_risks} {str(self.metadata)}"
        for pat in PROTECTED_TARGET_PATTERNS:
            if pat.search(combined_text):
                raise SafetyBoundaryViolation(
                    f"Improvement proposal '{self.proposal_id}' targets inviolable core system component "
                    f"matching protected pattern '{pat.pattern}'. Self-modification of core identity, "
                    f"security policies, or privacy gates is strictly prohibited."
                )

    def is_authorized_to_execute(self) -> bool:
        """
        Anti-autonomy check.
        INVARIANT: An ImprovementProposal is NEVER autonomous permission to execute changes.
        Even when owner_approval_status is APPROVED, deployment requires explicit external owner workflow.
        """
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "related_weakness_ids": self.related_weakness_ids,
            "description": self.description,
            "change_category": self.change_category.value,
            "expected_benefit": self.expected_benefit,
            "potential_risks": self.potential_risks,
            "evaluation_status": self.evaluation_status.value,
            "evaluation_results_ref": self.evaluation_results_ref,
            "owner_approval_status": self.owner_approval_status.value,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImprovementProposal":
        prov = KnowledgeProvenance.from_dict(data["provenance"]) if data.get("provenance") else None
        return cls(
            proposal_id=data["proposal_id"],
            related_weakness_ids=data.get("related_weakness_ids", []),
            description=data.get("description", ""),
            change_category=ProposalChangeCategory(data["change_category"]),
            expected_benefit=data.get("expected_benefit", ""),
            potential_risks=data.get("potential_risks", ""),
            evaluation_status=ProposalEvaluationStatus(data.get("evaluation_status", ProposalEvaluationStatus.PENDING.value)),
            evaluation_results_ref=data.get("evaluation_results_ref"),
            owner_approval_status=ProposalApprovalStatus(data.get("owner_approval_status", ProposalApprovalStatus.PENDING_REVIEW.value)),
            created_at=float(data.get("created_at", time.time())),
            provenance=prov,
            metadata=data.get("metadata", {}),
        )
