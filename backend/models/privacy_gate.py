"""
backend/models/privacy_gate.py

Final Outbound Privacy Boundary Gate for HINAKU.
Strictly inspects all candidate outbound payloads immediately before transmission to external API models.

Enforces:
1. Explicit conversation privacy state (is_private).
   - Missing or non-boolean privacy state FAILS CLOSED.
2. Explicit attachment state (has_attachments).
   - Missing or non-boolean attachment state FAILS CLOSED.
3. Message structure, role, and content validation:
   - Must be a non-empty list of dicts.
   - Roles must be standard: {"system", "developer", "user", "assistant", "tool"}.
     Any unknown role FAILS CLOSED.
   - Content must be string or supported structured text parts.
     Multimodal content (images, audio, video, binary) FAILS CLOSED.
   - Unsupported or ambiguous payload structures FAIL CLOSED.
4. Complete payload inspection:
   - System and developer prompts inspected for memory injection and document citations.
   - User, assistant, and tool turns inspected for sensitive credentials, document excerpts,
     sensitive personal topics, despair, and first-person personal statements.
5. Fail-closed behavior:
   - On any ambiguity, corruption, missing metadata, or unrecognized structure, execution
     halts immediately before any external network connection is established.
6. Zero secret or personal data leakage in log output.

KNOWN LIMITATION - ENGLISH-ONLY HEURISTIC DETECTION:
All heuristic pattern matching (personal statements, sensitive topics, credentials)
is implemented in English-only regex. Queries in other languages (Spanish, Hindi, French, etc.),
romanized transliterations (Hinglish), and non-English slang are NOT reliably intercepted
by content heuristics. Automatic multilingual privacy protection does NOT exist.
Full privacy protection for non-English conversation is provided ONLY by explicitly marking
the conversation as Private (is_private=True), which unconditionally blocks external API calls.
"""

import logging
import re
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

from backend.guards import SENSITIVE_REPLACEMENTS, SENSITIVE_TOPIC_PATTERNS, is_sensitive_topic, is_hopelessness_or_self_harm

logger = logging.getLogger("hinaku.privacy_gate")


class OutboundPrivacyViolation(RuntimeError):
    """
    Raised when an outbound API request is blocked by the privacy policy.
    Ensures execution halts before any external network connection is established.
    """
    def __init__(self, message: str, category: Optional[str] = None):
        super().__init__(message)
        self.category = category or "general_privacy_violation"


class PrivacyInspectionResult(NamedTuple):
    is_safe: bool
    reason: Optional[str]
    category: Optional[str]
    turn_index: Optional[int]


# Allowed standard roles across modern LLM providers
ALLOWED_ROLES = {"system", "developer", "user", "assistant", "tool"}

# Multimodal types that must fail closed immediately
PROHIBITED_MULTIMODAL_TYPES = {
    "image", "image_url", "input_audio", "audio", "video", "file", "document", "binary"
}

# Markers indicating personal memory injection or document attachments
FORBIDDEN_SYSTEM_MARKERS = [
    r"\[What HINAKU remembers about you\]",
    r"What HINAKU remembers about you",
    r"Relevant memories from prior conversations:",
    r"<document_reference>",
    r"</document_reference>",
    r"\[File:\s*[^\]]+,\s*Page:\s*\d+\]",
    r"\[Section:\s*[^\]]+\]",
]

# Sensitive credential patterns from guards that must never leave in unredacted plaintext
CREDENTIAL_PATTERNS = [
    (r"(?i)\b(?:my\s+(?:card\s+|atm\s+)?pin\s+is\s+)\d{3,8}\b", "pin"),
    (r"(?i)\b(?:card\s*pin|atm\s*pin|pin\s*code)\s*(?:[:=]|is)\s*\d{3,8}\b", "pin"),
    (r"(?i)\bmy\s+password\s+is\s+\S+", "password"),
    (r"(?i)\b(?:password|passwd|pwd|passcode)\s*(?:[:=]|is)\s*\S+", "password"),
    (r"\b(?:\d{4}[ -]?){3}\d{4}\b", "credit_card"),
    (r"\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b", "credit_card"),
    (r"(?i)\b(?:bank\s+account|account\s+number|iban|routing\s+number)\s*(?:[:=]|is)?\s*[A-Z0-9-]{8,34}\b", "bank_account"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "government_id"),
    (r"\b\d{4}\s\d{4}\s\d{4}\b", "government_id"),
    (r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "government_id"),
    (r"\b(?:sk-[a-zA-Z0-9_\-]{20,}|ghp_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9]{20,})\b", "api_key"),
]


class OutboundPrivacyGate:
    """
    Final authoritative privacy gate.
    Evaluates full payload immediately before transmission to external API endpoints.
    Enforces strict fail-closed security: missing metadata or unknown formats are rejected.
    """

    @classmethod
    def inspect_payload(
        cls,
        messages: Any,
        is_private: Any,
        has_attachments: Any
    ) -> PrivacyInspectionResult:
        """
        Inspects complete outbound message payload and returns detailed safety evaluation.
        Fails closed on any violation, missing metadata, or malformed data.
        NOTE: is_private and has_attachments do NOT have default values to prevent unsafe assumptions.
        """
        # 1. Validate privacy metadata (Must be explicitly a boolean; no unsafe defaults)
        if not isinstance(is_private, bool):
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Missing or invalid privacy metadata ('is_private' must be a boolean); failing closed.",
                category="invalid_privacy_metadata",
                turn_index=None
            )

        # 2. Validate attachment metadata (Must be explicitly a boolean; no unsafe defaults)
        if not isinstance(has_attachments, bool):
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Missing or invalid attachment metadata ('has_attachments' must be a boolean); failing closed.",
                category="invalid_attachment_metadata",
                turn_index=None
            )

        # 3. Enforce explicit conversation privacy state
        if is_private is True:
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Conversation is explicitly marked private; outbound API transmission prohibited.",
                category="private_conversation",
                turn_index=None
            )

        # 4. Enforce attachment boundary
        if has_attachments is True:
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Conversation contains attachments; document content is restricted to local processing.",
                category="attachment_restricted",
                turn_index=None
            )

        # 5. Fail closed on non-list, empty list, or malformed messages payload
        if not isinstance(messages, list) or len(messages) == 0:
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Payload is empty or not a list; failing closed.",
                category="malformed_payload",
                turn_index=None
            )

        # 6. Inspect every message turn in the candidate payload
        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                return PrivacyInspectionResult(
                    is_safe=False,
                    reason=f"Message turn {idx} is malformed (expected dict, got {type(msg).__name__}); failing closed.",
                    category="malformed_payload",
                    turn_index=idx
                )

            # Validate required keys
            if "role" not in msg or "content" not in msg:
                return PrivacyInspectionResult(
                    is_safe=False,
                    reason=f"Message turn {idx} is missing required 'role' or 'content' keys; failing closed.",
                    category="malformed_payload",
                    turn_index=idx
                )

            raw_role = msg.get("role")
            if not isinstance(raw_role, str) or raw_role.strip().lower() not in ALLOWED_ROLES:
                return PrivacyInspectionResult(
                    is_safe=False,
                    reason=f"Message turn {idx} contains unknown or unsupported role: {repr(raw_role)}; failing closed.",
                    category="unsupported_role",
                    turn_index=idx
                )
            role = raw_role.strip().lower()

            raw_content = msg.get("content")

            # Extract string texts from supported content formats
            text_blocks: List[str] = []

            if isinstance(raw_content, str):
                text_blocks.append(raw_content)
            elif isinstance(raw_content, list):
                # Structured content: list of parts
                for part_idx, part in enumerate(raw_content):
                    if not isinstance(part, dict):
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} structured content part {part_idx} is not a dict; failing closed.",
                            category="unsupported_content_type",
                            turn_index=idx
                        )
                    part_type = str(part.get("type", "")).strip().lower()
                    if part_type in PROHIBITED_MULTIMODAL_TYPES:
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} contains multimodal or binary content ({part_type}); external transmission prohibited.",
                            category="multimodal_payload_prohibited",
                            turn_index=idx
                        )
                    elif part_type == "text":
                        text_val = part.get("text")
                        if not isinstance(text_val, str):
                            return PrivacyInspectionResult(
                                is_safe=False,
                                reason=f"Turn {idx} structured text part {part_idx} text is not a string; failing closed.",
                                category="unsupported_content_type",
                                turn_index=idx
                            )
                        text_blocks.append(text_val)
                    else:
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} contains unsupported structured content part ({part_type}); failing closed.",
                            category="unsupported_content_type",
                            turn_index=idx
                        )
            else:
                # Unsupported content type (None, int, dict, bytes, etc.)
                return PrivacyInspectionResult(
                    is_safe=False,
                    reason=f"Message turn {idx} contains unsupported content type: {type(raw_content).__name__}; failing closed.",
                    category="unsupported_content_type",
                    turn_index=idx
                )

            # Inspect extracted text blocks
            for content in text_blocks:
                # A. Check system/developer prompt for forbidden personal context or document markers
                if role in ("system", "developer"):
                    for pat in FORBIDDEN_SYSTEM_MARKERS:
                        if re.search(pat, content, re.IGNORECASE):
                            return PrivacyInspectionResult(
                                is_safe=False,
                                reason=f"System/developer prompt contains injected personal memory or document tags ({pat}).",
                                category="injected_personal_context",
                                turn_index=idx
                            )

                # B. Check for unredacted credentials in ANY role (system, developer, user, assistant, tool)
                for pat, cat in CREDENTIAL_PATTERNS:
                    if re.search(pat, content):
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} ({role}) contains unredacted sensitive credential ({cat}).",
                            category=f"sensitive_credential_{cat}",
                            turn_index=idx
                        )

                # C. Check conversation turns (user, assistant, tool)
                if role in ("user", "assistant", "tool"):
                    # Check document marker leakage in conversation turns
                    if "<document_reference>" in content or "[File:" in content:
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} ({role}) contains document attachment excerpts.",
                            category="document_leakage",
                            turn_index=idx
                        )

                    # Check sensitive topics (mental health, mood, health, money trouble, personal relationships)
                    is_sens_topic, sens_cat = is_sensitive_topic(content)
                    if is_sens_topic:
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} ({role}) contains sensitive personal topic ({sens_cat}).",
                            category=f"sensitive_topic_{sens_cat}",
                            turn_index=idx
                        )

                    # Check despair / self-harm
                    if is_hopelessness_or_self_harm(content):
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"Turn {idx} ({role}) contains distress or self-harm indicators.",
                            category="sensitive_topic_hopelessness",
                            turn_index=idx
                        )

                    # Check first-person personal statements and owner facts
                    if role in ("user", "tool"):
                        from .router import is_personal_statement
                        if is_personal_statement(content):
                            return PrivacyInspectionResult(
                                is_safe=False,
                                reason=f"Turn {idx} ({role}) contains personal statements or owner profile data.",
                                category="personal_statement",
                                turn_index=idx
                            )

        return PrivacyInspectionResult(
            is_safe=True,
            reason=None,
            category=None,
            turn_index=None
        )

    @classmethod
    def is_payload_safe_for_api(
        cls,
        messages: Any,
        is_private: Any,
        has_attachments: Any
    ) -> bool:
        """Convenience boolean check."""
        result = cls.inspect_payload(messages, is_private=is_private, has_attachments=has_attachments)
        return result.is_safe

    @classmethod
    def verify_outbound_payload(
        cls,
        messages: Any,
        is_private: Any,
        has_attachments: Any
    ) -> None:
        """
        Validates payload or immediately raises OutboundPrivacyViolation.
        Logs sanitized warning without leaking payload contents.
        Fails closed on any violation or missing metadata.
        """
        result = cls.inspect_payload(messages, is_private=is_private, has_attachments=has_attachments)
        if not result.is_safe:
            log_msg = f"[PrivacyGate] Blocked external API transmission: {result.reason} (Category: {result.category})"
            logger.warning(log_msg)
            raise OutboundPrivacyViolation(result.reason or "Outbound privacy policy violation", category=result.category)
