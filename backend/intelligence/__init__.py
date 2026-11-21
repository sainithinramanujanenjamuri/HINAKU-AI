"""
backend/intelligence/__init__.py

HINAKU Intelligence Core: Foundation for Independent Intelligence.
"""

from .errors import (
    IntelligenceError,
    ProvenanceError,
    DomainIsolationViolation,
    UncertaintyThresholdExceeded,
    ContextSecurityViolation,
    ProjectNotFoundError,
    DuplicateProjectError,
    ProjectConfidentialityViolation,
    UnauthorizedRepositoryAccessError,
    RepositoryAccessViolation,
    KnowledgeGraphError,
    ContradictionResolutionError,
    CrossDomainLeakageError,
    TaskLifecycleViolation,
    PlanningDependencyError,
    CriticalApprovalRequiredError,
    ModelSelectionError,
    ModelExecutionError,
    HardwareConstraintViolation,
    UnsuitableModelError,
)
from .types import (
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
from .orchestrator_types import (
    ModelExecutionTarget,
    ModelAvailability,
    ModelApprovalStatus,
    ModelCapability,
    ModelMetadata,
    TaskRequirements,
    CapabilityAssessment,
    ModelSelectionResult,
    OrchestratedExecutionResult,
)
from .project_types import (
    ProjectStatus,
    ProjectConfidentiality,
    KnowledgeCategory,
    ProjectRecord,
    ProjectKnowledgeItem,
    ProjectKnowledgeRevision,
    RepositoryFileIndex,
    ProjectDiscoveryCandidate,
)
from .graph_types import (
    EdgeRelationship,
    KnowledgeEdge,
    ContextBundle,
)
from .decision_types import (
    DecisionStatus,
    UncertaintyLevel,
    CriticalActionCategory,
    AlternativeEvaluation,
    UncertaintyAssessment,
    DecisionRecommendation,
    DecisionRecord,
)
from .planning_types import (
    PlanStatus,
    DependencyType,
    TaskDependency,
    ManagedTask,
    TaskStateTransition,
    PlanRecord,
)
from .project_store import ProjectStore
from .repo_grounding import RepoGrounding
from .project_discovery import ProjectDiscovery
from .project_engine import ProjectEngine
from .knowledge_graph import KnowledgeGraph
from .contradiction_manager import ContradictionManager
from .domain_router import DomainRouter
from .decision_engine import DecisionEngine
from .planning_engine import PlanningEngine
from .task_manager import TaskManager
from .model_registry import ModelRegistry
from .capability_assessor import CapabilityAssessor
from .model_orchestrator import ModelOrchestrator
from .context import IntelligenceContext

__all__ = [
    # Errors
    "IntelligenceError",
    "ProvenanceError",
    "DomainIsolationViolation",
    "UncertaintyThresholdExceeded",
    "ContextSecurityViolation",
    "ProjectNotFoundError",
    "DuplicateProjectError",
    "ProjectConfidentialityViolation",
    "UnauthorizedRepositoryAccessError",
    "RepositoryAccessViolation",
    "KnowledgeGraphError",
    "ContradictionResolutionError",
    "CrossDomainLeakageError",
    "TaskLifecycleViolation",
    "PlanningDependencyError",
    "CriticalApprovalRequiredError",
    "ModelSelectionError",
    "ModelExecutionError",
    "HardwareConstraintViolation",
    "UnsuitableModelError",
    # Types & Enums
    "KnowledgeDomain",
    "SourceAuthority",
    "ImplementationStatus",
    "TaskPriority",
    "TaskStatus",
    "KnowledgeProvenance",
    "CognitiveTask",
    "ReasoningStep",
    "ReasoningResult",
    # Model Orchestration Types
    "ModelExecutionTarget",
    "ModelAvailability",
    "ModelApprovalStatus",
    "ModelCapability",
    "ModelMetadata",
    "TaskRequirements",
    "CapabilityAssessment",
    "ModelSelectionResult",
    "OrchestratedExecutionResult",
    # Project Intelligence Types
    "ProjectStatus",
    "ProjectConfidentiality",
    "KnowledgeCategory",
    "ProjectRecord",
    "ProjectKnowledgeItem",
    "ProjectKnowledgeRevision",
    "RepositoryFileIndex",
    "ProjectDiscoveryCandidate",
    # Knowledge Graph & Context Types
    "EdgeRelationship",
    "KnowledgeEdge",
    "ContextBundle",
    # Decision Types
    "DecisionStatus",
    "UncertaintyLevel",
    "CriticalActionCategory",
    "AlternativeEvaluation",
    "UncertaintyAssessment",
    "DecisionRecommendation",
    "DecisionRecord",
    # Planning & Task Types
    "PlanStatus",
    "DependencyType",
    "TaskDependency",
    "ManagedTask",
    "TaskStateTransition",
    "PlanRecord",
    # Services & Engines
    "ProjectStore",
    "RepoGrounding",
    "ProjectDiscovery",
    "ProjectEngine",
    "KnowledgeGraph",
    "ContradictionManager",
    "DomainRouter",
    "DecisionEngine",
    "PlanningEngine",
    "TaskManager",
    "ModelRegistry",
    "CapabilityAssessor",
    "ModelOrchestrator",
    # Context
    "IntelligenceContext",
]

