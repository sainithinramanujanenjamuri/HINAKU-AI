"""
backend/intelligence/capability_assessor.py

Evaluates AI model suitability against specific task requirements and constraints.
Enforces hardware limitations (6GB RTX 4050 target laptop), context capacities,
owner approval gates, and physical privacy boundaries.
"""

from typing import List, Optional, Set
from .orchestrator_types import (
    CapabilityAssessment,
    ModelApprovalStatus,
    ModelAvailability,
    ModelCapability,
    ModelExecutionTarget,
    ModelMetadata,
    TaskRequirements,
)


class CapabilityAssessor:
    """
    Evaluates candidate models against explicit task requirements.
    Avoids universal rank ordering; computes contextual fitness scores.
    """

    def __init__(self, hardware_vram_gb: float = 6.0, hardware_ram_gb: float = 16.0):
        self.hardware_vram_gb = hardware_vram_gb
        self.hardware_ram_gb = hardware_ram_gb

    def assess_model(
        self,
        model: ModelMetadata,
        requirements: TaskRequirements,
    ) -> CapabilityAssessment:
        rejection_reasons: List[str] = []
        is_suitable = True

        # 1. Availability check
        if model.availability == ModelAvailability.UNAVAILABLE:
            is_suitable = False
            rejection_reasons.append(f"Model '{model.model_id}' is currently unavailable/offline.")

        # 2. Owner approval check
        if model.approval_status != ModelApprovalStatus.APPROVED:
            is_suitable = False
            rejection_reasons.append(
                f"Model '{model.model_id}' has approval status '{model.approval_status.value}' (requires 'approved')."
            )

        # 3. Privacy compliance check
        privacy_compliant = True
        if requirements.local_only_required and model.execution_target != ModelExecutionTarget.LOCAL:
            privacy_compliant = False
            is_suitable = False
            rejection_reasons.append(
                f"Task requires strictly local execution; model '{model.model_id}' is cloud-hosted."
            )

        # 4. Capability matching
        supported_req_caps: Set[ModelCapability] = set()
        missing_req_caps: Set[ModelCapability] = set()

        for req_cap in requirements.required_capabilities:
            if req_cap in model.capabilities:
                supported_req_caps.add(req_cap)
            else:
                missing_req_caps.add(req_cap)

        if missing_req_caps:
            is_suitable = False
            missing_names = ", ".join(sorted(c.value for c in missing_req_caps))
            rejection_reasons.append(
                f"Model '{model.model_id}' lacks required capabilities: {missing_names}"
            )

        # 5. Context window sufficiency
        total_tokens_needed = requirements.total_estimated_tokens()
        context_window_sufficient = total_tokens_needed <= model.context_window
        if not context_window_sufficient:
            is_suitable = False
            rejection_reasons.append(
                f"Context window ({model.context_window} tokens) insufficient for task estimated tokens ({total_tokens_needed} tokens)."
            )

        # 6. Hardware constraint check (for local models on RTX 4050 6GB target)
        hardware_compliant = True
        if model.execution_target == ModelExecutionTarget.LOCAL:
            if model.min_vram_gb > self.hardware_vram_gb:
                hardware_compliant = False
                is_suitable = False
                rejection_reasons.append(
                    f"Model requires {model.min_vram_gb:.1f} GB VRAM, exceeding hardware ceiling of {self.hardware_vram_gb:.1f} GB VRAM."
                )

        # 7. Fitness scoring (contextual; 0.0 if not suitable)
        fitness_score = 0.0
        if is_suitable:
            base_score = 1.0

            # Match ratio of capabilities
            if requirements.required_capabilities:
                cap_ratio = len(supported_req_caps) / len(requirements.required_capabilities)
                base_score += cap_ratio * 2.0

            # Local models preferred for privacy and zero marginal API cost
            if model.execution_target == ModelExecutionTarget.LOCAL:
                base_score += 0.5

            # If fast inference requested and model has FAST_INFERENCE
            if ModelCapability.FAST_INFERENCE in requirements.required_capabilities and ModelCapability.FAST_INFERENCE in model.capabilities:
                base_score += 0.5

            # Degraded status penalty
            if model.availability == ModelAvailability.DEGRADED:
                base_score *= 0.5

            fitness_score = round(base_score, 3)

        return CapabilityAssessment(
            model_id=model.model_id,
            is_suitable=is_suitable,
            supported_required_capabilities=supported_req_caps,
            missing_required_capabilities=missing_req_caps,
            context_window_sufficient=context_window_sufficient,
            privacy_compliant=privacy_compliant,
            hardware_compliant=hardware_compliant,
            fitness_score=fitness_score,
            rejection_reasons=rejection_reasons,
        )
