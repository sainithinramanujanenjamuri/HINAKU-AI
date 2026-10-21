import os
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import get_settings
from backend.persona import PersonaManager, DEFAULT_FALLBACK_PROMPT
from backend.models.thinking_filter import ThinkingFilter, strip_thinking, strip_meta_commentary
import backend.api.chat as chat_module

client = TestClient(app)

def test_persona_loads():
    settings = get_settings()
    manager = PersonaManager(settings.persona_file)
    state = manager.get_persona()

    assert not state.is_fallback
    assert state.notice is None
    assert "You are HINAKU" in state.content
    assert state.content == settings.persona_file.read_text(encoding="utf-8").strip()

def test_persona_missing_file_fallback(tmp_path, caplog):
    missing_file = tmp_path / "non_existent_persona.md"
    manager = PersonaManager(missing_file)

    with caplog.at_level("WARNING"):
        state = manager.get_persona()

    assert state.is_fallback is True
    assert state.content == DEFAULT_FALLBACK_PROMPT
    assert "missing" in state.notice.lower()
    assert any("missing" in record.message.lower() for record in caplog.records)

def test_persona_empty_file_fallback(tmp_path, caplog):
    empty_file = tmp_path / "empty_persona.md"
    empty_file.write_text("   \n   ", encoding="utf-8")
    manager = PersonaManager(empty_file)

    with caplog.at_level("WARNING"):
        state = manager.get_persona()

    assert state.is_fallback is True
    assert state.content == DEFAULT_FALLBACK_PROMPT
    assert "empty" in state.notice.lower()
    assert any("empty" in record.message.lower() for record in caplog.records)

def test_persona_hot_reload_on_change(tmp_path):
    dynamic_file = tmp_path / "dynamic_persona.md"
    dynamic_file.write_text("Initial persona text", encoding="utf-8")
    manager = PersonaManager(dynamic_file)

    state1 = manager.get_persona()
    assert state1.content == "Initial persona text"
    assert state1.is_fallback is False

    # Simulate edit and modification time change
    time.sleep(0.05)
    dynamic_file.write_text("Updated persona text with new directives", encoding="utf-8")
    # Ensure mtime is strictly greater
    current_mtime = dynamic_file.stat().st_mtime
    os.utime(dynamic_file, (current_mtime + 2, current_mtime + 2))

    state2 = manager.get_persona()
    assert state2.content == "Updated persona text with new directives"
    assert state2.is_fallback is False

def test_persona_included_in_request(monkeypatch):
    captured_messages = []

    async def fake_stream_chat(messages, model=None):
        captured_messages.extend(messages)
        yield "Fake response"

    monkeypatch.setattr(chat_module.adapter, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(chat_module.memory_manager, "enabled", False)

    response = client.post("/api/chat", json={
        "messages": [
            {"role": "system", "content": "Client rogue system prompt"},
            {"role": "user", "content": "Hello HINAKU"}
        ],
        "stream": True
    })

    assert response.status_code == 200
    # First message must be the system message containing the persona
    assert len(captured_messages) > 0
    assert captured_messages[0]["role"] == "system"
    assert "You are HINAKU" in captured_messages[0]["content"]
    # The client's rogue system prompt must be filtered out
    roles = [m["role"] for m in captured_messages]
    assert roles == ["system", "user"]
    assert captured_messages[1]["content"] == "Hello HINAKU"

def test_thinking_filter_strip_complete():
    text = "<think>Internal reasoning step</think>I am HINAKU, an AI."
    assert strip_thinking(text) == "I am HINAKU, an AI."

    text_multiline = "<think>\nStep 1: Analyze user request.\nStep 2: Formulate reply.\n</think>\n\nDarkness is infinite."
    assert strip_thinking(text_multiline) == "Darkness is infinite."

def test_thinking_filter_streaming_chunks():
    chunks = ["<th", "ink>\nLet me think about this.\n</th", "ink>\nHello! I am ", "HINAKU."]
    filt = ThinkingFilter()
    output = []
    for c in chunks:
        out = filt.process_chunk(c)
        if out:
            output.append(out)
    rem = filt.flush()
    if rem:
        output.append(rem)

    result = "".join(output)
    assert "<think>" not in result
    assert "Let me think" not in result
    assert result == "Hello! I am HINAKU."

def test_thinking_filter_preserves_regular_less_than():
    chunks = ["If x < 5 and y > 3 then return True.", " Also <vector<int>>."]
    filt = ThinkingFilter()
    output = []
    for c in chunks:
        out = filt.process_chunk(c)
        if out:
            output.append(out)
    rem = filt.flush()
    if rem:
        output.append(rem)

    result = "".join(output)
    assert result == "If x < 5 and y > 3 then return True. Also <vector<int>>."

def test_strip_meta_commentary_cases():
    assert strip_meta_commentary("It is a question about the day.\nI am here.") == "I am here."
    assert strip_meta_commentary("The user wants assistance.\nHINAKU at your service.") == "HINAKU at your service."
    assert strip_meta_commentary("I should answer with precision.\nUnderstood.") == "Understood."
    assert strip_meta_commentary("I should not do that.") == ""
    assert strip_meta_commentary("Normal reply with no meta.") == "Normal reply with no meta."

def test_streaming_strips_meta_commentary():
    chunks = ["The user is asking: ", "how are you today?\n", "I don't experience days, ", "but I'm here."]
    filt = ThinkingFilter()
    output = []
    for c in chunks:
        out = filt.process_chunk(c)
        if out:
            output.append(out)
    rem = filt.flush()
    if rem:
        output.append(rem)
    result = "".join(output)
    assert not result.startswith("The user")
    assert result == "I don't experience days, but I'm here."

def test_ollama_adapter_payload_options_and_think(monkeypatch):
    captured_payload = {}

    class DummyResponse:
        status_code = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def aiter_lines(self):
            yield '{"message": {"content": "ok"}, "done": true}'

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def stream(self, method, url, json=None):
            captured_payload.update(json)
            return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    adapter = chat_module.OllamaAdapter(
        default_options={"temperature": 0.6, "top_p": 0.9},
        default_think=False
    )
    import asyncio
    asyncio.run(adapter.chat([{"role": "user", "content": "hi"}]))

    assert captured_payload["options"]["temperature"] == 0.6
    assert captured_payload["options"]["top_p"] == 0.9
    assert captured_payload["think"] is False


def test_persona_examples_no_overlap():
    import json
    import re
    settings = get_settings()
    persona_text = settings.persona_file.read_text(encoding="utf-8")

    # Extract all example owner situations from hinaku_persona.md
    example_situations = re.findall(r"^\s*Owner:\s*(.+)$", persona_text, flags=re.MULTILINE | re.IGNORECASE)
    assert len(example_situations) >= 4, "Expected at least 4 persona examples"

    # Load prompts from eval/golden.jsonl
    from backend.config import ROOT_DIR
    golden_path = ROOT_DIR / "eval" / "golden.jsonl"
    golden_prompts = []
    if golden_path.exists():
        for line in golden_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                golden_prompts.append(json.loads(line).get("prompt", ""))

    # Load prompts from scripts/model_bakeoff.py
    from scripts.model_bakeoff import PROMPTS as bakeoff_prompts

    eval_prompts = golden_prompts + bakeoff_prompts

    stop_words = {"a", "an", "the", "and", "or", "to", "in", "of", "for", "is", "my", "your", "on", "it", "what", "how", "i", "im"}

    for sit in example_situations:
        sit_clean = re.sub(r"[^\w\s]", "", sit).strip().lower()
        sit_words = {w for w in sit_clean.split() if w not in stop_words}

        for p in eval_prompts:
            p_clean = re.sub(r"[^\w\s]", "", p).strip().lower()
            # 1. Exact string match
            assert sit_clean != p_clean, f"Persona example '{sit}' matches eval prompt '{p}' exactly!"

            # 2. Substring match
            if len(sit_clean) > 8 and len(p_clean) > 8:
                assert sit_clean not in p_clean and p_clean not in sit_clean, (
                    f"Persona example '{sit}' overlaps eval prompt '{p}'!"
                )

            # 3. High keyword overlap (3 or more significant words in common)
            p_words = {w for w in p_clean.split() if w not in stop_words}
            overlap = sit_words.intersection(p_words)
            assert len(overlap) < 3, (
                f"Persona example '{sit}' shares too many keywords {overlap} with eval prompt '{p}'!"
            )



