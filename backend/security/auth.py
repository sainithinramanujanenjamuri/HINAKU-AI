"""
backend/security/auth.py

Local Session Authorization Manager for HINAKU.
Protects sensitive and destructive local API endpoints from unauthorized access,
CSRF, and local browser-origin attacks.

Key Security Properties:
1. Cryptographically secure session tokens generated using secrets.token_hex(32) (256-bit entropy).
2. Server-side in-memory validation; tokens are never logged, stored in Git, or exposed in URLs.
3. Constant-time token comparison via hmac.compare_digest to prevent timing side-channel attacks.
4. Defense against CSRF: custom header (X-Hinaku-Token) cannot be attached by cross-origin
   browser forms or simple cross-origin requests without failing CORS preflight.
5. Defense against browser-origin attacks: token is passed directly through native desktop IPC
   (pywebview JavaScript bridge) and is never injected into static HTML.
"""

import hmac
import logging
import os
import secrets
import time
from enum import Enum
from typing import Any, Dict, Optional, Set
from fastapi import Header, HTTPException, Request

logger = logging.getLogger("hinaku.security.auth")


class InternalScope(str, Enum):
    """
    Granular scopes for legitimate internal and background services.
    Internal tokens cannot be used to authenticate external API endpoints
    and cannot be escalated to perform critical owner actions.
    """
    BACKGROUND_SCHEDULER = "internal:scheduler"
    BACKGROUND_MEMORY = "internal:memory_extraction"
    BACKGROUND_PREWARM = "internal:prewarm"
    SYSTEM_MAINTENANCE = "internal:maintenance"


class InternalAuthorizationError(Exception):
    """Raised when an internal or background execution authorization check fails."""
    pass


# Critical owner actions that strictly require direct human owner authorization
# via desktop session tokens and CANNOT be executed autonomously by background
# services, internal tokens, or AI reasoning engines.
CRITICAL_OWNER_ACTIONS: Set[str] = {
    "promote_model",
    "rollback_model",
    "wipe_all_data",
    "clear_all_memory",
    "delete_conversation",
    "export_all_data",
    "modify_security_settings",
}


class InternalTokenManager:
    """
    Manages narrowly scoped internal execution authorization tokens for background services.

    Key Security Properties:
    1. Independent entropy: tokens are distinct from the desktop session token and never expose it.
    2. Scope confinement: tokens are bounded to a single declared scope with finite TTL.
    3. Non-interchangeable: internal tokens are explicitly rejected on HTTP API endpoints
       requiring desktop session authorization.
    4. Anti-escalation: critical owner actions are barred from internal token execution.
    5. In-memory validation with constant-time comparison via hmac.compare_digest.
    """
    def __init__(self):
        self._tokens: Dict[str, Dict[str, Any]] = {}

    def issue_token(self, scope: InternalScope, ttl_seconds: int = 300) -> str:
        """Issue a fresh, cryptographically secure scoped internal token."""
        raw_token = "hinaku_internal_" + secrets.token_hex(24)
        scope_str = scope.value if isinstance(scope, InternalScope) else str(scope)
        now = time.time()
        self._tokens[raw_token] = {
            "scope": scope_str,
            "created_at": now,
            "expires_at": now + ttl_seconds,
        }
        return raw_token

    def validate_token(self, candidate_token: Optional[str], required_scope: InternalScope) -> bool:
        """
        Validate an internal token against an expected scope.
        Returns False if candidate is missing, expired, or scope does not match.
        """
        if not candidate_token or not isinstance(candidate_token, str):
            return False

        now = time.time()
        entry = self._tokens.get(candidate_token)
        if not entry:
            return False

        if now > entry["expires_at"]:
            self._tokens.pop(candidate_token, None)
            return False

        expected_scope = required_scope.value if isinstance(required_scope, InternalScope) else str(required_scope)
        return hmac.compare_digest(entry["scope"], expected_scope)

    def revoke_token(self, token: str) -> None:
        """Revoke an active internal token."""
        self._tokens.pop(token, None)

    def clear(self) -> None:
        """Clear all active internal tokens."""
        self._tokens.clear()


internal_token_manager = InternalTokenManager()


def validate_internal_scope(token: Optional[str], required_scope: InternalScope) -> None:
    """
    Validates that a token has the exact required internal scope.
    Raises InternalAuthorizationError if missing, expired, or wrong scope.
    """
    if not internal_token_manager.validate_token(token, required_scope):
        expected_scope = required_scope.value if isinstance(required_scope, InternalScope) else str(required_scope)
        logger.warning(
            f"[Security] Internal authorization failed. Missing or invalid internal token for scope '{expected_scope}'."
        )
        raise InternalAuthorizationError(
            f"Unauthorized internal operation: valid token for scope '{expected_scope}' is required."
        )


def assert_owner_session_required(action_name: str, has_owner_session: bool) -> None:
    """
    Enforces that critical actions strictly require direct owner authorization.
    Prevents autonomous background processes, planning loops, or internal
    tokens from executing critical/destructive actions without owner consent.
    """
    if action_name in CRITICAL_OWNER_ACTIONS and not has_owner_session:
        logger.warning(
            f"[Security] Denied autonomous execution of critical owner action '{action_name}'. "
            "Direct owner desktop session authorization is required."
        )
        raise InternalAuthorizationError(
            f"Action '{action_name}' is restricted to owner desktop authorization and cannot be run autonomously."
        )


class SessionTokenManager:
    """
    Manages the lifecycle and verification of local desktop session authorization tokens.
    """
    def __init__(self, token_ttl_seconds: Optional[int] = None):
        self._token: Optional[str] = None
        self._created_at: float = 0.0
        self.token_ttl_seconds = token_ttl_seconds  # None means session lasts process lifetime
        self._initialize_token()

    def _initialize_token(self) -> None:
        """Initialize session token from environment or generate a fresh secure token."""
        env_token = os.environ.get("HINAKU_SESSION_TOKEN")
        if env_token and len(env_token.strip()) >= 32:
            self._token = env_token.strip()
        else:
            self._token = secrets.token_hex(32)
        self._created_at = time.time()

    def get_token(self) -> str:
        """Returns the current active session token."""
        if not self._token or self.is_expired():
            self._initialize_token()
        return self._token

    def set_token(self, token: str) -> None:
        """Explicitly set an active token (used in tests or explicit process bootstrapping)."""
        if not token or len(token.strip()) < 16:
            raise ValueError("Token must be a non-empty string with at least 16 characters of entropy.")
        self._token = token.strip()
        self._created_at = time.time()

    def is_expired(self) -> bool:
        """Checks whether the token has exceeded its configured time-to-live."""
        if self.token_ttl_seconds is None:
            return False
        return (time.time() - self._created_at) > self.token_ttl_seconds

    def invalidate(self) -> None:
        """Invalidate the current token."""
        self._token = None
        self._created_at = 0.0

    def rotate_token(self) -> str:
        """Rotate and return a new active session token."""
        self._token = secrets.token_hex(32)
        self._created_at = time.time()
        return self._token

    def validate_token(self, candidate_token: Optional[str]) -> bool:
        """
        Validates the candidate token using constant-time comparison.
        Returns False if candidate is missing, token is expired, or tokens do not match.
        Explicitly rejects internal background tokens to prevent authorization bypass.
        """
        if not candidate_token or not isinstance(candidate_token, str):
            return False

        clean_candidate = candidate_token.strip()

        # Internal tokens can NEVER be used as desktop session tokens
        if clean_candidate.startswith("hinaku_internal_"):
            return False

        if not self._token or self.is_expired():
            return False

        return hmac.compare_digest(clean_candidate, self._token)


# Global singleton session manager
session_token_manager = SessionTokenManager()


def get_active_session_token() -> str:
    """Helper to retrieve the current active session token."""
    return session_token_manager.get_token()


def set_active_session_token(token: str) -> None:
    """Helper to set the active session token."""
    session_token_manager.set_token(token)


def rotate_active_session_token() -> str:
    """Helper to rotate the active session token."""
    return session_token_manager.rotate_token()


def invalidate_active_session_token() -> None:
    """Helper to invalidate the active session token."""
    session_token_manager.invalidate()


async def require_session_auth(
    request: Request,
    x_hinaku_token: Optional[str] = Header(None, alias="X-Hinaku-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> str:
    """
    FastAPI dependency enforcing local session authorization on sensitive endpoints.
    Checks 'X-Hinaku-Token' header or 'Authorization: Bearer <token>'.
    Fails closed with HTTP 401 Unauthorized if token is missing, invalid, or expired.
    Explicitly refuses internal background tokens attempting to authenticate API requests.
    """
    candidate_token = x_hinaku_token

    if not candidate_token and authorization:
        auth_str = authorization.strip()
        if auth_str.lower().startswith("bearer "):
            candidate_token = auth_str[7:].strip()
        else:
            candidate_token = auth_str

    if not candidate_token or not session_token_manager.validate_token(candidate_token):
        client_host = request.client.host if request.client else "unknown"
        logger.warning(
            f"[Security] Unauthorized access attempt to {request.method} {request.url.path} from {client_host}. "
            "Session token missing, invalid, or disallowed internal token."
        )
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing or invalid local session authorization token."
        )

    return candidate_token
