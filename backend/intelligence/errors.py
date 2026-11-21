"""
backend/intelligence/errors.py

Exception hierarchy for HINAKU Intelligence Core.
"""

class IntelligenceError(Exception):
    """Base exception for all HINAKU Intelligence Core operations."""
    pass


class ProvenanceError(IntelligenceError):
    """Raised when knowledge provenance invariants are violated (e.g. ungrounded implementation status)."""
    pass


class DomainIsolationViolation(IntelligenceError):
    """Raised when an operation attempts to access or mix knowledge domains outside permitted boundaries."""
    pass


class UncertaintyThresholdExceeded(IntelligenceError):
    """Raised when reasoning confidence falls below an acceptable threshold without authorized assumptions."""
    pass


class ContextSecurityViolation(IntelligenceError):
    """Raised when authentication secrets, session tokens, or credentials are inappropriately introduced into context."""
    pass


class ProjectNotFoundError(IntelligenceError):
    """Raised when an operation references a project ID that does not exist or is marked deleted."""
    pass


class DuplicateProjectError(IntelligenceError):
    """Raised when attempting to register a project with a duplicate identity, name, or repo path."""
    pass


class ProjectConfidentialityViolation(IntelligenceError):
    """Raised when an operation attempts to breach project confidentiality (e.g. leaking confidential project data to external models)."""
    pass


class UnauthorizedRepositoryAccessError(IntelligenceError):
    """Raised when repository grounding attempts to access an unauthorized path outside explicit project bounds."""
    pass


class RepositoryAccessViolation(IntelligenceError):
    """Raised when repository grounding encounters prohibited files (secrets, private databases, credentials) or write attempts."""
    pass


class KnowledgeGraphError(IntelligenceError):
    """Raised when knowledge graph edge operations violate graph consistency or referential integrity."""
    pass


class ContradictionResolutionError(IntelligenceError):
    """Raised when an automated contradiction resolution attempt fails or produces conflicting states."""
    pass


class CrossDomainLeakageError(DomainIsolationViolation):
    """Raised when knowledge from one domain (e.g. personal facts) is inappropriately leaked into another (e.g. project context or API egress)."""
    pass


class TaskLifecycleViolation(IntelligenceError):
    """Raised when an invalid task state transition is attempted or approval preconditions are unmet."""
    pass


class PlanningDependencyError(IntelligenceError):
    """Raised when a planning operation encounters circular dependencies or missing prerequisite tasks."""
    pass


class CriticalApprovalRequiredError(IntelligenceError):
    """Raised when an operation requiring explicit owner authorization is initiated without approval."""
    pass


class ModelSelectionError(IntelligenceError):
    """Raised when no suitable model can be identified to satisfy task constraints or privacy requirements."""
    pass


class ModelExecutionError(IntelligenceError):
    """Raised when a selected model fails during execution and all safe fallbacks are exhausted."""
    pass


class HardwareConstraintViolation(IntelligenceError):
    """Raised when model selection or execution exceeds local hardware capacity (e.g. 6GB VRAM ceiling)."""
    pass


class UnsuitableModelError(IntelligenceError):
    """Raised when a requested or overridden model lacks mandatory capabilities or violates privacy rules."""
    pass




