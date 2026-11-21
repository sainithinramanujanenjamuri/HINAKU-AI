"""
backend/intelligence/orchestrator_types.py

Data structures, enums, and models for HINAKU Adaptive Model Orchestration.
Tracks model registration, capabilities, runtime constraints, task requirements, and execution results.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Set


class ModelExecutionTarget(str, Enum):
    """Execution environment for the model."""
    LOCAL = "local"   # On-device inference via local daemon (Ollama)
    CLOUD = "cloud"   # External hosted provider via API adapter


class ModelAvailability(str, Enum):
    """Runtime availability status of a model."""
    AVAILABLE = "available"     # Active and ready to accept prompts
    UNAVAILABLE = "unavailable" # Offline, daemon down, or API unreachable
    DEGRADED = "degraded"       # Operational with high latency or intermittent failures
    DISCOVERED = "discovered"   # Detected locally/remotely; pending evaluation or approval


class ModelApprovalStatus(str, Enum):
    """Owner authorization status for using the model."""
    APPROVED = "approved"             # Explicitly authorized for production tasks
    PENDING_REVIEW = "pending_review" # Discovered model awaiting owner confirmation
    PROHIBITED = "prohibited"         # Explicitly banned or disabled by owner


class ModelCapability(str, Enum):
    """Distinct cognitive and technical capabilities supported by models."""
    REASONING = "reasoning"                 # Multi-step logical analysis
    CODING = "coding"                       # Code generation, syntax, debugging
    FAST_INFERENCE = "fast_inference"       # Low latency for conversational follow-ups
    DETAILED_EXPLANATION = "detailed_explanation" # Deep, pedagogical walkthroughs
    STRUCTURED_OUTPUT = "structured_output" # Strict JSON / schema conformity
    FUNCTION_CALLING = "function_calling"   # Tool invocation
    VISION = "vision"                       # Multimodal visual understanding


@dataclass
class ModelMetadata:
    """Registered entity representing an AI model in the HINAKU ecosystem."""
    model_id: str
    name: str
    provider: str
    execution_target: ModelExecutionTarget
    availability: ModelAvailability = ModelAvailability.AVAILABLE
    approval_status: ModelApprovalStatus = ModelApprovalStatus.APPROVED
    capabilities: Set[ModelCapability] = field(default_factory=set)
    context_window: int = 4096
    min_vram_gb: float = 0.0
    min_ram_gb: float = 0.0
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "provider": self.provider,
            "execution_target": self.execution_target.value,
            "availability": self.availability.value,
            "approval_status": self.approval_status.value,
            "capabilities": [c.value for c in self.capabilities],
            "context_window": self.context_window,
            "min_vram_gb": self.min_vram_gb,
            "min_ram_gb": self.min_ram_gb,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "metadata": self.metadata,
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelMetadata":
        caps = {ModelCapability(c) for c in data.get("capabilities", [])}
        return cls(
            model_id=data["model_id"],
            name=data["name"],
            provider=data["provider"],
            execution_target=ModelExecutionTarget(data["execution_target"]),
            availability=ModelAvailability(data.get("availability", ModelAvailability.AVAILABLE.value)),
            approval_status=ModelApprovalStatus(data.get("approval_status", ModelApprovalStatus.APPROVED.value)),
            capabilities=caps,
            context_window=data.get("context_window", 4096),
            min_vram_gb=float(data.get("min_vram_gb", 0.0)),
            min_ram_gb=float(data.get("min_ram_gb", 0.0)),
            cost_per_1k_input=float(data.get("cost_per_1k_input", 0.0)),
            cost_per_1k_output=float(data.get("cost_per_1k_output", 0.0)),
            metadata=data.get("metadata", {}),
            registered_at=data.get("registered_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class TaskRequirements:
    """Explicit functional and environmental requirements for a cognitive task."""
    task_id: str
    description: str = ""
    required_capabilities: Set[ModelCapability] = field(default_factory=set)
    estimated_input_tokens: int = 500
    estimated_output_tokens: int = 500
    local_only_required: bool = False
    max_cost_allowed: float = 1.0
    manual_override_model: Optional[str] = None
    multi_model_verification_required: bool = False

    def total_estimated_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens


@dataclass
class CapabilityAssessment:
    """Suitability assessment of a candidate model against task requirements."""
    model_id: str
    is_suitable: bool
    supported_required_capabilities: Set[ModelCapability] = field(default_factory=set)
    missing_required_capabilities: Set[ModelCapability] = field(default_factory=set)
    context_window_sufficient: bool = True
    privacy_compliant: bool = True
    hardware_compliant: bool = True
    fitness_score: float = 0.0
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "is_suitable": self.is_suitable,
            "supported_required_capabilities": [c.value for c in self.supported_required_capabilities],
            "missing_required_capabilities": [c.value for c in self.missing_required_capabilities],
            "context_window_sufficient": self.context_window_sufficient,
            "privacy_compliant": self.privacy_compliant,
            "hardware_compliant": self.hardware_compliant,
            "fitness_score": self.fitness_score,
            "rejection_reasons": self.rejection_reasons,
        }


@dataclass
class ModelSelectionResult:
    """Determined model and fallback options for task execution."""
    selected_model_id: str
    execution_target: ModelExecutionTarget
    selection_rationale: str
    fallback_models: List[str] = field(default_factory=list)
    multi_model_verifier_id: Optional[str] = None


@dataclass
class OrchestratedExecutionResult:
    """Outcome of an orchestrated model invocation."""
    task_id: str
    model_id: str
    execution_target: ModelExecutionTarget
    content: str
    tokens_used: int = 0
    latency_ms: int = 0
    fallback_occurred: bool = False
    fallback_history: List[str] = field(default_factory=list)
    verification_result: Optional[Dict[str, Any]] = None
