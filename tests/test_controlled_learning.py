"""
tests/test_controlled_learning.py

Unit test suite for Phase 1 Milestone 6: Controlled Learning Foundation (Step 1).
Validates:
- FeedbackType, ErrorCategory, WeaknessSeverity, WeaknessStatus, and Proposal enums.
- ExperienceRecord validation, confidence bounds, serialization, and secret metadata rejection.
- Separation of observed feedback from inferred failure classifications.
- WeaknessRecord validation, timestamp ordering, and lifecycle statuses.
- ImprovementProposal data contract, anti-autonomy invariants, and safety boundary violations.
- Distinguishable error hierarchy (SafetyBoundaryViolation vs ImprovementEvaluationError).
"""

import time
import pytest

from backend.intelligence.errors import (
    ContextSecurityViolation,
    CriticalApprovalRequiredError,
    ImprovementEvaluationError,
    IntelligenceError,
    SafetyBoundaryViolation,
)
from backend.intelligence.learning_types import (
    ErrorCategory,
    ExperienceRecord,
    FeedbackType,
    ImprovementProposal,
    ProposalApprovalStatus,
    ProposalChangeCategory,
    ProposalEvaluationStatus,
    WeaknessRecord,
    WeaknessSeverity,
    WeaknessStatus,
)
from backend.intelligence.experience_logger import ExperienceLogger
from backend.intelligence.weakness_catalog import WeaknessCatalog
from backend.intelligence.improvement_engine import ImprovementProposalEngine
from backend.intelligence.types import (
    ImplementationStatus,
    KnowledgeDomain,
    KnowledgeProvenance,
    SourceAuthority,
)


def test_learning_enums_values():
    assert FeedbackType.THUMBS_DOWN.value == "thumbs_down"
    assert FeedbackType.USER_CORRECTION.value == "user_correction"
    assert FeedbackType.ACCEPTED_EDIT.value == "accepted_edit"
    assert FeedbackType.RETRIED_PROMPT.value == "retried_prompt"

    assert ErrorCategory.FACTUAL_INACCURACY.value == "factual_inaccuracy"
    assert ErrorCategory.TONE_DRIFT.value == "tone_drift"
    assert ErrorCategory.OVER_VERBOSITY.value == "over_verbosity"
    assert ErrorCategory.INCOMPLETE_REASONING.value == "incomplete_reasoning"
    assert ErrorCategory.MISINTERPRETED_INSTRUCTION.value == "misinterpreted_instruction"
    assert ErrorCategory.REPETITION.value == "repetition"

    assert WeaknessStatus.IDENTIFIED.value == "identified"
    assert WeaknessStatus.UNDER_REVIEW.value == "under_review"
    assert WeaknessStatus.PROPOSED_FIX.value == "proposed_fix"
    assert WeaknessStatus.RESOLVED.value == "resolved"
    assert WeaknessStatus.IGNORED.value == "ignored"


def test_experience_record_valid_creation_and_roundtrip():
    prov = KnowledgeProvenance(
        source_authority=SourceAuthority.OWNER_DIRECTIVE,
        claim_confidence=1.0,
        verification_status=ImplementationStatus.VERIFIED,
        implementation_evidence={"verified_by": "owner_correction"},
    )
    rec = ExperienceRecord(
        experience_id="exp-001",
        feedback_type=FeedbackType.USER_CORRECTION,
        error_category=ErrorCategory.FACTUAL_INACCURACY,
        task_id="task-100",
        interaction_id="int-200",
        project_id="proj-hinaku",
        observed_user_feedback="You stated the model had 8GB VRAM, but RTX 4050 has 6GB VRAM.",
        original_output_summary="Assistant claimed HP V15 laptop has 8GB VRAM.",
        inferred_failure_mode="Hardware spec memory retrieval omission",
        provenance=prov,
        confidence=0.95,
        redacted=True,
        metadata={"source_turn": 3},
    )

    data = rec.to_dict()
    assert data["experience_id"] == "exp-001"
    assert data["feedback_type"] == "user_correction"
    assert data["error_category"] == "factual_inaccuracy"
    assert data["confidence"] == 0.95
    assert data["provenance"]["source_authority"] == "owner_directive"

    restored = ExperienceRecord.from_dict(data)
    assert restored.experience_id == rec.experience_id
    assert restored.feedback_type == FeedbackType.USER_CORRECTION
    assert restored.error_category == ErrorCategory.FACTUAL_INACCURACY
    assert restored.observed_user_feedback == rec.observed_user_feedback
    assert restored.inferred_failure_mode == rec.inferred_failure_mode
    assert restored.confidence == 0.95
    assert restored.redacted is True
    assert restored.provenance.source_authority == SourceAuthority.OWNER_DIRECTIVE


def test_experience_record_confidence_bounds_validation():
    # Valid bounds: 0.0 and 1.0
    rec_min = ExperienceRecord(experience_id="e1", feedback_type=FeedbackType.THUMBS_DOWN, confidence=0.0)
    assert rec_min.confidence == 0.0

    rec_max = ExperienceRecord(experience_id="e2", feedback_type=FeedbackType.THUMBS_DOWN, confidence=1.0)
    assert rec_max.confidence == 1.0

    # Invalid: < 0.0
    with pytest.raises(ValueError, match="Confidence score"):
        ExperienceRecord(experience_id="e_invalid", feedback_type=FeedbackType.THUMBS_DOWN, confidence=-0.1)

    # Invalid: > 1.0
    with pytest.raises(ValueError, match="Confidence score"):
        ExperienceRecord(experience_id="e_invalid2", feedback_type=FeedbackType.THUMBS_DOWN, confidence=1.05)


def test_experience_record_observed_vs_inferred_separation():
    """
    CRITICAL INVARIANT: Observed feedback from the owner is distinct from
    inferred failure modes, which are assistant hypotheses and not verified facts.
    """
    rec = ExperienceRecord(
        experience_id="exp-obs-1",
        feedback_type=FeedbackType.USER_CORRECTION,
        observed_user_feedback="Please keep your answer to 2 bullet points.",
        inferred_failure_mode="Hypothesis: prompt context lacks strict brevity token constraints",
        confidence=0.7,
    )
    # Observed feedback is factual record of owner directive
    assert "2 bullet points" in rec.observed_user_feedback
    # Inferred mode is explicitly labeled hypothesis with lower confidence
    assert rec.inferred_failure_mode.startswith("Hypothesis:")
    assert rec.confidence < 1.0


def test_experience_record_rejects_sensitive_metadata():
    """
    SECURITY REQUIREMENT: Sensitive tokens, passwords, and API keys must be rejected from metadata.
    """
    with pytest.raises(ContextSecurityViolation, match="forbidden secret or credential pattern"):
        ExperienceRecord(
            experience_id="exp-sec-1",
            feedback_type=FeedbackType.THUMBS_DOWN,
            metadata={"user_api_key": "sk-12345abcdef"},
        )

    with pytest.raises(ContextSecurityViolation, match="forbidden secret or credential pattern"):
        ExperienceRecord(
            experience_id="exp-sec-2",
            feedback_type=FeedbackType.THUMBS_DOWN,
            metadata={"auth_token": "token-xyz"},
        )

    with pytest.raises(ContextSecurityViolation, match="forbidden secret or credential pattern"):
        ExperienceRecord(
            experience_id="exp-sec-3",
            feedback_type=FeedbackType.THUMBS_DOWN,
            metadata={"password": "secret-pass-word"},
        )


def test_weakness_record_valid_creation_and_roundtrip():
    now = time.time()
    weakness = WeaknessRecord(
        weakness_id="weak-001",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Assistant repeats contextual background unnecessarily when answering follow-up queries.",
        frequency=3,
        severity=WeaknessSeverity.MEDIUM,
        supporting_experience_ids=["exp-001", "exp-002", "exp-003"],
        confidence=0.88,
        first_observed_at=now - 3600,
        last_observed_at=now,
        status=WeaknessStatus.UNDER_REVIEW,
        metadata={"domain": "general"},
    )

    data = weakness.to_dict()
    assert data["weakness_id"] == "weak-001"
    assert data["error_category"] == "over_verbosity"
    assert data["frequency"] == 3
    assert data["severity"] == "medium"
    assert data["status"] == "under_review"
    assert len(data["supporting_experience_ids"]) == 3

    restored = WeaknessRecord.from_dict(data)
    assert restored.weakness_id == weakness.weakness_id
    assert restored.error_category == ErrorCategory.OVER_VERBOSITY
    assert restored.frequency == 3
    assert restored.status == WeaknessStatus.UNDER_REVIEW


def test_weakness_record_validation():
    now = time.time()

    # Empty weakness_id raises ValueError
    with pytest.raises(ValueError, match="non-empty 'weakness_id'"):
        WeaknessRecord(
            weakness_id="",
            error_category=ErrorCategory.REPETITION,
            description="Repeats phrases",
        )

    # Empty description raises ValueError
    with pytest.raises(ValueError, match="non-empty 'description'"):
        WeaknessRecord(
            weakness_id="w-1",
            error_category=ErrorCategory.REPETITION,
            description="",
        )

    # Frequency < 1 raises ValueError
    with pytest.raises(ValueError, match="Frequency must be at least 1"):
        WeaknessRecord(
            weakness_id="w-2",
            error_category=ErrorCategory.REPETITION,
            description="Repeats phrases",
            frequency=0,
        )

    # first_observed_at > last_observed_at raises ValueError
    with pytest.raises(ValueError, match="cannot be later than"):
        WeaknessRecord(
            weakness_id="w-3",
            error_category=ErrorCategory.REPETITION,
            description="Repeats phrases",
            first_observed_at=now + 100,
            last_observed_at=now,
        )


def test_improvement_proposal_valid_creation_and_roundtrip():
    proposal = ImprovementProposal(
        proposal_id="prop-001",
        related_weakness_ids=["weak-001"],
        description="Inject concise bullet-point guidance in task-specific prompt templates.",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Reduces reply token length by ~20% on conversational turns.",
        potential_risks="May omit nuanced caveats if query requires deep technical explanation.",
        evaluation_status=ProposalEvaluationStatus.PENDING,
        owner_approval_status=ProposalApprovalStatus.PENDING_REVIEW,
        metadata={"candidate_revision": "v1.1"},
    )

    data = proposal.to_dict()
    assert data["proposal_id"] == "prop-001"
    assert data["change_category"] == "prompt_guidance"
    assert data["evaluation_status"] == "pending"
    assert data["owner_approval_status"] == "pending_review"

    restored = ImprovementProposal.from_dict(data)
    assert restored.proposal_id == proposal.proposal_id
    assert restored.change_category == ProposalChangeCategory.PROMPT_GUIDANCE
    assert restored.evaluation_status == ProposalEvaluationStatus.PENDING
    assert restored.owner_approval_status == ProposalApprovalStatus.PENDING_REVIEW


def test_improvement_proposal_anti_autonomy_invariant():
    """
    CRITICAL INVARIANT: An ImprovementProposal is data, never authorization to execute changes.
    Even with owner_approval_status = APPROVED, is_authorized_to_execute() must return False.
    """
    proposal = ImprovementProposal(
        proposal_id="prop-approved",
        description="Update temperature setting for creative coding tasks.",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        owner_approval_status=ProposalApprovalStatus.APPROVED,
    )
    # Anti-autonomy check
    assert proposal.is_authorized_to_execute() is False


def test_improvement_proposal_safety_boundary_violation():
    """
    INVIOLABLE SAFETY BOUNDARY: Learning mechanisms can NEVER propose to modify
    the core persona prompt (config/hinaku_persona.md), privacy gate, or authentication systems.
    """
    # 1. Attempting to modify persona prompt
    with pytest.raises(SafetyBoundaryViolation, match="targets inviolable core system component"):
        ImprovementProposal(
            proposal_id="prop-persona-tamper",
            description="Modify config/hinaku_persona.md to make HINAKU more cheerful and talkative.",
            change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        )

    # 2. Attempting to modify privacy gate
    with pytest.raises(SafetyBoundaryViolation, match="targets inviolable core system component"):
        ImprovementProposal(
            proposal_id="prop-privacy-tamper",
            description="Bypass outbound_privacy gate for faster web search replies.",
            change_category=ProposalChangeCategory.SYSTEM_INSTRUCTION,
        )

    # 3. Attempting to alter auth or critical owner actions
    with pytest.raises(SafetyBoundaryViolation, match="targets inviolable core system component"):
        ImprovementProposal(
            proposal_id="prop-auth-tamper",
            description="Disable assert_owner_session check to automate file modifications.",
            change_category=ProposalChangeCategory.SYSTEM_INSTRUCTION,
        )


def test_error_hierarchy_and_distinguishability():
    """
    Verifies that SafetyBoundaryViolation and ImprovementEvaluationError are distinct
    subclasses of IntelligenceError.
    """
    assert issubclass(SafetyBoundaryViolation, IntelligenceError)
    assert issubclass(ImprovementEvaluationError, IntelligenceError)
    assert SafetyBoundaryViolation is not ImprovementEvaluationError

    # Distinction check
    try:
        raise SafetyBoundaryViolation("Security policy violated")
    except ImprovementEvaluationError:
        pytest.fail("SafetyBoundaryViolation should not be caught as ImprovementEvaluationError")
    except SafetyBoundaryViolation as e:
        assert "Security policy violated" in str(e)


def test_experience_logger_persistence_and_retrieval(tmp_path):
    db_file = tmp_path / "learning.db"
    logger = ExperienceLogger(db_file)

    rec = ExperienceRecord(
        experience_id="exp-persist-1",
        feedback_type=FeedbackType.THUMBS_DOWN,
        error_category=ErrorCategory.INCOMPLETE_REASONING,
        task_id="task-42",
        observed_user_feedback="The calculation stopped halfway without showing the final sum.",
        original_output_summary="Assistant stopped after step 2.",
        confidence=0.9,
        metadata={"model": "gemma3:4b"},
    )

    saved = logger.log_experience(rec)
    assert saved.experience_id == "exp-persist-1"

    loaded = logger.get_experience("exp-persist-1")
    assert loaded is not None
    assert loaded.experience_id == "exp-persist-1"
    assert loaded.feedback_type == FeedbackType.THUMBS_DOWN
    assert loaded.error_category == ErrorCategory.INCOMPLETE_REASONING
    assert loaded.task_id == "task-42"
    assert loaded.observed_user_feedback == rec.observed_user_feedback
    assert loaded.metadata == {"model": "gemma3:4b"}


def test_experience_logger_redacts_sensitive_credentials(tmp_path):
    db_file = tmp_path / "learning_redact.db"
    logger = ExperienceLogger(db_file)

    # Observed feedback containing card number and password
    rec = ExperienceRecord(
        experience_id="exp-sec-redact",
        feedback_type=FeedbackType.USER_CORRECTION,
        observed_user_feedback="Don't print my password is supersecret123 or card 4111 2222 3333 4444 in logs.",
        original_output_summary="Assistant echoed password is supersecret123 back.",
    )

    saved = logger.log_experience(rec)
    assert saved.redacted is True
    assert "supersecret123" not in saved.observed_user_feedback
    assert "[removed]" in saved.observed_user_feedback
    assert "4111 2222 3333 4444" not in saved.observed_user_feedback

    # Confirm database row contains redacted text, never plaintext secret
    loaded = logger.get_experience("exp-sec-redact")
    assert loaded is not None
    assert loaded.redacted is True
    assert "supersecret123" not in loaded.observed_user_feedback
    assert "[removed]" in loaded.observed_user_feedback


def test_experience_logger_log_from_feedback_helper(tmp_path):
    db_file = tmp_path / "learning_helper.db"
    logger = ExperienceLogger(db_file)

    rec = logger.log_from_feedback(
        feedback_type=FeedbackType.ACCEPTED_EDIT,
        observed_feedback="Owner corrected formatting of JSON payload.",
        original_output="Malformed JSON with trailing comma.",
        interaction_id="int-99",
        project_id="proj-hinaku",
        inferred_error=ErrorCategory.MISINTERPRETED_INSTRUCTION,
        inferred_mode="JSON schema formatting error",
    )

    assert rec.experience_id.startswith("exp_")
    assert rec.feedback_type == FeedbackType.ACCEPTED_EDIT
    assert rec.error_category == ErrorCategory.MISINTERPRETED_INSTRUCTION
    assert rec.project_id == "proj-hinaku"

    loaded = logger.get_experience(rec.experience_id)
    assert loaded is not None
    assert loaded.experience_id == rec.experience_id


def test_experience_logger_list_and_count_filters(tmp_path):
    db_file = tmp_path / "learning_filters.db"
    logger = ExperienceLogger(db_file)

    logger.log_from_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        observed_feedback="Too long",
        original_output="Long essay",
        inferred_error=ErrorCategory.OVER_VERBOSITY,
        project_id="p1",
    )
    logger.log_from_feedback(
        feedback_type=FeedbackType.THUMBS_DOWN,
        observed_feedback="Hallucinated date",
        original_output="Incorrect year",
        inferred_error=ErrorCategory.FACTUAL_INACCURACY,
        project_id="p1",
    )
    logger.log_from_feedback(
        feedback_type=FeedbackType.USER_CORRECTION,
        observed_feedback="Not quite",
        original_output="Off topic",
        inferred_error=ErrorCategory.MISINTERPRETED_INSTRUCTION,
        project_id="p2",
    )

    assert logger.count_experiences() == 3
    assert logger.count_experiences(feedback_type=FeedbackType.THUMBS_DOWN) == 2
    assert logger.count_experiences(error_category=ErrorCategory.OVER_VERBOSITY) == 1
    assert logger.count_experiences(project_id="p1") == 2

    # Query list
    p1_records = logger.list_experiences(project_id="p1")
    assert len(p1_records) == 2

    thumbs_down_records = logger.list_experiences(feedback_type=FeedbackType.THUMBS_DOWN)
    assert len(thumbs_down_records) == 2


def test_experience_logger_delete_and_clear_all(tmp_path):
    db_file = tmp_path / "learning_delete.db"
    logger = ExperienceLogger(db_file)

    rec1 = logger.log_from_feedback(FeedbackType.THUMBS_DOWN, "Bad", "Bad")
    rec2 = logger.log_from_feedback(FeedbackType.USER_CORRECTION, "Correction", "Bad")

    assert logger.count_experiences() == 2

    # Delete single
    deleted = logger.delete_experience(rec1.experience_id)
    assert deleted is True
    assert logger.get_experience(rec1.experience_id) is None
    assert logger.count_experiences() == 1

    # Clear all (full-wipe support)
    cleared_count = logger.clear_all_experiences()
    assert cleared_count == 1
    assert logger.count_experiences() == 0


def test_weakness_catalog_register_and_retrieve(tmp_path):
    db_file = tmp_path / "weakness_reg.db"
    catalog = WeaknessCatalog(db_file)

    now = time.time()
    w = WeaknessRecord(
        weakness_id="weak-reg-1",
        error_category=ErrorCategory.TONE_DRIFT,
        description="Assistant became overly enthusiastic or apologetic instead of composed.",
        frequency=1,
        severity=WeaknessSeverity.MEDIUM,
        supporting_experience_ids=["exp-01"],
        first_observed_at=now,
        last_observed_at=now,
        status=WeaknessStatus.IDENTIFIED,
    )

    saved = catalog.register_weakness(w)
    assert saved.weakness_id == "weak-reg-1"

    loaded = catalog.get_weakness("weak-reg-1")
    assert loaded is not None
    assert loaded.weakness_id == "weak-reg-1"
    assert loaded.error_category == ErrorCategory.TONE_DRIFT
    assert loaded.severity == WeaknessSeverity.MEDIUM
    assert loaded.status == WeaknessStatus.IDENTIFIED


def test_weakness_catalog_auto_cluster_from_experience(tmp_path):
    db_file = tmp_path / "weakness_cluster.db"
    catalog = WeaknessCatalog(db_file)

    # Experience 1: First occurrence creates new weakness
    exp1 = ExperienceRecord(
        experience_id="exp-c1",
        feedback_type=FeedbackType.USER_CORRECTION,
        error_category=ErrorCategory.FACTUAL_INACCURACY,
        observed_user_feedback="The port number was 8000, not 5000.",
        inferred_failure_mode="Hallucinated default port number",
        confidence=0.9,
    )
    w1 = catalog.catalog_experience(exp1)
    assert w1 is not None
    assert w1.frequency == 1
    assert w1.error_category == ErrorCategory.FACTUAL_INACCURACY
    assert w1.supporting_experience_ids == ["exp-c1"]
    assert w1.status == WeaknessStatus.IDENTIFIED

    # Experience 2: Same category clusters into existing active weakness
    exp2 = ExperienceRecord(
        experience_id="exp-c2",
        feedback_type=FeedbackType.THUMBS_DOWN,
        error_category=ErrorCategory.FACTUAL_INACCURACY,
        observed_user_feedback="Wrong URL path.",
        confidence=0.95,
    )
    w2 = catalog.catalog_experience(exp2)
    assert w2 is not None
    assert w2.weakness_id == w1.weakness_id
    assert w2.frequency == 2
    assert "exp-c1" in w2.supporting_experience_ids
    assert "exp-c2" in w2.supporting_experience_ids

    # Additional experiences escalate severity
    for i in range(3, 7):
        exp_next = ExperienceRecord(
            experience_id=f"exp-c{i}",
            feedback_type=FeedbackType.THUMBS_DOWN,
            error_category=ErrorCategory.FACTUAL_INACCURACY,
        )
        catalog.catalog_experience(exp_next)

    escalated = catalog.get_weakness(w1.weakness_id)
    assert escalated.frequency == 6
    assert escalated.severity == WeaknessSeverity.HIGH


def test_weakness_catalog_status_transitions(tmp_path):
    db_file = tmp_path / "weakness_status.db"
    catalog = WeaknessCatalog(db_file)

    w = WeaknessRecord(
        weakness_id="weak-stat-1",
        error_category=ErrorCategory.MISINTERPRETED_INSTRUCTION,
        description="Fails to apply negative constraints.",
        frequency=2,
    )
    catalog.register_weakness(w)

    # Transition to UNDER_REVIEW
    reviewed = catalog.update_status("weak-stat-1", WeaknessStatus.UNDER_REVIEW)
    assert reviewed.status == WeaknessStatus.UNDER_REVIEW

    # Transition to PROPOSED_FIX
    proposed = catalog.update_status("weak-stat-1", WeaknessStatus.PROPOSED_FIX)
    assert proposed.status == WeaknessStatus.PROPOSED_FIX

    # Transition to RESOLVED with resolution note
    resolved = catalog.update_status(
        "weak-stat-1",
        WeaknessStatus.RESOLVED,
        resolution_note="Added negative constraint verification prompt rule."
    )
    assert resolved.status == WeaknessStatus.RESOLVED
    assert resolved.metadata["resolution_note"] == "Added negative constraint verification prompt rule."


def test_weakness_catalog_list_and_count_filters(tmp_path):
    db_file = tmp_path / "weakness_filters.db"
    catalog = WeaknessCatalog(db_file)

    catalog.register_weakness(WeaknessRecord(
        weakness_id="w-1",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Too verbose",
        status=WeaknessStatus.IDENTIFIED,
        severity=WeaknessSeverity.LOW,
        frequency=1,
    ))
    catalog.register_weakness(WeaknessRecord(
        weakness_id="w-2",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Extremely verbose",
        status=WeaknessStatus.UNDER_REVIEW,
        severity=WeaknessSeverity.HIGH,
        frequency=5,
    ))
    catalog.register_weakness(WeaknessRecord(
        weakness_id="w-3",
        error_category=ErrorCategory.TONE_DRIFT,
        description="Too eager",
        status=WeaknessStatus.RESOLVED,
        severity=WeaknessSeverity.MEDIUM,
        frequency=2,
    ))

    assert catalog.count_weaknesses() == 3
    assert catalog.count_weaknesses(status=WeaknessStatus.IDENTIFIED) == 1
    assert catalog.count_weaknesses(error_category=ErrorCategory.OVER_VERBOSITY) == 2

    active_verbosity = catalog.list_weaknesses(error_category=ErrorCategory.OVER_VERBOSITY)
    assert len(active_verbosity) == 2
    # Ordered by frequency desc
    assert active_verbosity[0].weakness_id == "w-2"
    assert active_verbosity[1].weakness_id == "w-1"


def test_weakness_catalog_delete_and_clear_all(tmp_path):
    db_file = tmp_path / "weakness_del.db"
    catalog = WeaknessCatalog(db_file)

    catalog.register_weakness(WeaknessRecord(
        weakness_id="w-del-1",
        error_category=ErrorCategory.REPETITION,
        description="Repeats",
    ))
    catalog.register_weakness(WeaknessRecord(
        weakness_id="w-del-2",
        error_category=ErrorCategory.TONE_DRIFT,
        description="Drifts",
    ))

    assert catalog.count_weaknesses() == 2

    # Delete single
    assert catalog.delete_weakness("w-del-1") is True
    assert catalog.get_weakness("w-del-1") is None
    assert catalog.count_weaknesses() == 1

    # Clear all
    assert catalog.clear_all_weaknesses() == 1
    assert catalog.count_weaknesses() == 0


def test_improvement_engine_create_and_retrieve_proposal(tmp_path):
    db_file = tmp_path / "learning_engine.db"
    catalog = WeaknessCatalog(db_file)
    engine = ImprovementProposalEngine(db_file, weakness_catalog=catalog)

    # Setup weakness
    catalog.register_weakness(WeaknessRecord(
        weakness_id="weak-target-1",
        error_category=ErrorCategory.TONE_DRIFT,
        description="Overly enthusiastic phrasing",
        status=WeaknessStatus.UNDER_REVIEW,
    ))

    prop = engine.create_proposal(
        description="Include explicit reminder to maintain composed, unhurried tone.",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Restores signature composed tone.",
        potential_risks="None identified.",
        related_weakness_ids=["weak-target-1"],
        candidate_changes={"prompt_rule": "Tone must remain cool, observant, and measured."},
    )

    assert prop.proposal_id.startswith("prop_")
    assert prop.change_category == ProposalChangeCategory.PROMPT_GUIDANCE
    assert prop.evaluation_status == ProposalEvaluationStatus.PENDING
    assert prop.owner_approval_status == ProposalApprovalStatus.PENDING_REVIEW

    # Invariant: Weakness transitions to PROPOSED_FIX
    updated_weakness = catalog.get_weakness("weak-target-1")
    assert updated_weakness.status == WeaknessStatus.PROPOSED_FIX

    # Retrieve from engine
    loaded = engine.get_proposal(prop.proposal_id)
    assert loaded is not None
    assert loaded.proposal_id == prop.proposal_id
    assert loaded.related_weakness_ids == ["weak-target-1"]


def test_improvement_engine_rejects_protected_targets(tmp_path):
    """
    INVIOLABLE SAFETY BOUNDARY:
    Attempting to propose modifications to core persona prompt or security gates MUST FAIL.
    """
    db_file = tmp_path / "learning_safety.db"
    engine = ImprovementProposalEngine(db_file)

    # 1. Proposing to modify hinaku_persona.md in description
    with pytest.raises(SafetyBoundaryViolation, match="targets inviolable core system component"):
        engine.create_proposal(
            description="Update config/hinaku_persona.md with cheerful greetings.",
            change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
            expected_benefit="Cheerier tone",
            potential_risks="Breaches persona",
        )

    # 2. Proposing to modify privacy_gate in candidate_changes
    with pytest.raises(SafetyBoundaryViolation, match="target protected core system components"):
        engine.create_proposal(
            description="Allow outbound data for live weather.",
            change_category=ProposalChangeCategory.SYSTEM_INSTRUCTION,
            expected_benefit="Weather updates",
            potential_risks="Privacy breach",
            candidate_changes={"target_file": "backend/models/privacy_gate.py"},
        )


def test_improvement_engine_isolated_evaluation_passed(tmp_path):
    db_file = tmp_path / "learning_eval_pass.db"
    engine = ImprovementProposalEngine(db_file)

    prop = engine.create_proposal(
        description="Concise bullet guidance",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Brevity",
        potential_risks="None",
    )

    test_cases = [
        {"id": "t1", "baseline_pass": True, "simulate_candidate_fail": False},
        {"id": "t2", "baseline_pass": True, "simulate_candidate_fail": False},
        {"id": "t3", "baseline_pass": True, "simulate_candidate_fail": False},
    ]

    eval_result = engine.evaluate_proposal(prop.proposal_id, test_cases=test_cases)
    assert eval_result["evaluation_passed"] is True
    assert eval_result["regressions"] == 0
    assert eval_result["score"] == 1.0

    updated = engine.get_proposal(prop.proposal_id)
    assert updated.evaluation_status == ProposalEvaluationStatus.PASSED


def test_improvement_engine_isolated_evaluation_failed_on_regression(tmp_path):
    """
    ZERO REGRESSION GATE:
    Any regression on previously passing baseline cases causes evaluation failure.
    """
    db_file = tmp_path / "learning_eval_fail.db"
    engine = ImprovementProposalEngine(db_file)

    prop = engine.create_proposal(
        description="Aggressive truncation",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Extreme brevity",
        potential_risks="Loss of vital details",
    )

    test_cases = [
        {"id": "t1", "baseline_pass": True, "simulate_candidate_fail": False},
        {"id": "t2", "baseline_pass": True, "simulate_candidate_fail": True},  # Regression!
    ]

    eval_result = engine.evaluate_proposal(prop.proposal_id, test_cases=test_cases)
    assert eval_result["evaluation_passed"] is False
    assert eval_result["regressions"] == 1

    updated = engine.get_proposal(prop.proposal_id)
    assert updated.evaluation_status == ProposalEvaluationStatus.FAILED


def test_improvement_engine_owner_decision_and_controlled_deployment(tmp_path):
    db_file = tmp_path / "learning_deploy.db"
    catalog = WeaknessCatalog(db_file)
    engine = ImprovementProposalEngine(db_file, weakness_catalog=catalog)

    catalog.register_weakness(WeaknessRecord(
        weakness_id="weak-res-1",
        error_category=ErrorCategory.OVER_VERBOSITY,
        description="Repeats context in replies",
        status=WeaknessStatus.UNDER_REVIEW,
    ))

    prop = engine.create_proposal(
        description="Reduce conversational context repetition",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Concise replies",
        potential_risks="Minimal",
        related_weakness_ids=["weak-res-1"],
    )

    # 1. Run evaluation to pass
    engine.evaluate_proposal(prop.proposal_id)
    assert engine.get_proposal(prop.proposal_id).evaluation_status == ProposalEvaluationStatus.PASSED

    # 2. Attempting to deploy without owner approval or confirmation raises error
    with pytest.raises(CriticalApprovalRequiredError, match="strictly requires explicit owner confirmation"):
        engine.deploy_approved_proposal(prop.proposal_id, owner_confirmed=False)

    # 3. Owner approves proposal
    engine.record_owner_decision(prop.proposal_id, approved=True, owner_comment="LGTM")
    approved_prop = engine.get_proposal(prop.proposal_id)
    assert approved_prop.owner_approval_status == ProposalApprovalStatus.APPROVED

    # 4. Deploy with explicit owner confirmation
    deploy_receipt = engine.deploy_approved_proposal(prop.proposal_id, owner_confirmed=True)
    assert deploy_receipt["deployed"] is True
    assert deploy_receipt["resolved_weakness_count"] == 1

    # Invariant: Related weakness transitions to RESOLVED
    resolved_weakness = catalog.get_weakness("weak-res-1")
    assert resolved_weakness.status == WeaknessStatus.RESOLVED


def test_improvement_engine_rejected_proposal_unblocks_weakness(tmp_path):
    db_file = tmp_path / "learning_unblock.db"
    catalog = WeaknessCatalog(db_file)
    engine = ImprovementProposalEngine(db_file, weakness_catalog=catalog)

    catalog.register_weakness(WeaknessRecord(
        weakness_id="weak-rej-1",
        error_category=ErrorCategory.TONE_DRIFT,
        description="Over-apologetic responses",
        status=WeaknessStatus.UNDER_REVIEW,
    ))

    prop = engine.create_proposal(
        description="Force sarcasm in tone",
        change_category=ProposalChangeCategory.PROMPT_GUIDANCE,
        expected_benefit="Different tone",
        potential_risks="Hostile replies",
        related_weakness_ids=["weak-rej-1"],
    )

    assert catalog.get_weakness("weak-rej-1").status == WeaknessStatus.PROPOSED_FIX

    # Owner rejects the proposal
    engine.record_owner_decision(prop.proposal_id, approved=False, owner_comment="Too hostile.")

    rejected_prop = engine.get_proposal(prop.proposal_id)
    assert rejected_prop.owner_approval_status == ProposalApprovalStatus.REJECTED

    # Invariant: Weakness is unblocked and returns to UNDER_REVIEW
    reverted_weakness = catalog.get_weakness("weak-rej-1")
    assert reverted_weakness.status == WeaknessStatus.UNDER_REVIEW



