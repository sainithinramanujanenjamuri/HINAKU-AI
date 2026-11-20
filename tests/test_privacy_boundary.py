"""
tests/test_privacy_boundary.py

Comprehensive Outbound Privacy Boundary Test Suite for Sprint 0B.
Tests cover all 15 required security scenarios verifying that private and personal content
never leaves the machine to external API providers.
All external adapters are mocked; no real external network requests are made.
Exact payloads that would be transmitted are asserted.
"""

import pytest
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models.router import ModelRouter, RouterDecision
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.api_adapter import ApiAdapter
from backend.models.privacy_gate import OutboundPrivacyGate, OutboundPrivacyViolation


class MockOllamaAdapter:
    def __init__(self, default_model: str = "bonsai-2:9b", fail: bool = False):
        self.default_model = default_model
        self.fail = fail
        self.calls: List[Dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        self.calls.append({
            "model": model or self.default_model,
            "messages": [dict(m) for m in messages],
            "kwargs": kwargs
        })
        if self.fail:
            raise RuntimeError("Simulated Ollama local failure")
        yield "Local response"


class MockApiAdapter:
    def __init__(self, model: str = "test-api-model", api_key: str = "test-key", fail: bool = False):
        self.provider = "openai_compatible"
        self.model = model
        self.api_key = api_key
        self.fail = fail
        self.transmitted_payloads: List[Dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        is_private: bool = False,
        has_attachments: bool = False
    ) -> AsyncGenerator[str, None]:
        # Enforce OutboundPrivacyGate identical to real ApiAdapter
        OutboundPrivacyGate.verify_outbound_payload(
            messages=messages,
            is_private=is_private,
            has_attachments=has_attachments
        )
        self.transmitted_payloads.append({
            "model": model or self.model,
            "messages": [dict(m) for m in messages],
            "is_private": is_private,
            "has_attachments": has_attachments
        })
        if self.fail:
            raise RuntimeError("Simulated API network error")
        yield "API response"


@pytest.fixture
def mock_pipeline():
    local = MockOllamaAdapter(default_model="bonsai-2:9b")
    api = MockApiAdapter(model="test-api-model", api_key="test-key")
    router = ModelRouter(local_adapter=local, api_adapter=api, mode="auto")
    return local, api, router


# ==============================================================================
# Scenario 1: Private conversation in automatic routing mode
# ==============================================================================
@pytest.mark.asyncio
async def test_1_private_conversation_in_auto_routing_mode_stays_local(mock_pipeline):
    local, api, router = mock_pipeline
    prompt = "Explain quantum computing and write an algorithm in Python"
    messages = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": prompt}
    ]

    decision = router.decide_backend(prompt, is_private=True)
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    events = []
    async for evt in router.stream_chat(messages, user_prompt=prompt, is_private=True):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "API received payload during private chat in auto mode!"
    assert len(local.calls) == 1


# ==============================================================================
# Scenario 2: Private conversation in API-only mode
# ==============================================================================
@pytest.mark.asyncio
async def test_2_private_conversation_in_api_only_mode_stays_local(mock_pipeline):
    local, api, router = mock_pipeline
    router.mode = "api_only"
    prompt = "Compare merge sort versus quick sort in Python"
    messages = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": prompt}
    ]

    decision = router.decide_backend(prompt, is_private=True)
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    events = []
    async for evt in router.stream_chat(messages, user_prompt=prompt, is_private=True):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "API received payload during private chat in api_only mode!"


# ==============================================================================
# Scenario 3: Private conversation with explicit API model selection
# ==============================================================================
@pytest.mark.asyncio
async def test_3_private_conversation_with_explicit_api_model_selection(mock_pipeline):
    local, api, router = mock_pipeline
    prompt = "Write a comprehensive C++ matrix multiplication function"
    messages = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": prompt}
    ]

    decision = router.decide_backend(prompt, is_private=True, requested_model="test-api-model")
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    events = []
    async for evt in router.stream_chat(
        messages,
        user_prompt=prompt,
        is_private=True,
        requested_model="test-api-model"
    ):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "API received payload during explicit API model selection in private chat!"


# ==============================================================================
# Scenario 4: Personal information in the latest message
# ==============================================================================
@pytest.mark.asyncio
async def test_4_personal_information_in_latest_message_stays_local(mock_pipeline):
    local, api, router = mock_pipeline
    prompt = "I have a high fever of 103F and severe headache, what medication should I consider?"
    messages = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": prompt}
    ]

    decision = router.decide_backend(prompt, is_private=False)
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    events = []
    async for evt in router.stream_chat(messages, user_prompt=prompt, is_private=False):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "API received personal medical information!"


# ==============================================================================
# Scenario 5: Personal information in earlier conversation history
# ==============================================================================
@pytest.mark.asyncio
async def test_5_personal_information_in_earlier_conversation_history(mock_pipeline):
    local, api, router = mock_pipeline
    # Turn 1: Personal health disclosure
    # Turn 2: General coding query that would normally route to API
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "My salary is 45000 and I am struggling with debt."},
        {"role": "assistant", "content": "Take it one step at a time."},
        {"role": "user", "content": "Can you explain how quicksort works in Python?"}
    ]
    latest_prompt = "Can you explain how quicksort works in Python?"

    # Outbound privacy gate inspects entire history
    safety = OutboundPrivacyGate.inspect_payload(history, is_private=False, has_attachments=False)
    assert safety.is_safe is False
    assert "personal_statement" in (safety.category or "") or "sensitive_topic" in (safety.category or "")

    events = []
    async for evt in router.stream_chat(history, user_prompt=latest_prompt, is_private=False):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "API received history containing prior personal financial statements!"


# ==============================================================================
# Scenario 6: Mixed personal and non-personal conversation history
# ==============================================================================
@pytest.mark.asyncio
async def test_6_mixed_personal_and_non_personal_conversation_history(mock_pipeline):
    local, api, router = mock_pipeline
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "What is the capital of Australia?"},
        {"role": "assistant", "content": "Canberra."},
        {"role": "user", "content": "I am feeling depressed and lonely today."},
        {"role": "assistant", "content": "Step away from work. Talk to someone close."},
        {"role": "user", "content": "Write a regex to match email addresses"}
    ]
    latest_prompt = "Write a regex to match email addresses"

    events = []
    async for evt in router.stream_chat(history, user_prompt=latest_prompt, is_private=False):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "API received mixed history with mental health statements!"


# ==============================================================================
# Scenario 7: Follow-up messages after personal discussions
# ==============================================================================
@pytest.mark.asyncio
async def test_7_follow_up_messages_after_personal_discussions(mock_pipeline):
    local, api, router = mock_pipeline
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "My wife and I are going through a painful divorce."},
        {"role": "assistant", "content": "Focus on the essentials today."},
        {"role": "user", "content": "why?"}
    ]
    followup_prompt = "why?"

    events = []
    async for evt in router.stream_chat(history, user_prompt=followup_prompt, is_private=False, last_backend="local"):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "Follow-up after personal conversation leaked to API!"


# ==============================================================================
# Scenario 8: Attachments and extracted document content
# ==============================================================================
@pytest.mark.asyncio
async def test_8_attachments_and_extracted_document_content_blocked_from_api(mock_pipeline):
    local, api, router = mock_pipeline
    doc_prompt = "Summarize this uploaded syllabus"
    history = [
        {
            "role": "system",
            "content": "You are HINAKU.\n\n<document_reference>\n[File: midterm.pdf, Page: 1]\nSecurity in AI systems.\n</document_reference>"
        },
        {"role": "user", "content": doc_prompt}
    ]

    # Inspection directly on payload
    safety = OutboundPrivacyGate.inspect_payload(history, is_private=False, has_attachments=True)
    assert safety.is_safe is False

    events = []
    async for evt in router.stream_chat(history, user_prompt=doc_prompt, is_private=False, has_attachments=True):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "Document attachment content leaked to external API!"


# ==============================================================================
# Scenario 9: Automatically triggered private mode
# ==============================================================================
@pytest.mark.asyncio
async def test_9_automatically_triggered_private_mode_blocks_api(mock_pipeline):
    local, api, router = mock_pipeline
    prompt = "I feel so hopeless and burned out, I can't go on like this."
    from backend.guards import is_sensitive_topic
    is_sens, cat = is_sensitive_topic(prompt)
    assert is_sens is True

    # Auto private triggers
    is_private_auto = True
    decision = router.decide_backend(prompt, is_private=is_private_auto)
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": prompt}
    ]
    events = []
    async for evt in router.stream_chat(history, user_prompt=prompt, is_private=is_private_auto):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "Auto-private conversation sent payload to API!"


# ==============================================================================
# Scenario 10: Private-mode transitions and undo behavior
# ==============================================================================
@pytest.mark.asyncio
async def test_10_private_mode_transitions_and_undo_behavior(mock_pipeline):
    local, api, router = mock_pipeline
    # User had a conversation containing personal data, but untoggled is_private
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "I live at 742 Evergreen Terrace."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "Explain binary search in Rust"}
    ]
    latest_prompt = "Explain binary search in Rust"

    # Even if is_private is passed as False (untoggled by user), the OutboundPrivacyGate rejects transmission!
    safety = OutboundPrivacyGate.inspect_payload(history, is_private=False, has_attachments=False)
    assert safety.is_safe is False
    assert "personal_statement" in (safety.category or "")

    events = []
    async for evt in router.stream_chat(history, user_prompt=latest_prompt, is_private=False):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "Untoggling private mode leaked earlier personal address to API!"


# ==============================================================================
# Scenario 11: API failure and local fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_11_api_failure_and_local_fallback(mock_pipeline):
    local, api, router = mock_pipeline
    api.fail = True  # Simulate API network outage
    prompt = "Explain Dijkstra's shortest path algorithm in detail"
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": prompt}
    ]

    events = []
    async for evt in router.stream_chat(history, user_prompt=prompt, is_private=False, is_detail=True):
        events.append(evt)

    # API attempted, failed, and safely fell back to local
    assert any(e.get("backend") == "local" for e in events)
    assert any("fell back to local model" in str(e.get("notice", "")).lower() for e in events)
    assert len(local.calls) == 1


# ==============================================================================
# Scenario 12: Local failure and API fallback
# ==============================================================================
@pytest.mark.asyncio
async def test_12_local_failure_and_api_fallback(mock_pipeline):
    local, api, router = mock_pipeline
    local.fail = True  # Simulate local Ollama failure

    # Case A: Personal statement -> API fallback MUST BE BLOCKED
    personal_prompt = "I'm stressed and feeling overwhelmed with work."
    personal_history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": personal_prompt}
    ]
    events_personal = []
    async for evt in router.stream_chat(personal_history, user_prompt=personal_prompt, is_private=False):
        events_personal.append(evt)

    assert len(api.transmitted_payloads) == 0, "Personal prompt fell back to API when local was offline!"
    assert any(e.get("type") == "error" for e in events_personal)

    # Case B: Neutral non-personal coding query -> API fallback allowed
    code_prompt = "Explain quicksort algorithm with time complexity"
    code_history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": code_prompt}
    ]
    events_code = []
    async for evt in router.stream_chat(code_history, user_prompt=code_prompt, is_private=False):
        events_code.append(evt)

    assert len(api.transmitted_payloads) == 1, "Neutral query failed to fall back to API when local was offline!"
    # Assert exact transmitted payload
    sent = api.transmitted_payloads[0]
    assert sent["messages"] == code_history
    assert sent["is_private"] is False
    assert sent["has_attachments"] is False


# ==============================================================================
# Scenario 13: Short-follow-up router stickiness
# ==============================================================================
@pytest.mark.asyncio
async def test_13_short_followup_router_stickiness(mock_pipeline):
    local, api, router = mock_pipeline
    # If prior turn was local because of personal data, short follow-up must NOT stick to API
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "My doctor said I have acute bronchitis."},
        {"role": "assistant", "content": "Rest well and take care."},
        {"role": "user", "content": "what else?"}
    ]
    followup = "what else?"

    events = []
    async for evt in router.stream_chat(history, user_prompt=followup, is_private=False, last_backend="local"):
        events.append(evt)

    assert any(e.get("backend") == "local" for e in events)
    assert len(api.transmitted_payloads) == 0, "Short follow-up leaked prior medical conversation to API!"


# ==============================================================================
# Scenario 14: Retry and regeneration paths
# ==============================================================================
@pytest.mark.asyncio
async def test_14_retry_and_regeneration_paths_enforce_privacy_gate(mock_pipeline):
    local, api, router = mock_pipeline
    # Regenerating an answer where history has personal data
    history = [
        {"role": "system", "content": "You are HINAKU."},
        {"role": "user", "content": "My password is mysecretpassword123"},
        {"role": "assistant", "content": "I don't store passwords."},
        {"role": "user", "content": "Regenerate that reply with more detail"}
    ]
    retry_prompt = "Regenerate that reply with more detail"

    events = []
    async for evt in router.stream_chat(history, user_prompt=retry_prompt, is_private=False, is_detail=True):
        events.append(evt)

    assert len(api.transmitted_payloads) == 0, "Regeneration path transmitted credentials to API!"


# ==============================================================================
# Scenario 15: Direct API adapter invocation
# ==============================================================================
@pytest.mark.asyncio
async def test_15_direct_api_adapter_invocation_enforces_privacy_gate():
    api = ApiAdapter(provider="openai_compatible", model="test-api-model", api_key="test-key")

    # Case A: Private conversation flag set
    with pytest.raises(OutboundPrivacyViolation) as exc1:
        async for _ in api.stream_chat(
            messages=[{"role": "user", "content": "Neutral query"}],
            is_private=True,
            has_attachments=False
        ):
            pass
    assert "private" in str(exc1.value).lower()

    # Case B: Attachments present
    with pytest.raises(OutboundPrivacyViolation) as exc2:
        async for _ in api.stream_chat(
            messages=[{"role": "user", "content": "Neutral query"}],
            is_private=False,
            has_attachments=True
        ):
            pass
    assert "attachment" in str(exc2.value).lower()

    # Case C: Personal statement in messages
    with pytest.raises(OutboundPrivacyViolation) as exc3:
        async for _ in api.stream_chat(
            messages=[
                {"role": "system", "content": "You are HINAKU."},
                {"role": "user", "content": "I am feeling stressed and worried about my exams"}
            ],
            is_private=False,
            has_attachments=False
        ):
            pass
    assert "personal" in str(exc3.value).lower() or "sensitive" in str(exc3.value).lower()

    # Case D: Injected personal memory in system prompt
    with pytest.raises(OutboundPrivacyViolation) as exc4:
        async for _ in api.stream_chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are HINAKU.\n\n[What HINAKU remembers about you]\n- Owner uses Python 3.11\n- Owner has RTX 4050"
                },
                {"role": "user", "content": "What is 2 + 2?"}
            ],
            is_private=False,
            has_attachments=False
        ):
            pass
    assert "personal memory" in str(exc4.value).lower() or "injected" in str(exc4.value).lower()

    # Case E: Unredacted sensitive credentials
    with pytest.raises(OutboundPrivacyViolation) as exc5:
        async for _ in api.stream_chat(
            messages=[
                {"role": "system", "content": "You are HINAKU."},
                {"role": "user", "content": "My pin is 9876"}
            ],
            is_private=False,
            has_attachments=False
        ):
            pass
    assert "sensitive credential" in str(exc5.value).lower() or "pin" in str(exc5.value).lower()

    # Case F: Missing metadata fails closed
    with pytest.raises(OutboundPrivacyViolation) as exc6:
        async for _ in api.stream_chat(
            messages=[{"role": "user", "content": "Neutral query"}]
        ):
            pass
    assert "invalid_privacy_metadata" == exc6.value.category
