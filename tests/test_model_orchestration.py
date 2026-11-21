"""
tests/test_model_orchestration.py

Comprehensive test suite for Phase 1 Milestone 5: Adaptive Model Orchestration.
Validates:
- Centralized ModelRegistry CRUD and passive discovery gating (PENDING_REVIEW).
- CapabilityAssessor capability matching, context capacity, and 6GB VRAM ceiling.
- ModelOrchestrator task-aware model selection, privacy gating, and safe fallback.
- Invariant: Local-only / confidential tasks NEVER fall back to cloud models.
- Invariant: Manual overrides cannot violate privacy or hardware boundaries.
- Sequential multi-model verification.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.intelligence.errors import (
    HardwareConstraintViolation,
    ModelExecutionError,
    ModelSelectionError,
)
from backend.intelligence.context import IntelligenceContext
from backend.intelligence.model_registry import ModelRegistry
from backend.intelligence.capability_assessor import CapabilityAssessor
from backend.intelligence.model_orchestrator import ModelOrchestrator
from backend.intelligence.orchestrator_types import (
    ModelApprovalStatus,
    ModelAvailability,
    ModelCapability,
    ModelExecutionTarget,
    ModelMetadata,
    TaskRequirements,
)
from backend.intelligence.project_types import ProjectConfidentiality, ProjectConfidentiality as ProjectConfidentialityLevel
from backend.models.privacy_gate import OutboundPrivacyViolation


def test_model_registry_initialization_and_crud():
    registry = ModelRegistry()

    # Verify canonical models initialized
    assert registry.get_model("gemma3:4b") is not None
    assert registry.get_model("bonsai-2:9b") is not None
    assert registry.get_model("claude-3-5-sonnet") is not None

    # Register custom model
    custom = ModelMetadata(
        model_id="custom-fast:1b",
        name="Custom Fast 1B",
        provider="ollama",
        execution_target=ModelExecutionTarget.LOCAL,
        availability=ModelAvailability.AVAILABLE,
        approval_status=ModelApprovalStatus.APPROVED,
        capabilities={ModelCapability.FAST_INFERENCE},
        context_window=2048,
        min_vram_gb=1.5,
    )
    registry.register_model(custom)
    assert registry.get_model("custom-fast:1b") == custom

    # Filter models
    locals_only = registry.list_models(execution_target=ModelExecutionTarget.LOCAL)
    assert all(m.execution_target == ModelExecutionTarget.LOCAL for m in locals_only)
    assert any(m.model_id == "custom-fast:1b" for m in locals_only)

    # Update availability & approval
    registry.update_availability("custom-fast:1b", ModelAvailability.DEGRADED)
    assert registry.get_model("custom-fast:1b").availability == ModelAvailability.DEGRADED

    registry.update_approval("custom-fast:1b", ModelApprovalStatus.PROHIBITED)
    assert registry.get_model("custom-fast:1b").approval_status == ModelApprovalStatus.PROHIBITED


def test_passive_discovery_gating_invariant():
    """
    CRITICAL INVARIANT: Newly discovered models must enter PENDING_REVIEW status.
    They must never be automatically approved or used for production tasks.
    """
    registry = ModelRegistry()

    discovered = registry.discover_local_models(["mystery-model:7b", "gemma3:4b"])
    assert len(discovered) == 1
    new_model = discovered[0]

    assert new_model.model_id == "mystery-model:7b"
    assert new_model.approval_status == ModelApprovalStatus.PENDING_REVIEW
    assert new_model.execution_target == ModelExecutionTarget.LOCAL

    # Existing model gemma3:4b remains approved
    gemma = registry.get_model("gemma3:4b")
    assert gemma.approval_status == ModelApprovalStatus.APPROVED
    assert gemma.availability == ModelAvailability.AVAILABLE


def test_capability_assessor_matching_and_rejections():
    assessor = CapabilityAssessor(hardware_vram_gb=6.0)

    # Case 1: Model with required capabilities and sufficient context
    model = ModelMetadata(
        model_id="code-expert:3b",
        name="Code Expert 3B",
        provider="ollama",
        execution_target=ModelExecutionTarget.LOCAL,
        availability=ModelAvailability.AVAILABLE,
        approval_status=ModelApprovalStatus.APPROVED,
        capabilities={ModelCapability.CODING, ModelCapability.REASONING},
        context_window=4096,
        min_vram_gb=2.8,
    )
    reqs = TaskRequirements(
        task_id="t1",
        required_capabilities={ModelCapability.CODING},
        estimated_input_tokens=500,
        estimated_output_tokens=500,
    )
    assessment = assessor.assess_model(model, reqs)
    assert assessment.is_suitable is True
    assert assessment.fitness_score > 0.0

    # Case 2: Model missing required capability
    reqs_vision = TaskRequirements(
        task_id="t2",
        required_capabilities={ModelCapability.VISION},
    )
    assessment_vision = assessor.assess_model(model, reqs_vision)
    assert assessment_vision.is_suitable is False
    assert ModelCapability.VISION in assessment_vision.missing_required_capabilities

    # Case 3: Context window insufficient
    reqs_large = TaskRequirements(
        task_id="t3",
        required_capabilities={ModelCapability.CODING},
        estimated_input_tokens=3000,
        estimated_output_tokens=2000,
    )
    assessment_large = assessor.assess_model(model, reqs_large)
    assert assessment_large.is_suitable is False
    assert assessment_large.context_window_sufficient is False

    # Case 4: Hardware ceiling violation (> 6GB VRAM on RTX 4050)
    huge_model = ModelMetadata(
        model_id="huge-model:70b",
        name="Huge Model 70B",
        provider="ollama",
        execution_target=ModelExecutionTarget.LOCAL,
        capabilities={ModelCapability.CODING},
        min_vram_gb=40.0,
    )
    assessment_huge = assessor.assess_model(huge_model, reqs)
    assert assessment_huge.is_suitable is False
    assert assessment_huge.hardware_compliant is False

    # Case 5: Unapproved model (PENDING_REVIEW) rejected
    pending_model = ModelMetadata(
        model_id="pending:1b",
        name="Pending 1B",
        provider="ollama",
        execution_target=ModelExecutionTarget.LOCAL,
        approval_status=ModelApprovalStatus.PENDING_REVIEW,
        capabilities={ModelCapability.CODING},
        min_vram_gb=1.0,
    )
    assessment_pending = assessor.assess_model(pending_model, reqs)
    assert assessment_pending.is_suitable is False
    assert "pending_review" in assessment_pending.rejection_reasons[0]


def test_privacy_compliance_assessment():
    assessor = CapabilityAssessor(hardware_vram_gb=6.0)

    cloud_model = ModelMetadata(
        model_id="claude-3-5-sonnet",
        name="Claude 3.5 Sonnet",
        provider="anthropic",
        execution_target=ModelExecutionTarget.CLOUD,
        approval_status=ModelApprovalStatus.APPROVED,
        capabilities={ModelCapability.REASONING, ModelCapability.CODING},
        context_window=200000,
    )

    reqs_local_only = TaskRequirements(
        task_id="t_privacy",
        required_capabilities={ModelCapability.REASONING},
        local_only_required=True,
    )

    assessment = assessor.assess_model(cloud_model, reqs_local_only)
    assert assessment.is_suitable is False
    assert assessment.privacy_compliant is False
    assert any("local-only" in r or "cloud-hosted" in r for r in assessment.rejection_reasons)


def test_model_orchestrator_dynamic_selection():
    registry = ModelRegistry()
    assessor = CapabilityAssessor(hardware_vram_gb=6.0)
    orchestrator = ModelOrchestrator(registry=registry, assessor=assessor)

    reqs = TaskRequirements(
        task_id="coding_task",
        required_capabilities={ModelCapability.CODING, ModelCapability.STRUCTURED_OUTPUT},
    )

    selection = orchestrator.select_model(reqs)
    assert selection.selected_model_id in ("bonsai-2:9b", "qwen2.5-coder:3b", "claude-3-5-sonnet", "gpt-4o")
    assert len(selection.fallback_models) >= 1


def test_model_orchestrator_strict_privacy_boundary():
    """
    CRITICAL INVARIANT: Local-only tasks must NEVER select cloud models,
    and fallbacks MUST strictly be local models.
    """
    registry = ModelRegistry()
    orchestrator = ModelOrchestrator(registry=registry)

    # 1. Direct local_only_required flag
    reqs = TaskRequirements(
        task_id="private_task",
        required_capabilities={ModelCapability.REASONING},
        local_only_required=True,
    )
    selection = orchestrator.select_model(reqs)

    selected_meta = registry.get_model(selection.selected_model_id)
    assert selected_meta.execution_target == ModelExecutionTarget.LOCAL

    for fb_id in selection.fallback_models:
        fb_meta = registry.get_model(fb_id)
        assert fb_meta.execution_target == ModelExecutionTarget.LOCAL

    # 2. Privacy derived from context confidentiality
    ctx = IntelligenceContext(
        actor_id="owner",
        metadata={"project_confidentiality": ProjectConfidentialityLevel.CONFIDENTIAL.value},
    )
    reqs_contextual = TaskRequirements(
        task_id="project_analysis",
        required_capabilities={ModelCapability.REASONING},
        local_only_required=False,  # Context should elevate this to True
    )
    selection_ctx = orchestrator.select_model(reqs_contextual, context=ctx)
    selected_ctx_meta = registry.get_model(selection_ctx.selected_model_id)
    assert selected_ctx_meta.execution_target == ModelExecutionTarget.LOCAL
    for fb_id in selection_ctx.fallback_models:
        assert registry.get_model(fb_id).execution_target == ModelExecutionTarget.LOCAL


def test_manual_override_security_and_constraints():
    registry = ModelRegistry()
    orchestrator = ModelOrchestrator(registry=registry)

    # 1. Valid approved override succeeds
    reqs_valid = TaskRequirements(
        task_id="task_override_1",
        manual_override_model="bonsai-2:9b",
    )
    sel = orchestrator.select_model(reqs_valid)
    assert sel.selected_model_id == "bonsai-2:9b"
    assert "Manual owner override" in sel.selection_rationale

    # 2. Manual override selecting cloud model for local-only task MUST FAIL
    reqs_cloud_for_private = TaskRequirements(
        task_id="task_override_privacy_violation",
        manual_override_model="claude-3-5-sonnet",
        local_only_required=True,
    )
    with pytest.raises(ModelSelectionError) as exc_info:
        orchestrator.select_model(reqs_cloud_for_private)
    assert "violates privacy boundary" in str(exc_info.value)

    # 3. Manual override with model exceeding hardware ceiling (>6GB VRAM)
    registry.register_model(
        ModelMetadata(
            model_id="too-heavy:32b",
            name="Too Heavy 32B",
            provider="ollama",
            execution_target=ModelExecutionTarget.LOCAL,
            min_vram_gb=18.0,
        )
    )
    reqs_hw = TaskRequirements(
        task_id="task_override_hw",
        manual_override_model="too-heavy:32b",
    )
    with pytest.raises(HardwareConstraintViolation):
        orchestrator.select_model(reqs_hw)

    # 4. Manual override with unknown model
    reqs_unknown = TaskRequirements(
        task_id="task_override_unknown",
        manual_override_model="ghost-model:1b",
    )
    with pytest.raises(ModelSelectionError) as exc_unknown:
        orchestrator.select_model(reqs_unknown)
    assert "not registered" in str(exc_unknown.value)


@pytest.mark.asyncio
async def test_orchestrated_execution_with_fallback():
    registry = ModelRegistry()
    mock_ollama = MagicMock()
    mock_api = MagicMock()

    orchestrator = ModelOrchestrator(
        registry=registry,
        ollama_adapter=mock_ollama,
        api_adapter=mock_api,
    )

    # Simulate primary model failing and fallback model succeeding
    call_count = 0

    async def mock_ollama_chat(messages, model, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Ollama primary model connection timeout")
        return f"Response from fallback model {model}"

    mock_ollama.chat = AsyncMock(side_effect=mock_ollama_chat)

    reqs = TaskRequirements(
        task_id="task_fallback_test",
        required_capabilities={ModelCapability.REASONING},
        local_only_required=True,
    )

    result = await orchestrator.execute_task(
        requirements=reqs,
        messages=[{"role": "user", "content": "Explain binary search."}],
    )

    assert result.fallback_occurred is True
    assert len(result.fallback_history) >= 1
    assert "Response from fallback model" in result.content


@pytest.mark.asyncio
async def test_sequential_multi_model_verification():
    registry = ModelRegistry()
    mock_ollama = MagicMock()

    # Sequential calls return distinct responses
    async def mock_chat(messages, model, **kwargs):
        if "bonsai" in model:
            return "Binary search divides the interval in half repeatedly."
        return "Binary search repeatedly partitions the search interval in half."

    mock_ollama.chat = AsyncMock(side_effect=mock_chat)

    orchestrator = ModelOrchestrator(
        registry=registry,
        ollama_adapter=mock_ollama,
    )

    reqs = TaskRequirements(
        task_id="task_verify",
        required_capabilities={ModelCapability.REASONING},
        local_only_required=True,
        multi_model_verification_required=True,
    )

    result = await orchestrator.execute_task(
        requirements=reqs,
        messages=[{"role": "user", "content": "What is binary search?"}],
    )

    assert result.verification_result is not None
    assert result.verification_result["verified"] is True
    assert result.verification_result["agreement_score"] > 0.3
    # Check that mock_ollama was called sequentially twice
    assert mock_ollama.chat.call_count == 2


@pytest.mark.asyncio
async def test_passive_discovery_via_orchestrator():
    registry = ModelRegistry()
    mock_ollama = MagicMock()
    mock_ollama.check_health = AsyncMock(
        return_value={"online": True, "models": ["new-candidate:3b", "gemma3:4b"]}
    )

    orchestrator = ModelOrchestrator(
        registry=registry,
        ollama_adapter=mock_ollama,
    )

    newly_discovered = await orchestrator.discover_and_update_models()
    assert len(newly_discovered) == 1
    assert newly_discovered[0].model_id == "new-candidate:3b"
    assert newly_discovered[0].approval_status == ModelApprovalStatus.PENDING_REVIEW
