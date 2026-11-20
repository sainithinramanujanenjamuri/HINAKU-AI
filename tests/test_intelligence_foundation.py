"""
tests/test_intelligence_foundation.py

Unit test suite for Phase 1 Milestone 1: Intelligence Architecture Foundation.
Verifies data contracts, provenance invariants, domain isolation,
context security boundaries, and serialization.
"""

import pytest

from backend.intelligence.errors import (
    IntelligenceError,
    ProvenanceError,
    DomainIsolationViolation,
    ContextSecurityViolation,
)
from backend.intelligence.types import (
    KnowledgeDomain,
    SourceAuthority,
    ImplementationStatus,
    TaskPriority,
    TaskStatus,
    KnowledgeProvenance,
    CognitiveTask,
    ReasoningStep,
    ReasoningResult,
)
from backend.intelligence.context import IntelligenceContext


# ==============================================================================
# 1. Enums and Domain Definitions
# ==============================================================================
def test_knowledge_domain_enums():
    """Verify standard KnowledgeDomain values."""
    assert KnowledgeDomain.PERSONAL.value == "personal"
    assert KnowledgeDomain.PROJECT.value == "project"
    assert KnowledgeDomain.GENERAL.value == "general"
    assert KnowledgeDomain.DECISION.value == "decision"


def test_provenance_enums():
    """Verify SourceAuthority and ImplementationStatus values."""
    assert SourceAuthority.OWNER_DIRECTIVE.value == "owner_directive"
    assert SourceAuthority.ASSISTANT_SUGGESTION.value == "assistant_suggestion"
    assert SourceAuthority.EXTERNAL_SOURCE.value == "external_source"

    assert ImplementationStatus.PROPOSED.value == "proposed"
    assert ImplementationStatus.ACCEPTED.value == "accepted"
    assert ImplementationStatus.IN_PROGRESS.value == "in_progress"
    assert ImplementationStatus.IMPLEMENTED.value == "implemented"
    assert ImplementationStatus.VERIFIED.value == "verified"


# ==============================================================================
# 2. Knowledge Provenance Invariants & Confidence Semantics
# ==============================================================================
def test_provenance_valid_initialization():
    """Verify normal initialization of KnowledgeProvenance."""
    prov = KnowledgeProvenance(
        source_authority=SourceAuthority.OWNER_DIRECTIVE,
        claim_confidence=0.85,
        verification_status=ImplementationStatus.PROPOSED
    )
    assert prov.source_authority == SourceAuthority.OWNER_DIRECTIVE
    assert prov.claim_confidence == 0.85
    assert prov.verification_status == ImplementationStatus.PROPOSED
    assert prov.implementation_evidence is None


def test_provenance_claim_confidence_bounds():
    """Verify claim confidence must strictly be within 0.0 and 1.0."""
    # Under lower bound
    with pytest.raises(ProvenanceError) as exc_under:
        KnowledgeProvenance(
            source_authority=SourceAuthority.ASSISTANT_SUGGESTION,
            claim_confidence=-0.1
        )
    assert "between 0.0 and 1.0" in str(exc_under.value)

    # Over upper bound
    with pytest.raises(ProvenanceError) as exc_over:
        KnowledgeProvenance(
            source_authority=SourceAuthority.ASSISTANT_SUGGESTION,
            claim_confidence=1.05
        )
    assert "between 0.0 and 1.0" in str(exc_over.value)


def test_provenance_implementation_evidence_required_for_implemented():
    """
    CRITICAL PROVENANCE RULE:
    Claiming implementation status (IMPLEMENTED or VERIFIED) strictly requires
    concrete implementation evidence (e.g. test proofs, file hashes).
    """
    # Attempting IMPLEMENTED without evidence raises ProvenanceError
    with pytest.raises(ProvenanceError) as exc_no_evidence:
        KnowledgeProvenance(
            source_authority=SourceAuthority.ASSISTANT_SUGGESTION,
            claim_confidence=0.9,
            verification_status=ImplementationStatus.IMPLEMENTED,
            implementation_evidence=None
        )
    assert "concrete implementation evidence" in str(exc_no_evidence.value)

    # Attempting VERIFIED with empty evidence dict raises ProvenanceError
    with pytest.raises(ProvenanceError):
        KnowledgeProvenance(
            source_authority=SourceAuthority.OWNER_DIRECTIVE,
            claim_confidence=1.0,
            verification_status=ImplementationStatus.VERIFIED,
            implementation_evidence={}
        )

    # Supplying actual evidence dict succeeds
    valid_evidence = {
        "test_suite": "tests/test_authorization.py",
        "passed": True,
        "commit_sha": "98aab84"
    }
    prov = KnowledgeProvenance(
        source_authority=SourceAuthority.OWNER_DIRECTIVE,
        claim_confidence=1.0,
        verification_status=ImplementationStatus.VERIFIED,
        implementation_evidence=valid_evidence
    )
    assert prov.verification_status == ImplementationStatus.VERIFIED
    assert prov.implementation_evidence["passed"] is True


def test_provenance_owner_assertion_is_not_automatically_implemented():
    """
    An owner directive is owner-sourced, but remains an assertion (PROPOSED / ACCEPTED)
    until verified evidence exists.
    """
    prov = KnowledgeProvenance(
        source_authority=SourceAuthority.OWNER_DIRECTIVE,
        claim_confidence=1.0,
        verification_status=ImplementationStatus.ACCEPTED
    )
    assert prov.source_authority == SourceAuthority.OWNER_DIRECTIVE
    assert prov.verification_status == ImplementationStatus.ACCEPTED
    assert prov.verification_status != ImplementationStatus.IMPLEMENTED


def test_provenance_serialization_roundtrip():
    """Verify KnowledgeProvenance to_dict and from_dict serialization."""
    prov = KnowledgeProvenance(
        source_authority=SourceAuthority.EXTERNAL_SOURCE,
        claim_confidence=0.95,
        verification_status=ImplementationStatus.VERIFIED,
        implementation_evidence={"verified_by": "compiler"},
        source_turn_id="turn_123"
    )
    data = prov.to_dict()
    assert data["source_authority"] == "external_source"
    assert data["claim_confidence"] == 0.95
    assert data["verification_status"] == "verified"

    restored = KnowledgeProvenance.from_dict(data)
    assert restored.source_authority == SourceAuthority.EXTERNAL_SOURCE
    assert restored.claim_confidence == 0.95
    assert restored.verification_status == ImplementationStatus.VERIFIED
    assert restored.implementation_evidence == {"verified_by": "compiler"}
    assert restored.source_turn_id == "turn_123"


# ==============================================================================
# 3. Intelligence Context Security & Domain Isolation
# ==============================================================================
def test_intelligence_context_default_initialization():
    """Verify default IntelligenceContext has all standard domains and safe actor."""
    ctx = IntelligenceContext()
    assert ctx.actor_id == "owner"
    assert ctx.conversation_id is None
    assert ctx.active_project_id is None
    assert KnowledgeDomain.PERSONAL in ctx.permitted_domains
    assert KnowledgeDomain.PROJECT in ctx.permitted_domains
    assert KnowledgeDomain.GENERAL in ctx.permitted_domains
    assert KnowledgeDomain.DECISION in ctx.permitted_domains


def test_intelligence_context_domain_isolation():
    """Verify validate_domain_access enforces domain boundary rules."""
    # Context restricted to project and general domains only (no personal data)
    ctx = IntelligenceContext(
        permitted_domains={KnowledgeDomain.PROJECT, KnowledgeDomain.GENERAL}
    )

    # Permitted domains pass
    ctx.validate_domain_access(KnowledgeDomain.PROJECT)
    ctx.validate_domain_access(KnowledgeDomain.GENERAL)

    # Personal and Decision domains are rejected
    with pytest.raises(DomainIsolationViolation) as exc_personal:
        ctx.validate_domain_access(KnowledgeDomain.PERSONAL)
    assert "access to 'personal' knowledge domain is not permitted" in str(exc_personal.value)

    with pytest.raises(DomainIsolationViolation):
        ctx.validate_domain_access(KnowledgeDomain.DECISION)


def test_intelligence_context_security_rejects_credentials_and_tokens():
    """
    CRITICAL SECURITY INVARIANT:
    IntelligenceContext must NEVER store session tokens, passwords, api keys, or authorization secrets.
    Attempting to store sensitive keys or candidate token values must raise ContextSecurityViolation.
    """
    # Prohibited key in operation_constraints
    with pytest.raises(ContextSecurityViolation) as exc_token_key:
        IntelligenceContext(
            operation_constraints={"session_token": "abc1234567890abcdef1234567890abcdef"}
        )
    assert "prohibited authorization pattern" in str(exc_token_key.value)

    with pytest.raises(ContextSecurityViolation):
        IntelligenceContext(
            operation_constraints={"api_key": "some_secret_key"}
        )

    with pytest.raises(ContextSecurityViolation):
        IntelligenceContext(
            metadata={"admin_password": "super_secret_value"}
        )

    with pytest.raises(ContextSecurityViolation):
        IntelligenceContext(
            operation_constraints={"authorization": "Bearer xyz"}
        )

    # Prohibited token value in string value
    with pytest.raises(ContextSecurityViolation) as exc_token_val:
        IntelligenceContext(
            metadata={"ref": "hinaku_internal_scheduler_token_value"}
        )
    assert "contains an authorization token" in str(exc_token_val.value)


def test_intelligence_context_serialization_roundtrip():
    """Verify IntelligenceContext to_dict and from_dict roundtrip."""
    ctx = IntelligenceContext(
        actor_id="owner",
        conversation_id="conv_abc_123",
        active_project_id="proj_hinaku_ai",
        permitted_domains={KnowledgeDomain.PROJECT, KnowledgeDomain.GENERAL},
        operation_constraints={"max_tokens": 1024, "allow_external_egress": False},
        metadata={"session_label": "review"}
    )
    data = ctx.to_dict()
    assert data["actor_id"] == "owner"
    assert data["conversation_id"] == "conv_abc_123"
    assert data["active_project_id"] == "proj_hinaku_ai"
    assert set(data["permitted_domains"]) == {"project", "general"}
    assert data["operation_constraints"]["allow_external_egress"] is False

    restored = IntelligenceContext.from_dict(data)
    assert restored.actor_id == "owner"
    assert restored.conversation_id == "conv_abc_123"
    assert restored.active_project_id == "proj_hinaku_ai"
    assert restored.permitted_domains == {KnowledgeDomain.PROJECT, KnowledgeDomain.GENERAL}
    assert restored.operation_constraints == {"max_tokens": 1024, "allow_external_egress": False}


# ==============================================================================
# 4. Cognitive Tasks and Reasoning Primitives
# ==============================================================================
def test_cognitive_task_lifecycle_and_serialization():
    """Verify CognitiveTask instantiation and serialization."""
    task = CognitiveTask(
        task_id="task_001",
        title="Inspect database integrity",
        domain=KnowledgeDomain.PROJECT,
        priority=TaskPriority.HIGH,
        status=TaskStatus.PENDING,
        dependencies=["task_000"],
        assigned_model="bonsai-2:9b"
    )
    assert task.status == TaskStatus.PENDING
    assert task.priority == TaskPriority.HIGH

    d = task.to_dict()
    assert d["task_id"] == "task_001"
    assert d["domain"] == "project"

    restored = CognitiveTask.from_dict(d)
    assert restored.task_id == "task_001"
    assert restored.priority == TaskPriority.HIGH
    assert restored.dependencies == ["task_000"]


def test_reasoning_step_and_result_contracts():
    """Verify ReasoningStep and ReasoningResult data contracts."""
    step1 = ReasoningStep(
        step_number=1,
        sub_goal="Decompose user request into tasks",
        hypotheses=["Request requires project context"],
        assumptions=["Active project is HINAKU"],
        unknowns=["Target deployment environment"],
        findings="Verified local laptop architecture",
        confidence=0.9
    )
    assert step1.step_number == 1
    assert step1.confidence == 0.9

    result = ReasoningResult(
        plan_id="plan_xyz",
        conclusion="Decomposition complete; 3 subtasks queued.",
        steps=[step1],
        assumptions_made=["Active project is HINAKU"],
        unresolved_unknowns=["Target deployment environment"],
        confidence_score=0.9
    )
    d = result.to_dict()
    assert d["plan_id"] == "plan_xyz"
    assert len(d["steps"]) == 1
    assert d["steps"][0]["step_number"] == 1
    assert d["confidence_score"] == 0.9
