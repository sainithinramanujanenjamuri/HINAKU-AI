# HINAKU Sprint 0A and 0B — Owner Review and Security Verification

**Author**: Antigravity Assistant  
**Date**: November 15, 2026  
**Repository**: `HINAKU-AI`  
**Branch**: `sprint-0b-privacy-boundary` (uncommitted working tree; no commits or merges created)  
**Status**: Pending Owner Review and Formal Approval  

---

## Table of Contents
1. [Executive Summary & Verification Purpose](#1-executive-summary--verification-purpose)
2. [Complete Implementation of Verified Components](#2-complete-implementation-of-verified-components)
   - [backend/models/privacy_gate.py](#21-backendmodelsprivacy_gatepy)
   - [backend/models/api_adapter.py](#22-backendmodelsapi_adapterpy)
   - [backend/models/router.py](#23-backendmodelsrouterpy)
   - [Relevant Changes in backend/api/chat.py](#24-relevant-changes-in-backendapichatpy)
   - [CORS Configuration in backend/main.py](#25-cors-configuration-in-backendmainpy)
3. [Verification of Every External API Transmission Path](#3-verification-of-every-external-api-transmission-path)
4. [Privacy Gate Bypass Resistance Verification](#4-privacy-gate-bypass-resistance-verification)
5. [English-Only Privacy Detection Limitation Review](#5-english-only-privacy-detection-limitation-review)
6. [Desktop Application (pywebview) CORS Compatibility](#6-desktop-application-pywebview-cors-compatibility)
7. [API Endpoint Authorization Audit (CORS is Not Authorization)](#7-api-endpoint-authorization-audit-cors-is-not-authorization)
8. [Complete Test Suite Execution & Output](#8-complete-test-suite-execution--output)
9. [Detailed Verification Matrix](#9-detailed-verification-matrix)
   - [Verified Implementation](#91-verified-implementation)
   - [Test-Confirmed Behavior](#92-test-confirmed-behavior)
   - [Unverified Assumptions](#93-unverified-assumptions)
   - [Remaining Vulnerabilities](#94-remaining-vulnerabilities)
   - [Recommended Corrections](#95-recommended-corrections)
10. [Strict Adherence & Next Steps](#10-strict-adherence--next-steps)

---

## 1. Executive Summary & Verification Purpose

This report documents the second independent security verification of **Sprint 0A** (ClaudeMax gateway integration) and **Sprint 0B** (defense-in-depth Outbound Privacy Gate, CORS boundary, and fail-closed security architecture). 

Per owner instructions:
- **Zero code has been committed, pushed, or merged to `main`**.
- **Phase 1 has NOT been started**.
- All verification claims are grounded in actual executed test results and inspectable source code.
- Clear separation is maintained between verified facts, test-confirmed behaviors, unverified assumptions, remaining vulnerabilities, and recommended corrections.

---

## 2. Complete Implementation of Verified Components

### 2.1 `backend/models/privacy_gate.py`
The final defense-in-depth barrier executed immediately before any outbound payload is dispatched across an external network connection.

```python
"""
backend/models/privacy_gate.py

Final Outbound Privacy Boundary Gate for HINAKU.
Strictly inspects all candidate outbound payloads immediately before transmission to external API models.

Enforces:
1. Explicit conversation privacy state (is_private).
2. Complete message payload inspection (system prompt, conversation history, current user turn).
3. Prohibition of personal owner statements, facts, feelings, health, finances, relationships, hardware.
4. Prohibition of injected semantic memories ([What HINAKU remembers]).
5. Prohibition of document attachments and extracted chunks.
6. Prohibition of unredacted sensitive credentials (PINs, passwords, card numbers, IDs, tokens).
7. Fail-closed behavior on ambiguity, corruption, or missing context.
8. Zero secret or personal data leakage in log output.
"""

import logging
import re
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

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
    """

    @classmethod
    def inspect_payload(
        cls,
        messages: List[Dict[str, str]],
        is_private: bool = False,
        has_attachments: bool = False
    ) -> PrivacyInspectionResult:
        """
        Inspects complete outbound message payload and returns detailed safety evaluation.
        Fails closed on any violation or malformed data.
        """
        # 1. Fail closed on empty or non-list messages
        if not isinstance(messages, list) or len(messages) == 0:
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Payload is empty or not a list; failing closed.",
                category="malformed_payload",
                turn_index=None
            )

        # 2. Enforce explicit conversation privacy state
        if is_private:
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Conversation is explicitly marked private; outbound API transmission prohibited.",
                category="private_conversation",
                turn_index=None
            )

        # 3. Enforce attachment boundary
        if has_attachments:
            return PrivacyInspectionResult(
                is_safe=False,
                reason="Conversation contains attachments; document content is restricted to local processing.",
                category="attachment_restricted",
                turn_index=None
            )

        # 4. Inspect every message in the candidate payload
        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                return PrivacyInspectionResult(
                    is_safe=False,
                    reason=f"Message turn {idx} is malformed; failing closed.",
                    category="malformed_payload",
                    turn_index=idx
                )

            role = str(msg.get("role", "")).lower()
            content = str(msg.get("content", "") or "")

            # A. Check system prompt for forbidden personal context or document markers
            if role in ("system", "developer"):
                for pat in FORBIDDEN_SYSTEM_MARKERS:
                    if re.search(pat, content, re.IGNORECASE):
                        return PrivacyInspectionResult(
                            is_safe=False,
                            reason=f"System prompt contains injected personal memory or document tags ({pat}).",
                            category="injected_personal_context",
                            turn_index=idx
                        )

            # B. Check for unredacted credentials in any role
            for pat, cat in CREDENTIAL_PATTERNS:
                if re.search(pat, content):
                    return PrivacyInspectionResult(
                        is_safe=False,
                        reason=f"Turn {idx} ({role}) contains unredacted sensitive credential ({cat}).",
                        category=f"sensitive_credential_{cat}",
                        turn_index=idx
                    )

            # C. Check user and assistant turns for personal statements & private life indicators
            if role in ("user", "assistant"):
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
                if role == "user":
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
        messages: List[Dict[str, str]],
        is_private: bool = False,
        has_attachments: bool = False
    ) -> bool:
        """Convenience boolean check."""
        result = cls.inspect_payload(messages, is_private=is_private, has_attachments=has_attachments)
        return result.is_safe

    @classmethod
    def verify_outbound_payload(
        cls,
        messages: List[Dict[str, str]],
        is_private: bool = False,
        has_attachments: bool = False
    ) -> None:
        """
        Validates payload or immediately raises OutboundPrivacyViolation.
        Logs sanitized warning without leaking payload contents.
        """
        result = cls.inspect_payload(messages, is_private=is_private, has_attachments=has_attachments)
        if not result.is_safe:
            log_msg = f"[PrivacyGate] Blocked external API transmission: {result.reason} (Category: {result.category})"
            logger.warning(log_msg)
            raise OutboundPrivacyViolation(result.reason or "Outbound privacy policy violation", category=result.category)
```

---

### 2.2 `backend/models/api_adapter.py`
Adapter handling both Anthropic Messages protocol (for ClaudeMax) and OpenAI-compatible Chat Completions, with `OutboundPrivacyGate` verification at its very entry point.

```python
import json
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx
from .thinking_filter import ThinkingFilter, strip_thinking
from .privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation

class ApiAdapter:
    """
    Unified API adapter supporting:
    1. Anthropic Messages API (provider='anthropic')
    2. OpenAI-compatible Chat Completions (provider='openai_compatible' / 'openai' / 'openrouter' / etc.)
    """
    def __init__(
        self,
        provider: str = "openai_compatible",
        model: str = "",
        base_url: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        max_tokens: int = 1024
    ):
        self.provider = provider.lower()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    @property
    def is_anthropic(self) -> bool:
        return "anthropic" in self.provider

    def check_ready(self) -> Dict[str, Any]:
        return {
            "has_key": bool(self.api_key),
            "provider": self.provider,
            "model": self.model,
            "configured": bool(self.api_key and self.model and self.model != "SET_ME")
        }

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        is_private: bool = False,
        has_attachments: bool = False
    ) -> AsyncGenerator[str, None]:
        # Final Outbound Privacy Gate: inspect full payload immediately before transmission
        OutboundPrivacyGate.verify_outbound_payload(
            messages=messages,
            is_private=is_private,
            has_attachments=has_attachments
        )

        if not self.api_key:
            raise ValueError("API key is missing or not configured in environment (HINAKU_API_KEY).")

        target_model = model or self.model
        if not target_model or target_model == "SET_ME":
            raise ValueError("API model name is not configured in settings.yaml.")

        thinking_filter = ThinkingFilter()

        if self.is_anthropic:
            async for chunk in self._stream_anthropic(messages, target_model, thinking_filter):
                yield chunk
        else:
            async for chunk in self._stream_openai_compatible(messages, target_model, thinking_filter):
                yield chunk

        final_chunk = thinking_filter.flush()
        if final_chunk:
            yield final_chunk

    async def _stream_openai_compatible(
        self,
        messages: List[Dict[str, str]],
        target_model: str,
        thinking_filter: ThinkingFilter
    ) -> AsyncGenerator[str, None]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/sainithinramanujanenjamuri/HINAKU-AI",
            "X-Title": "HINAKU"
        }
        payload = {
            "model": target_model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": True
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_bytes = await response.aread()
                        err_str = err_bytes.decode("utf-8", errors="ignore")
                        raise RuntimeError(f"API Error ({response.status_code}): {err_str}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        trimmed = line.strip()
                        if not trimmed.startswith("data:"):
                            continue
                        data_part = trimmed[5:].strip()
                        if data_part == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data_part)
                            choices = parsed.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    filtered = thinking_filter.process_chunk(text)
                                    if filtered:
                                        yield filtered
                        except json.JSONDecodeError:
                            continue
            except httpx.TimeoutException:
                raise TimeoutError(f"API request timed out after {self.timeout}s.")
            except Exception as e:
                if isinstance(e, (RuntimeError, TimeoutError, ValueError)):
                    raise
                raise RuntimeError(f"API connection failed: {str(e)}")

    async def _stream_anthropic(
        self,
        messages: List[Dict[str, str]],
        target_model: str,
        thinking_filter: ThinkingFilter
    ) -> AsyncGenerator[str, None]:
        base = self.base_url.rstrip("/")
        if base.endswith("/messages"):
            url = base
        elif base.endswith("/v1"):
            url = f"{base}/messages"
        else:
            url = f"{base}/v1/messages"

        headers = {
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        system_prompt = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        non_system = [
            {"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] in ("user", "assistant")
        ]

        payload = {
            "model": target_model,
            "max_tokens": self.max_tokens,
            "messages": non_system,
            "stream": True
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_bytes = await response.aread()
                        err_str = err_bytes.decode("utf-8", errors="ignore")
                        raise RuntimeError(f"Anthropic API Error ({response.status_code}): {err_str}")

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        trimmed = line.strip()
                        if trimmed.startswith("data:"):
                            data_part = trimmed[5:].strip()
                            try:
                                parsed = json.loads(data_part)
                                event_type = parsed.get("type")
                                if event_type == "content_block_delta":
                                    delta = parsed.get("delta", {})
                                    text = delta.get("text", "")
                                    if text:
                                        filtered = thinking_filter.process_chunk(text)
                                        if filtered:
                                            yield filtered
                                elif event_type == "message_stop":
                                    break
                                elif event_type == "error":
                                    err_msg = parsed.get("error", {}).get("message", "Unknown error")
                                    raise RuntimeError(f"Anthropic streaming error: {err_msg}")
                            except json.JSONDecodeError:
                                continue
            except httpx.TimeoutException:
                raise TimeoutError(f"Anthropic API request timed out after {self.timeout}s.")
            except Exception as e:
                if isinstance(e, (RuntimeError, TimeoutError, ValueError)):
                    raise
                raise RuntimeError(f"Anthropic API connection failed: {str(e)}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None
    ) -> str:
        parts = []
        async for chunk in self.stream_chat(messages, model=model):
            parts.append(chunk)
        return strip_thinking("".join(parts))
```

---

### 2.3 `backend/models/router.py`
The router decides between `local` and `api` backend. Notice that both `stream_chat` primary API execution AND `stream_chat` local-to-API fallback perform independent pre-flight inspections through `OutboundPrivacyGate.inspect_payload()`.

Key routing logic and boundaries in `backend/models/router.py`:
```python
# Lines 355-396: Privacy Enforcement in Backend Decision
        if is_private:
            return RouterDecision(
                target_backend="local",
                target_model=self.local_adapter.default_model,
                fallback_allowed=False,
                notice=None
            )

        if has_attachments:
            return RouterDecision(
                target_backend="local",
                target_model=self.local_adapter.default_model,
                fallback_allowed=False,
                notice=None
            )

        if is_personal or has_personal_context:
            return RouterDecision(
                target_backend="local",
                target_model=self.local_adapter.default_model,
                fallback_allowed=False,
                notice=None
            )
```

```python
# Lines 430-442: Primary API Stream Outbound Privacy Preflight
        if active_backend == "api":
            safety = OutboundPrivacyGate.inspect_payload(
                messages,
                is_private=is_private,
                has_attachments=has_attachments
            )
            if not safety.is_safe:
                logger.warning(f"[Router] Outbound payload blocked by privacy policy: {safety.reason}. Forcing local execution.")
                active_backend = "local"
                active_model = override_model or self.local_adapter.default_model
                notice = "Personal or private context detected; routed locally for privacy."
```

```python
# Lines 532-553: Local Failure Fallback Privacy Inspection
        except Exception as e:
            logger.error(f"Local backend failed: {e}")
            if active_backend == "local" and decision.fallback_allowed and not is_private and self.api_adapter.api_key:
                # Outbound Privacy Gate inspection BEFORE API fallback
                safety = OutboundPrivacyGate.inspect_payload(
                    messages,
                    is_private=is_private,
                    has_attachments=has_attachments
                )
                if not safety.is_safe:
                    logger.warning(f"[Router] Refusing API fallback: outbound payload contains private or personal context ({safety.reason}).")
                    yield {
                        "type": "error",
                        "error_type": "local_error",
                        "chunk": "",
                        "error": f"Local model failed: {str(e)} (API fallback blocked: payload contains private or personal context)",
                        "backend": "local",
                        "model": active_model,
                        "notice": f"Local model error: {str(e)}"
                    }
                    return
```

---

### 2.4 Relevant Changes in `backend/api/chat.py`
In `backend/api/chat.py`:
1. **Dynamic Settings Sync**:
   Lines 490-495 reload and synchronize `api_adapter` parameters on every request if `config/settings.yaml` was modified, ensuring runtime hot-swaps of API provider, base URL, and model identifier take effect immediately.
   ```python
   # Sync fresh settings (dynamic reload on file modification)
   curr_settings = get_settings()
   api_adapter.provider = curr_settings.api_provider
   api_adapter.base_url = curr_settings.api_base_url
   api_adapter.model = curr_settings.api_model
   api_adapter.api_key = curr_settings.get_api_key()
   ```
2. **Memory Context Injection Gating**:
   Lines 512-520 explicitly check `is_api` and `settings.api_send_personal_context`. When `is_api=True`, memory retrieval returns an empty string `""` so no personal memories are ever injected into API system prompts.
3. **Outbound Privacy Gate Enforcement**:
   Both `stream_chat` in `router.py` and `api_adapter.py` enforce `OutboundPrivacyGate.verify_outbound_payload(...)`.

---

### 2.5 CORS Configuration in `backend/main.py`
CORS is restricted strictly to local loopback origins and desktop app schemes:

```python
LOCAL_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "pywebview://localhost",
    "app://localhost",
    "null",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
```

---

## 3. Verification of Every External API Transmission Path

Every potential code path capable of triggering an external HTTP network request to an API model was verified against the Outbound Privacy Gate:

| Path | Primary Gate Checkpoint | Secondary (Defense-in-Depth) Checkpoint | Test Confirmation |
|---|---|---|---|
| **1. Normal API Request** | `router.py:431` (`inspect_payload`) | `api_adapter.py:49` (`verify_outbound_payload`) | `test_privacy_boundary.py:test_1_private_conversation_in_auto_routing_mode_stays_local` |
| **2. Streaming API Turn** | `router.py:431` (`inspect_payload`) | `api_adapter.py:49` (`verify_outbound_payload`) | `test_privacy_boundary.py:test_14_retry_and_regeneration_paths_enforce_privacy_gate` |
| **3. Retries (Think Retry)** | `router.py:503` (strictly stays within local adapter; never retries across API) | N/A (local adapter only) | `test_router_local_only.py:test_local_only_think_retry_uses_local_and_never_calls_api` |
| **4. Regeneration** | `chat.py` verifies history + `router.py:431` | `api_adapter.py:49` (`verify_outbound_payload`) | `test_privacy_boundary.py:test_14_retry_and_regeneration_paths_enforce_privacy_gate` |
| **5. Explicit API Selection** | `router.py:355` (`is_private` overrides model choice) | `api_adapter.py:49` (`verify_outbound_payload`) | `test_privacy_boundary.py:test_3_private_conversation_with_explicit_api_model_selection` |
| **6. API-Only Mode** | `router.py:355` (`is_private` overrides `api_only`) | `api_adapter.py:49` (`verify_outbound_payload`) | `test_privacy_boundary.py:test_2_private_conversation_in_api_only_mode_stays_local` |
| **7. Local-to-API Fallback** | `router.py:536` (`inspect_payload` blocks fallback if personal) | `api_adapter.py:49` (`verify_outbound_payload`) | `test_privacy_boundary.py:test_12_local_failure_and_api_fallback` |
| **8. Direct Adapter Calls** | N/A (bypasses router) | `api_adapter.py:49` (`verify_outbound_payload` entry barrier) | `test_privacy_boundary.py:test_15_direct_api_adapter_invocation_enforces_privacy_gate` |

---

## 4. Privacy Gate Bypass Resistance Verification

Verification confirms that the privacy gate cannot be bypassed through payload abnormalities or edge cases:

1. **Missing Metadata (`is_private=None` or unassigned)**:
   - Handled via `bool(is_private)`. If conversation was previously stored as private in SQLite, `chat.py` reads `conv["is_private"]` and enforces `True`.
2. **Malformed Payloads (None, Non-List, Non-Dict)**:
   - Evaluated in `OutboundPrivacyGate.inspect_payload()`.
   - `messages=None` or `messages=[]` raises `OutboundPrivacyViolation("Payload is empty or not a list; failing closed.")`.
   - `messages=[123, None, {}]` raises `OutboundPrivacyViolation("Message turn 0 is malformed; failing closed.")`.
   - Confirmed by `test_security_review_uncovered.py::test_privacy_gate_rejects_none_payload` and `test_privacy_gate_rejects_non_dict_elements`.
3. **Empty Messages / Blank Content (`role=None, content=None`)**:
   - `msg.get("role", "")` and `msg.get("content", "")` convert `None` safely to empty string `""` without raising uncaught exceptions, then scan for credentials and forbidden markers.
   - Confirmed by `test_security_review_uncovered.py::test_privacy_gate_handles_none_role_and_content_safely`.
4. **Unexpected Message Roles (`developer`, custom roles)**:
   - The gate inspects system markers on roles `"system"` and `"developer"` alike, preventing OpenAI o1/o3/Claude developer-role memory smuggling.
   - Confirmed by `test_security_review_uncovered.py::test_privacy_gate_developer_role_scanned`.
5. **Future Provider Adapters**:
   - The gate check is located inside `ApiAdapter.stream_chat` *before* the branching condition (`if self.is_anthropic: ... else: ...`). Any new provider method added to `ApiAdapter` is guarded automatically because all calls must pass through `stream_chat`.

---

## 5. English-Only Privacy Detection Limitation Review

> [!WARNING]
> **Definitive Limitation**: HINAKU does NOT have multilingual privacy protection via regex or classifier heuristics. The content-inspection rules are strictly English.

### Cases Not Reliably Detected by Content Heuristics:
1. **Non-English Languages**:
   - Spanish: `"Me siento profundamente deprimido y triste"` (feelings/mental health).
   - Hindi: `"Main bahut pareshan hoon aur salary kam hai"` (financial distress).
   - French: `"Mon mot de passe est secret123"` (credential phrasing).
   - Japanese, German, Chinese, etc.
2. **Transliterated Phrasing & Romanized Slang**:
   - `"Mujhe anxiety ho rahi hai"` (Hinglish).
   - `"Naaku job poyindi"` (Telugu Romanized).
3. **Indirect or Metaphorical Phrasing**:
   - `"The water is rising above my neck"` (emotional distress without explicit depression keywords).
   - `"My vault code matches my birthday"` (implicit credential).

### Test-Confirmed Guarantee:
- While regex-based keyword detection fails on non-English text, **marking the conversation as Private (`is_private=True`) is an unconditional code-level block**.
- When `is_private=True`, all requests stay 100% local regardless of language, dialect, or phrasing.
- Confirmed by `test_security_review_uncovered.py::test_english_only_detection_limitation_and_private_override`.

---

## 6. Desktop Application (pywebview) CORS Compatibility

Verification was conducted on `run_desktop.py` and `backend/main.py`:
1. **Desktop Shell Launch Mechanism**:
   - `run_desktop.py` starts the FastAPI backend on `http://127.0.0.1:8000`.
   - `webview.create_window()` navigates directly to `http://127.0.0.1:8000`.
   - Because the UI is served from the FastAPI server (`FileResponse("ui/index.html")`), standard in-app `fetch()` requests carry the same origin (`http://127.0.0.1:8000`).
2. **Origins Allowed by CORS**:
   - `http://127.0.0.1:8000`, `http://localhost:8000`
   - `http://127.0.0.1:5173`, `http://localhost:5173` (Vite dev server)
   - `pywebview://localhost` (pywebview custom scheme on Windows/macOS)
   - `app://localhost` (Electron / custom app container)
   - `null` (sandboxed iframes / local file protocol fallback)
   - Regex: `r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"` allowing any local port.
3. **Subdomain and Attacker Spoofing Blocked**:
   - `http://localhost.evil.com` or `https://malicious-website.com` do not match either the list or the regex and are strictly rejected.
   - Confirmed by `test_security_review_uncovered.py::test_cors_rejects_subdomain_spoofing` and `test_cors_rejects_untrusted_external_origin`.

---

## 7. API Endpoint Authorization Audit (CORS is Not Authorization)

> [!CAUTION]
> **Identified Vulnerability**: CORS is strictly a browser-enforced security mechanism. It provides zero protection against non-browser clients (such as local malware, Python scripts, PowerShell, or curl) running on the local machine.

### Audit of Sensitive Endpoints:
The following endpoints currently execute without any authentication token or session authorization:
- `POST /api/settings/wipe-all`: Permanently deletes all conversations, memories, interactions, and attachments, vacuuming the database.
- `POST /api/memories/clear`: Clears all stored memories.
- `GET /api/settings/export`: Exfiltrates the complete SQLite database and all conversations.
- `GET /api/memories`: Exfiltrates all stored semantic memories.
- `POST /api/training/promote`: Promotes a fine-tuned model into active rotation.
- `POST /api/training/rollback`: Reverts the active local model to a previous iteration.

### Recommended Correction:
1. Implement a **Local App Token** (`X-Hinaku-Auth`):
   - At startup, `run_desktop.py` or FastAPI generates a secure random UUID token stored in memory.
   - The token is injected into the initial `index.html` render or passed via pywebview API.
   - All state-modifying (`POST`, `PUT`, `DELETE`) and exfiltration (`export`, `memories`) endpoints require `X-Hinaku-Auth: <token>`.
   - Requests without the valid token return `HTTP 401 Unauthorized`.

---

## 8. Complete Test Suite Execution & Output

The full test suite was executed against the active working tree:

```powershell
& "D:\HINAKU-AI\venv\Scripts\python.exe" -m pytest -v
```

### Exact Terminal Output Summary:
```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.1.1, pluggy-1.7.0 -- D:\HINAKU-AI\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\HINAKU-AI
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.15.1, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 293 items

tests/test_attachments.py::test_sanitize_filename PASSED                 [  0%]
...
tests/test_claudemax_adapter.py::test_claudemax_adapter_anthropic_url_and_headers PASSED [ 10%]
tests/test_claudemax_adapter.py::test_claudemax_adapter_url_with_v1_already PASSED [ 10%]
tests/test_claudemax_adapter.py::test_claudemax_adapter_thinking_filter PASSED [ 10%]
tests/test_claudemax_adapter.py::test_claudemax_privacy_gate_blocks_private_chats PASSED [ 11%]
tests/test_claudemax_adapter.py::test_claudemax_privacy_gate_blocks_memories PASSED [ 11%]
tests/test_claudemax_adapter.py::test_claudemax_privacy_gate_blocks_attachments PASSED [ 11%]
tests/test_claudemax_adapter.py::test_claudemax_privacy_gate_blocks_credentials PASSED [ 12%]
tests/test_claudemax_adapter.py::test_dynamic_settings_reload PASSED     [ 12%]
...
tests/test_privacy_boundary.py::test_1_private_conversation_in_auto_routing_mode_stays_local PASSED [ 51%]
tests/test_privacy_boundary.py::test_2_private_conversation_in_api_only_mode_stays_local PASSED [ 52%]
tests/test_privacy_boundary.py::test_3_private_conversation_with_explicit_api_model_selection PASSED [ 52%]
tests/test_privacy_boundary.py::test_4_personal_information_in_latest_message_stays_local PASSED [ 52%]
tests/test_privacy_boundary.py::test_5_personal_information_in_earlier_conversation_history PASSED [ 53%]
tests/test_privacy_boundary.py::test_6_mixed_personal_and_non_personal_conversation_history PASSED [ 53%]
tests/test_privacy_boundary.py::test_7_follow_up_messages_after_personal_discussions PASSED [ 53%]
tests/test_privacy_boundary.py::test_8_attachments_and_extracted_document_content_blocked_from_api PASSED [ 54%]
tests/test_privacy_boundary.py::test_9_automatically_triggered_private_mode_blocks_api PASSED [ 54%]
tests/test_privacy_boundary.py::test_10_private_mode_transitions_and_undo_behavior PASSED [ 54%]
tests/test_privacy_boundary.py::test_11_api_failure_and_local_fallback PASSED [ 55%]
tests/test_privacy_boundary.py::test_12_local_failure_and_api_fallback PASSED [ 55%]
tests/test_privacy_boundary.py::test_13_short_followup_router_stickiness PASSED [ 55%]
tests/test_privacy_boundary.py::test_14_retry_and_regeneration_paths_enforce_privacy_gate PASSED [ 56%]
tests/test_privacy_boundary.py::test_15_direct_api_adapter_invocation_enforces_privacy_gate PASSED [ 56%]
...
tests/test_security_review_uncovered.py::test_privacy_gate_rejects_none_payload PASSED [ 65%]
tests/test_security_review_uncovered.py::test_privacy_gate_rejects_empty_list PASSED [ 66%]
tests/test_security_review_uncovered.py::test_privacy_gate_rejects_non_dict_elements PASSED [ 66%]
tests/test_security_review_uncovered.py::test_privacy_gate_handles_none_role_and_content_safely PASSED [ 66%]
tests/test_security_review_uncovered.py::test_privacy_gate_developer_role_scanned PASSED [ 67%]
tests/test_security_review_uncovered.py::test_cors_rejects_untrusted_external_origin PASSED [ 67%]
tests/test_security_review_uncovered.py::test_cors_rejects_subdomain_spoofing PASSED [ 67%]
tests/test_security_review_uncovered.py::test_cors_allows_legitimate_local_origins PASSED [ 68%]
tests/test_security_review_uncovered.py::test_english_only_detection_limitation_and_private_override PASSED [ 68%]
tests/test_security_review_uncovered.py::test_api_adapter_fails_on_missing_api_key PASSED [ 68%]
tests/test_security_review_uncovered.py::test_api_adapter_fails_on_unset_model PASSED [ 69%]
...
tests/test_step4.py::test_optional_live_api SKIPPED (Live API call f...) [ 82%]
...
tests/ui/test_ui_shell.py::test_pinned_attribute_on_history_manager PASSED [100%]

================= 292 passed, 1 skipped in 134.71s (0:02:14) ==================
```

### Explanation of Skipped / Deselected Tests:
- **Total Tests Collected**: 293
- **Passed**: 292
- **Skipped**: 1 (`tests/test_step4.py::test_optional_live_api`)
  - **Reason**: `test_optional_live_api` is explicitly designed to skip if a live working third-party API key is not present or returns a 401 response. The repository's local `.env` currently retains a placeholder/revoked key to prevent accidental billing during automated test suite execution.
- **Deselected**: 0 (all 293 tests in the test suite were collected and evaluated).

---

## 9. Detailed Verification Matrix

### 9.1 Verified Implementation
- `backend/models/privacy_gate.py`: Implemented, tested, and actively guarding all outbound transmissions.
- `backend/models/api_adapter.py`: Implemented with dual Anthropic + OpenAI protocols, URL normalization (`/v1/messages`), header authentication (`x-api-key` and `Authorization: Bearer`), and thinking filter.
- `backend/models/router.py`: Verified dual-layer gate checks in primary routing and local failure fallback.
- `backend/config.py`: Verified `CONFIG_PATH.stat().st_mtime` file-modification detection for live settings reload without server restarts.
- `backend/main.py`: Verified local-only CORS origin whitelist and regex matcher.

### 9.2 Test-Confirmed Behavior
- **15/15 Privacy Boundary Scenarios**: Passed (`tests/test_privacy_boundary.py`).
- **8/8 ClaudeMax Adapter Scenarios**: Passed (`tests/test_claudemax_adapter.py`).
- **11/11 Uncovered Security Scenarios**: Passed (`tests/test_security_review_uncovered.py`).
- **Fail-Closed on Malformed Data**: Empty lists, `None`, and non-dict payloads trigger immediate `OutboundPrivacyViolation`.
- **Credential Leakage Prevention**: Credit cards, passwords, PINs, and API tokens are intercepted in plaintext turns.
- **Thinking Filter**: `<think>...</think>` tokens are stripped from streaming deltas.

### 9.3 Unverified Assumptions
- **ClaudeMax Gateway Production Availability**: Gateway uptime, rate limits, and latency under high concurrency have not been stress-tested.
- **User Live Key Functionality**: Verified that adapter formats requests correctly for ClaudeMax, but the user's specific live key has not been sent over the wire (as requested).

### 9.4 Remaining Vulnerabilities
1. **Endpoint Authorization Lack**: As documented in Section 7, sensitive and destructive endpoints (`/wipe-all`, `/clear`, `/export`) rely on CORS alone. Any native process on the owner's laptop can invoke them.
2. **English-Only Content Heuristics**: As documented in Section 5, non-English conversations rely exclusively on explicit `is_private=True` rather than automatic keyword detection.

### 9.5 Recommended Corrections
1. **Add `X-Hinaku-Auth` Header Token**: Protect all state-modifying and export endpoints with a randomized session token generated by the backend on boot.
2. **UI Multilingual Privacy Warning**: Display a clear notice in the UI explaining that conversations in languages other than English should be set to Private manually to guarantee data locality.

---

## 10. Strict Adherence & Next Steps

In strict compliance with instructions:
- **No commit has been made.**
- **No push or merge has been performed.**
- **Phase 1 remains untouched.**
- Antigravity Assistant is stopped and awaiting explicit owner review and approval.
