"""
backend/intelligence/context.py

Shared contextual container for HINAKU Intelligence Core operations.

SECURITY DIRECTIVE:
IntelligenceContext is strictly a contextual runtime container. It must NEVER store
session tokens, authentication credentials, passwords, or reusable authorization secrets.
Authentication and authorization remain exclusively within backend/security/auth.py.
"""

import re
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Set

from .errors import ContextSecurityViolation, DomainIsolationViolation
from .types import KnowledgeDomain

# Forbidden sensitive key patterns that indicate authentication credentials or session tokens
PROHIBITED_SECRET_KEY_REGEXES = [
    re.compile(r"(?i)(?:^|_)(?:auth|session|access|bearer|internal|id|refresh)?_?token(?:_|$)"),
    re.compile(r"(?i)^token$"),
    re.compile(r"(?i)(?:password|passwd|pwd|passcode)"),
    re.compile(r"(?i)(?:api_key|apikey|secret_key|private_key)"),
    re.compile(r"(?i)(?:^|_)secret(?:_|$)"),
    re.compile(r"(?i)^authorization$"),
    re.compile(r"(?i)^bearer$"),
]


@dataclass
class IntelligenceContext:
    """
    Contextual runtime container for intelligence operations.
    Carries safe actor attribution, project state, domain restrictions, and operational constraints.
    """
    actor_id: str = "owner"
    conversation_id: Optional[str] = None
    active_project_id: Optional[str] = None
    permitted_domains: Set[KnowledgeDomain] = field(
        default_factory=lambda: {
            KnowledgeDomain.PERSONAL,
            KnowledgeDomain.PROJECT,
            KnowledgeDomain.GENERAL,
            KnowledgeDomain.DECISION,
        }
    )
    operation_constraints: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        # Validate that no credentials, tokens, or secrets leak into context
        self._audit_for_prohibited_secrets(self.operation_constraints, "operation_constraints")
        self._audit_for_prohibited_secrets(self.metadata, "metadata")

        # Normalize permitted_domains to KnowledgeDomain enums if strings were passed
        normalized_domains = set()
        for d in self.permitted_domains:
            if isinstance(d, KnowledgeDomain):
                normalized_domains.add(d)
            elif isinstance(d, str):
                normalized_domains.add(KnowledgeDomain(d.lower()))
            else:
                raise TypeError(f"Invalid domain type in permitted_domains: {type(d)}")
        self.permitted_domains = normalized_domains

    def _audit_for_prohibited_secrets(self, container: Dict[str, Any], container_name: str) -> None:
        """Audits dict keys and string values to prevent secret/token injection."""
        if not isinstance(container, dict):
            return

        for k, v in container.items():
            k_str = str(k).strip()
            for regex in PROHIBITED_SECRET_KEY_REGEXES:
                if regex.search(k_str):
                    raise ContextSecurityViolation(
                        f"Security violation: key '{k}' in {container_name} matches prohibited authorization pattern '{regex.pattern}'. "
                        "IntelligenceContext must not store authorization tokens or credentials."
                    )
            # Check for candidate token values (e.g. bearer tokens or 32+ char hex/base64 strings)
            if isinstance(v, str):
                v_strip = v.strip()
                if v_strip.startswith("hinaku_internal_") or v_strip.startswith("Bearer "):
                    raise ContextSecurityViolation(
                        f"Security violation: value in {container_name}['{k}'] contains an authorization token. "
                        "IntelligenceContext must not store authorization tokens or credentials."
                    )

    def validate_domain_access(self, domain: KnowledgeDomain) -> None:
        """
        Enforces domain boundary isolation.
        Raises DomainIsolationViolation if the requested domain is not permitted by this context.
        """
        target_domain = domain if isinstance(domain, KnowledgeDomain) else KnowledgeDomain(str(domain).lower())
        if target_domain not in self.permitted_domains:
            raise DomainIsolationViolation(
                f"Domain isolation violation: access to '{target_domain.value}' knowledge domain is not permitted in this context. "
                f"Permitted domains: {[d.value for d in self.permitted_domains]}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "conversation_id": self.conversation_id,
            "active_project_id": self.active_project_id,
            "permitted_domains": [d.value for d in self.permitted_domains],
            "operation_constraints": self.operation_constraints,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntelligenceContext":
        domains = {KnowledgeDomain(d) for d in data.get("permitted_domains", [])}
        return cls(
            actor_id=data.get("actor_id", "owner"),
            conversation_id=data.get("conversation_id"),
            active_project_id=data.get("active_project_id"),
            permitted_domains=domains if domains else {
                KnowledgeDomain.PERSONAL,
                KnowledgeDomain.PROJECT,
                KnowledgeDomain.GENERAL,
                KnowledgeDomain.DECISION,
            },
            operation_constraints=data.get("operation_constraints", {}),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
        )
