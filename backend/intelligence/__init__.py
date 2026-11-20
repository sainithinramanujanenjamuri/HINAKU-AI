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
from .graph_types import (
    EdgeRelationship,
    KnowledgeEdge,
    ContextBundle,
)
from .project_store import ProjectStore
from .repo_grounding import RepoGrounding
from .project_discovery import ProjectDiscovery
from .project_engine import ProjectEngine
from .knowledge_graph import KnowledgeGraph
from .contradiction_manager import ContradictionManager
from .domain_router import DomainRouter
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
    # Knowledge Graph & Context Types
    "EdgeRelationship",
    "KnowledgeEdge",
    "ContextBundle",
    # Services & Engines
    "ProjectStore",
    "RepoGrounding",
    "ProjectDiscovery",
    "ProjectEngine",
    "KnowledgeGraph",
    "ContradictionManager",
    "DomainRouter",
    # Context
    "IntelligenceContext",
]

