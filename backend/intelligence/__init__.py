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
from .project_store import ProjectStore
from .repo_grounding import RepoGrounding
from .project_discovery import ProjectDiscovery
from .project_engine import ProjectEngine
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
    # Project Intelligence Types
    "ProjectStatus",
    "ProjectConfidentiality",
    "KnowledgeCategory",
    "ProjectRecord",
    "ProjectKnowledgeItem",
    "ProjectKnowledgeRevision",
    "RepositoryFileIndex",
    "ProjectDiscoveryCandidate",
    # Project Intelligence Services
    "ProjectStore",
    "RepoGrounding",
    "ProjectDiscovery",
    "ProjectEngine",
    # Context
    "IntelligenceContext",
]

