"""
backend/intelligence/model_registry.py

Centralized model registry for HINAKU Adaptive Model Orchestration.
Tracks model capabilities, execution targets, availability, and owner approval status.
"""

from typing import Any, Dict, List, Optional, Set
import time

from .orchestrator_types import (
    ModelApprovalStatus,
    ModelAvailability,
    ModelCapability,
    ModelExecutionTarget,
    ModelMetadata,
)


# Standard canonical capability profiles for well-known models in the HINAKU ecosystem
KNOWN_MODEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "bonsai-2:9b": {
        "name": "Bonsai 2 (9B Q2_0)",
        "provider": "ollama",
        "execution_target": ModelExecutionTarget.LOCAL,
        "capabilities": {
            ModelCapability.REASONING,
            ModelCapability.CODING,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.DETAILED_EXPLANATION,
        },
        "context_window": 8192,
        "min_vram_gb": 4.5,
        "min_ram_gb": 8.0,
    },
    "gemma3:4b": {
        "name": "Gemma 3 (4B Q4)",
        "provider": "ollama",
        "execution_target": ModelExecutionTarget.LOCAL,
        "capabilities": {
            ModelCapability.FAST_INFERENCE,
            ModelCapability.REASONING,
            ModelCapability.STRUCTURED_OUTPUT,
        },
        "context_window": 4096,
        "min_vram_gb": 3.2,
        "min_ram_gb": 6.0,
    },
    "qwen3.5:4b": {
        "name": "Qwen 3.5 (4B Q4)",
        "provider": "ollama",
        "execution_target": ModelExecutionTarget.LOCAL,
        "capabilities": {
            ModelCapability.FAST_INFERENCE,
            ModelCapability.REASONING,
            ModelCapability.CODING,
        },
        "context_window": 4096,
        "min_vram_gb": 3.0,
        "min_ram_gb": 6.0,
    },
    "llama3.2:3b": {
        "name": "Llama 3.2 (3B Q4)",
        "provider": "ollama",
        "execution_target": ModelExecutionTarget.LOCAL,
        "capabilities": {
            ModelCapability.FAST_INFERENCE,
            ModelCapability.REASONING,
        },
        "context_window": 4096,
        "min_vram_gb": 2.5,
        "min_ram_gb": 4.0,
    },
    "qwen2.5-coder:3b": {
        "name": "Qwen 2.5 Coder (3B Q4)",
        "provider": "ollama",
        "execution_target": ModelExecutionTarget.LOCAL,
        "capabilities": {
            ModelCapability.CODING,
            ModelCapability.FAST_INFERENCE,
            ModelCapability.STRUCTURED_OUTPUT,
        },
        "context_window": 4096,
        "min_vram_gb": 2.8,
        "min_ram_gb": 4.0,
    },
    "claude-3-5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "provider": "anthropic",
        "execution_target": ModelExecutionTarget.CLOUD,
        "capabilities": {
            ModelCapability.REASONING,
            ModelCapability.CODING,
            ModelCapability.DETAILED_EXPLANATION,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        },
        "context_window": 200000,
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
    },
    "gpt-4o": {
        "name": "GPT-4o",
        "provider": "openai_compatible",
        "execution_target": ModelExecutionTarget.CLOUD,
        "capabilities": {
            ModelCapability.REASONING,
            ModelCapability.CODING,
            ModelCapability.FAST_INFERENCE,
            ModelCapability.DETAILED_EXPLANATION,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        },
        "context_window": 128000,
        "cost_per_1k_input": 0.005,
        "cost_per_1k_output": 0.015,
    },
    "gpt-4o-mini": {
        "name": "GPT-4o Mini",
        "provider": "openai_compatible",
        "execution_target": ModelExecutionTarget.CLOUD,
        "capabilities": {
            ModelCapability.FAST_INFERENCE,
            ModelCapability.REASONING,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.FUNCTION_CALLING,
        },
        "context_window": 128000,
        "cost_per_1k_input": 0.00015,
        "cost_per_1k_output": 0.0006,
    },
}


class ModelRegistry:
    """Central registry tracking approved, configured, and discovered models."""

    def __init__(self):
        self._models: Dict[str, ModelMetadata] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Initializes default known model profiles."""
        for mid, prof in KNOWN_MODEL_PROFILES.items():
            self._models[mid] = ModelMetadata(
                model_id=mid,
                name=prof["name"],
                provider=prof["provider"],
                execution_target=prof["execution_target"],
                availability=ModelAvailability.AVAILABLE,
                approval_status=ModelApprovalStatus.APPROVED,
                capabilities=set(prof.get("capabilities", set())),
                context_window=prof.get("context_window", 4096),
                min_vram_gb=prof.get("min_vram_gb", 0.0),
                min_ram_gb=prof.get("min_ram_gb", 0.0),
                cost_per_1k_input=prof.get("cost_per_1k_input", 0.0),
                cost_per_1k_output=prof.get("cost_per_1k_output", 0.0),
            )

    def register_model(self, metadata: ModelMetadata) -> ModelMetadata:
        """Registers or updates a model record."""
        metadata.updated_at = time.time()
        self._models[metadata.model_id] = metadata
        return metadata

    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        """Retrieves a model by its identifier."""
        return self._models.get(model_id)

    def list_models(
        self,
        execution_target: Optional[ModelExecutionTarget] = None,
        availability: Optional[ModelAvailability] = None,
        approval_status: Optional[ModelApprovalStatus] = None,
    ) -> List[ModelMetadata]:
        """Returns filtered list of registered models."""
        res = list(self._models.values())
        if execution_target is not None:
            res = [m for m in res if m.execution_target == execution_target]
        if availability is not None:
            res = [m for m in res if m.availability == availability]
        if approval_status is not None:
            res = [m for m in res if m.approval_status == approval_status]
        return res

    def update_availability(self, model_id: str, status: ModelAvailability) -> None:
        """Updates runtime availability of a model."""
        if model_id in self._models:
            self._models[model_id].availability = status
            self._models[model_id].updated_at = time.time()

    def update_approval(self, model_id: str, status: ModelApprovalStatus) -> None:
        """Updates owner approval status for a model."""
        if model_id in self._models:
            self._models[model_id].approval_status = status
            self._models[model_id].updated_at = time.time()

    def discover_local_models(self, discovered_tags: List[str]) -> List[ModelMetadata]:
        """
        Passive discovery: registers locally found models as DISCOVERED and PENDING_REVIEW.
        INVARIANT: Does not automatically approve or install newly discovered models.
        """
        newly_discovered: List[ModelMetadata] = []
        for tag in discovered_tags:
            tag_clean = tag.strip()
            if not tag_clean:
                continue

            if tag_clean in self._models:
                # Update existing model availability to AVAILABLE
                self._models[tag_clean].availability = ModelAvailability.AVAILABLE
            else:
                # Register new discovered model
                prof = KNOWN_MODEL_PROFILES.get(tag_clean, {})
                caps = set(prof.get("capabilities", {ModelCapability.REASONING}))
                meta = ModelMetadata(
                    model_id=tag_clean,
                    name=prof.get("name", f"Discovered ({tag_clean})"),
                    provider="ollama",
                    execution_target=ModelExecutionTarget.LOCAL,
                    availability=ModelAvailability.AVAILABLE,
                    approval_status=ModelApprovalStatus.PENDING_REVIEW,  # Mandatory: requires review!
                    capabilities=caps,
                    context_window=prof.get("context_window", 4096),
                    min_vram_gb=prof.get("min_vram_gb", 3.0),
                )
                self.register_model(meta)
                newly_discovered.append(meta)

        return newly_discovered
