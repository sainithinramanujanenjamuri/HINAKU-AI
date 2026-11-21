"""
backend/intelligence/model_orchestrator.py

Adaptive Model Orchestrator for HINAKU.
Coordinates model selection, capability-based routing, controlled fallback,
multi-model verification, and passive local model discovery.

INVARIANTS:
1. Physical Privacy Gate: Confidential project data, personal memory, and private
   conversations must NEVER be transmitted to external cloud models, even during fallback.
2. Hardware Awareness: Target laptop RTX 4050 has 6GB VRAM; models exceeding capacity
   are rejected. Multi-model verification runs sequentially to prevent VRAM exhaustion.
3. Passive Model Discovery: Newly detected local models enter PENDING_REVIEW status and
   are never auto-promoted or auto-used for production tasks without owner approval.
4. Model Independence: Models are replaceable tools; they never store HINAKU's identity,
   memory, decision records, or knowledge graphs.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Set

from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter

from .capability_assessor import CapabilityAssessor
from .context import IntelligenceContext
from .errors import (
    HardwareConstraintViolation,
    ModelExecutionError,
    ModelSelectionError,
    ProjectConfidentialityViolation,
)
from .model_registry import ModelRegistry
from .orchestrator_types import (
    ModelApprovalStatus,
    ModelAvailability,
    ModelCapability,
    ModelExecutionTarget,
    ModelMetadata,
    ModelSelectionResult,
    OrchestratedExecutionResult,
    TaskRequirements,
)
from .project_types import ProjectConfidentiality, ProjectConfidentiality as ProjectConfidentialityLevel

logger = logging.getLogger("hinaku.intelligence.model_orchestrator")


class ModelOrchestrator:
    """
    Adaptive Model Orchestration Engine.
    Dynamically routes tasks to capable models, coordinates safe fallback,
    and enforces strict outbound privacy and hardware boundaries.
    """

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        assessor: Optional[CapabilityAssessor] = None,
        ollama_adapter: Optional[OllamaAdapter] = None,
        api_adapter: Optional[ApiAdapter] = None,
    ):
        self.registry = registry or ModelRegistry()
        self.assessor = assessor or CapabilityAssessor(hardware_vram_gb=6.0, hardware_ram_gb=16.0)
        self.ollama_adapter = ollama_adapter or OllamaAdapter()
        self.api_adapter = api_adapter or ApiAdapter()

    def select_model(
        self,
        requirements: TaskRequirements,
        context: Optional[IntelligenceContext] = None,
    ) -> ModelSelectionResult:
        """
        Selects primary and fallback models meeting explicit task requirements and boundaries.
        Enforces physical privacy restrictions: local-only tasks NEVER route to cloud models.
        """
        # 1. Enforce privacy requirements derived from context
        local_only = requirements.local_only_required
        if context is not None:
            # Check operation constraints
            if context.operation_constraints.get("local_only") is True:
                local_only = True
            # Check project confidentiality if active project present
            proj_conf = context.metadata.get("project_confidentiality")
            if proj_conf in (
                ProjectConfidentialityLevel.CONFIDENTIAL.value,
                ProjectConfidentialityLevel.RESTRICTED.value,
                ProjectConfidentialityLevel.CONFIDENTIAL,
                ProjectConfidentialityLevel.RESTRICTED,
            ):
                local_only = True

        # Copy requirements to avoid mutating caller's object
        effective_reqs = TaskRequirements(
            task_id=requirements.task_id,
            description=requirements.description,
            required_capabilities=set(requirements.required_capabilities),
            estimated_input_tokens=requirements.estimated_input_tokens,
            estimated_output_tokens=requirements.estimated_output_tokens,
            local_only_required=local_only,
            max_cost_allowed=requirements.max_cost_allowed,
            manual_override_model=requirements.manual_override_model,
            multi_model_verification_required=requirements.multi_model_verification_required,
        )

        # 2. Handle Manual Model Override
        if effective_reqs.manual_override_model:
            override_id = effective_reqs.manual_override_model
            model = self.registry.get_model(override_id)
            if not model:
                raise ModelSelectionError(
                    f"Manual override model '{override_id}' is not registered in the model registry."
                )

            assessment = self.assessor.assess_model(model, effective_reqs)

            # Security Invariant: Manual override CANNOT bypass privacy boundaries
            if not assessment.privacy_compliant:
                raise ModelSelectionError(
                    f"Manual override model '{override_id}' violates privacy boundary: "
                    f"task requires local-only execution, but model is {model.execution_target.value}."
                )

            # Hardware Invariant: Local models must fit target hardware (6GB VRAM)
            if not assessment.hardware_compliant:
                raise HardwareConstraintViolation(
                    f"Manual override model '{override_id}' violates hardware ceiling: "
                    f"requires {model.min_vram_gb:.1f}GB VRAM exceeding 6GB capacity."
                )

            # Availability & Approval check
            if model.availability == ModelAvailability.UNAVAILABLE:
                raise ModelSelectionError(
                    f"Manual override model '{override_id}' is currently unavailable."
                )
            if model.approval_status != ModelApprovalStatus.APPROVED:
                raise ModelSelectionError(
                    f"Manual override model '{override_id}' is not approved for production use (status: {model.approval_status.value})."
                )

            return ModelSelectionResult(
                selected_model_id=model.model_id,
                execution_target=model.execution_target,
                selection_rationale=f"Manual owner override: {model.name} ({model.model_id})",
                fallback_models=[],
                multi_model_verifier_id=None,
            )

        # 3. Dynamic Selection: Evaluate all registered models
        all_models = self.registry.list_models()
        candidate_assessments = []

        for model in all_models:
            assessment = self.assessor.assess_model(model, effective_reqs)
            if assessment.is_suitable:
                candidate_assessments.append((model, assessment))

        if not candidate_assessments:
            raise ModelSelectionError(
                f"No suitable model found satisfying task '{effective_reqs.task_id}' requirements "
                f"(capabilities: {[c.value for c in effective_reqs.required_capabilities]}, "
                f"local_only: {effective_reqs.local_only_required})."
            )

        # 4. Sort suitable candidates by contextual fitness score descending
        candidate_assessments.sort(key=lambda item: item[1].fitness_score, reverse=True)

        primary_model, primary_assessment = candidate_assessments[0]

        # 5. Build Fallback Models List
        # STRICT PRIVACY INVARIANT: If task requires local execution, fallbacks MUST be strictly local.
        fallbacks: List[str] = []
        for model, _ in candidate_assessments[1:]:
            if effective_reqs.local_only_required and model.execution_target != ModelExecutionTarget.LOCAL:
                continue
            fallbacks.append(model.model_id)

        # 6. Multi-Model Verifier Selection (if requested)
        verifier_id: Optional[str] = None
        if effective_reqs.multi_model_verification_required:
            for model, _ in candidate_assessments[1:]:
                # Verifier must be a distinct model
                if model.model_id != primary_model.model_id:
                    # If local-only required, verifier must be local
                    if effective_reqs.local_only_required and model.execution_target != ModelExecutionTarget.LOCAL:
                        continue
                    verifier_id = model.model_id
                    break

        rationale = (
            f"Selected {primary_model.name} ({primary_model.model_id}) with fitness score {primary_assessment.fitness_score:.2f}. "
            f"Execution target: {primary_model.execution_target.value}. Fallbacks available: {len(fallbacks)}."
        )

        return ModelSelectionResult(
            selected_model_id=primary_model.model_id,
            execution_target=primary_model.execution_target,
            selection_rationale=rationale,
            fallback_models=fallbacks,
            multi_model_verifier_id=verifier_id,
        )

    async def execute_task(
        self,
        requirements: TaskRequirements,
        messages: List[Dict[str, str]],
        context: Optional[IntelligenceContext] = None,
        is_private: Optional[bool] = None,
        has_attachments: Optional[bool] = None,
    ) -> OrchestratedExecutionResult:
        """
        Executes a task through selected model with controlled fallback and privacy gate enforcement.
        Runs multi-model verification sequentially when required.
        """
        start_time = time.time()

        # Enforce conversation-level privacy state
        if is_private is True:
            requirements.local_only_required = True

        selection = self.select_model(requirements, context)
        execution_chain = [selection.selected_model_id] + selection.fallback_models

        fallback_history: List[str] = []
        final_content: str = ""
        successful_model_id: str = ""
        successful_target = selection.execution_target
        last_error: Optional[Exception] = None

        for attempt_idx, candidate_id in enumerate(execution_chain):
            model_meta = self.registry.get_model(candidate_id)
            if not model_meta:
                continue

            target = model_meta.execution_target

            # Physical Outbound Privacy Gate Enforcement
            if target == ModelExecutionTarget.CLOUD:
                if requirements.local_only_required or is_private is True:
                    # Invariant violation: abort immediately before any network interaction
                    raise OutboundPrivacyViolation(
                        f"Attempted cloud dispatch for local-only task '{requirements.task_id}'. Halting execution."
                    )
                # Verify payload via OutboundPrivacyGate
                OutboundPrivacyGate.verify_outbound_payload(
                    messages=messages,
                    is_private=bool(is_private),
                    has_attachments=bool(has_attachments),
                )

            try:
                if target == ModelExecutionTarget.LOCAL:
                    response_text = await self.ollama_adapter.chat(
                        messages=messages,
                        model=model_meta.model_id,
                    )
                else:
                    response_text = await self.api_adapter.chat(
                        messages=messages,
                        model=model_meta.model_id,
                        is_private=bool(is_private),
                        has_attachments=bool(has_attachments),
                    )

                final_content = response_text
                successful_model_id = candidate_id
                successful_target = target
                if attempt_idx > 0:
                    fallback_history.append(f"Fallback to {candidate_id} succeeded")
                break

            except Exception as e:
                logger.warning(
                    f"Execution failed on model '{candidate_id}': {str(e)}. "
                    f"Attempting fallback if available."
                )
                last_error = e
                fallback_history.append(f"Failed on {candidate_id}: {str(e)}")
                continue

        if not successful_model_id:
            raise ModelExecutionError(
                f"All candidate models exhausted for task '{requirements.task_id}'. Last error: {str(last_error)}"
            )

        # Multi-Model Verification (if configured and verifier available)
        verification_result: Optional[Dict[str, Any]] = None
        if requirements.multi_model_verification_required and selection.multi_model_verifier_id:
            verifier_id = selection.multi_model_verifier_id
            verifier_meta = self.registry.get_model(verifier_id)
            if verifier_meta:
                try:
                    # Run SEQUENTIALLY to safeguard 6GB VRAM on RTX 4050
                    if verifier_meta.execution_target == ModelExecutionTarget.LOCAL:
                        verifier_content = await self.ollama_adapter.chat(
                            messages=messages,
                            model=verifier_meta.model_id,
                        )
                    else:
                        verifier_content = await self.api_adapter.chat(
                            messages=messages,
                            model=verifier_meta.model_id,
                            is_private=bool(is_private),
                            has_attachments=bool(has_attachments),
                        )

                    # Compute basic lexical/token agreement between responses
                    tokens_primary = set(final_content.lower().split())
                    tokens_verifier = set(verifier_content.lower().split())
                    intersection = tokens_primary.intersection(tokens_verifier)
                    union = tokens_primary.union(tokens_verifier)
                    agreement_score = len(intersection) / len(union) if union else 1.0

                    verification_result = {
                        "verifier_model_id": verifier_id,
                        "verifier_execution_target": verifier_meta.execution_target.value,
                        "agreement_score": round(agreement_score, 3),
                        "verified": agreement_score >= 0.25,
                        "verifier_content_length": len(verifier_content),
                    }
                except Exception as ve:
                    logger.warning(f"Verification model '{verifier_id}' execution failed: {str(ve)}")
                    verification_result = {
                        "verifier_model_id": verifier_id,
                        "error": str(ve),
                        "verified": False,
                    }

        elapsed_ms = int((time.time() - start_time) * 1000)

        return OrchestratedExecutionResult(
            task_id=requirements.task_id,
            model_id=successful_model_id,
            execution_target=successful_target,
            content=final_content,
            tokens_used=len(final_content.split()),
            latency_ms=elapsed_ms,
            fallback_occurred=len(fallback_history) > 1 or (len(fallback_history) == 1 and not fallback_history[0].startswith("Fallback")),
            fallback_history=fallback_history,
            verification_result=verification_result,
        )

    async def discover_and_update_models(self) -> List[ModelMetadata]:
        """
        Passive discovery: queries local Ollama daemon for installed models.
        New models are registered with PENDING_REVIEW status and require owner approval.
        """
        try:
            health = await self.ollama_adapter.check_health()
            models = health.get("models", [])
            new_models = self.registry.discover_local_models(models)
            return new_models
        except Exception as e:
            logger.warning(f"Passive model discovery encountered error: {str(e)}")
            return []
