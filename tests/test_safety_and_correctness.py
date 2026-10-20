import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import get_settings
from backend.models.router import ModelRouter, is_personal_statement, classify_prompt
from tests.conftest import REAL_DB_PATH, INITIAL_DB_EXISTS, INITIAL_DB_HASH, get_file_hash

client = TestClient(app)

# ==============================================================================
# 1. Database Safety: Default to Temp unless HINAKU_USE_REAL_DATA=1
# ==============================================================================

def test_script_without_opt_in_uses_temp_dir():
    """
    Any external process or script without HINAKU_USE_REAL_DATA=1 must
    automatically resolve sqlite_path and chroma_path to tempfile.gettempdir().
    """
    code = """
import os, sys, tempfile
from pathlib import Path
# Ensure HINAKU_USE_REAL_DATA is NOT set
os.environ.pop("HINAKU_USE_REAL_DATA", None)
os.environ.pop("HINAKU_DB_PATH", None)
os.environ.pop("HINAKU_CHROMA_PATH", None)

from backend.config import get_settings
s = get_settings()

temp_dir = Path(tempfile.gettempdir()).resolve()
sqlite_resolved = s.sqlite_path.resolve()
chroma_resolved = s.chroma_path.resolve()

assert str(sqlite_resolved).startswith(str(temp_dir)), f"SQLite path {sqlite_resolved} not in {temp_dir}"
assert str(chroma_resolved).startswith(str(temp_dir)), f"Chroma path {chroma_resolved} not in {temp_dir}"

from backend.history import ChatHistoryManager
mgr = ChatHistoryManager(s.sqlite_path)
conv = mgr.create_conversation(title="Temp Script Chat")
mgr.add_message(conv["id"], "user", "Hello from safe script")

print("SAFE_SCRIPT_SUCCESS")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent)
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert "SAFE_SCRIPT_SUCCESS" in result.stdout

    # Verify real database data/hinaku.db was never touched
    assert REAL_DB_PATH.exists() == INITIAL_DB_EXISTS
    assert get_file_hash(REAL_DB_PATH) == INITIAL_DB_HASH

def test_opt_in_with_real_data_flag():
    """
    Explicit opt-in with HINAKU_USE_REAL_DATA=1 resolves to data/hinaku.db.
    """
    code = """
import os, sys
os.environ["HINAKU_USE_REAL_DATA"] = "1"
os.environ.pop("HINAKU_DB_PATH", None)
os.environ.pop("HINAKU_CHROMA_PATH", None)

from backend.config import get_settings
s = get_settings()

assert s.sqlite_path.name == "hinaku.db"
assert "data" in s.sqlite_path.parts
assert "chroma" in s.chroma_path.parts
print("REAL_OPT_IN_SUCCESS")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent)
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert "REAL_OPT_IN_SUCCESS" in result.stdout


# ==============================================================================
# 2. Private Chats: Never call API in any mode, from first message
# ==============================================================================

@pytest.mark.asyncio
async def test_private_chat_never_calls_api_even_in_api_only_mode():
    """
    Private chats must NEVER invoke the API adapter under ANY router mode,
    including 'api_only' mode and even for complex prompts.
    """
    mock_local = MagicMock()
    mock_local.default_model = "local-model"
    async def mock_local_stream(*args, **kwargs):
        yield "Local response to private chat"
    mock_local.stream_chat = mock_local_stream

    mock_api = MagicMock()
    mock_api.model = "api-model"
    mock_api.api_key = "dummy-key"
    async def forbidden_api_stream(*args, **kwargs):
        pytest.fail("API adapter was called during a Private chat!")
        yield "FORBIDDEN"
    mock_api.stream_chat = forbidden_api_stream

    router = ModelRouter(
        local_adapter=mock_local,
        api_adapter=mock_api,
        mode="api_only",
        fallback_on_failure=True
    )

    # 1. Routing decision check
    decision = router.decide_backend(
        user_prompt="Explain the detailed theory of general relativity in Python",
        is_private=True
    )
    assert decision.target_backend == "local"
    assert decision.fallback_allowed is False

    # 2. Streaming execution check
    chunks = []
    async for item in router.stream_chat(
        messages=[{"role": "user", "content": "Explain relativity"}],
        user_prompt="Explain relativity",
        is_private=True
    ):
        chunks.append(item["chunk"])

    assert "Local response to private chat" in "".join(chunks)

def test_private_chat_flag_set_on_creation_before_first_message(monkeypatch):
    """
    Verify creating a conversation with is_private=True sets it before any message is sent,
    and sending the first message via /api/chat preserves privacy.
    """
    import backend.api.chat as chat_module

    # Mock API adapter to explode if called
    mock_api = MagicMock()
    mock_api.model = "api-model"
    mock_api.api_key = "dummy-key"
    async def fail_api(*args, **kwargs):
        pytest.fail("API was called on private chat first message!")
        yield ""
    mock_api.stream_chat = fail_api
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)

    mock_local = MagicMock()
    mock_local.default_model = "local-model"
    async def safe_local(*args, **kwargs):
        yield "Safe local reply"
    mock_local.stream_chat = safe_local
    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)

    # 1. Create private conversation before sending message
    res_create = client.post("/api/conversations", json={
        "title": "Confidential Topic",
        "is_private": True
    })
    assert res_create.status_code == 200
    conv_data = res_create.json()
    assert conv_data["is_private"] is True
    cid = conv_data["id"]

    # 2. Send the first message (factual query that would normally trigger API)
    res_chat = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "What is the secret formula for rocket fuel?"}],
        "conversation_id": cid,
        "is_private": True,
        "stream": False
    })
    assert res_chat.status_code == 200
    resp_json = res_chat.json()
    assert resp_json["backend"] == "local"


# ==============================================================================
# 3. Personal Statements Stay Local
# ==============================================================================

def test_personal_statements_routing():
    """
    First-person statements about the owner ("I use...", "my favorite...", "I am...")
    must route to 'local' even in auto mode and even with keywords like python or code.
    """
    personal_samples = [
        "I use a laptop with an RTX 4050 and 6 GB VRAM",
        "My favorite editor is VS Code",
        "I am a backend developer working on Python APIs",
        "I prefer short direct answers without fluff",
        "Remember my card PIN is 1234",
        "I'm exhausted and nothing is working on my project",
        "I like writing clean code in Rust and Python",
        "My project is building an AI assistant named Hinaku",
        "I have 6 GB of VRAM",
        "Note that I work on Windows"
    ]

    for prompt in personal_samples:
        assert is_personal_statement(prompt) is True, f"Failed to identify as personal: {prompt}"
        decision = classify_prompt(prompt, is_private=False)
        assert decision == "local", f"Personal prompt routed to API: {prompt}"

def test_non_personal_statements_route_to_api():
    """
    General questions, code queries, or advice requests that are NOT first-person statements
    should route to 'api' (in auto mode).
    """
    api_samples = [
        "What is the capital of Australia?",
        "Explain how python generators work under the hood",
        "Compare PyTorch versus TensorFlow",
        "Write a function to calculate Fibonacci numbers in C++",
        "Why is the sky blue during sunset?"
    ]

    for prompt in api_samples:
        assert is_personal_statement(prompt) is False, f"Incorrectly marked personal: {prompt}"
        decision = classify_prompt(prompt, is_private=False)
        assert decision == "api", f"API prompt routed to local: {prompt}"


# ==============================================================================
# 4. End-to-End Tests through /api/chat Endpoint
# ==============================================================================

def test_e2e_normal_api_message(monkeypatch):
    import backend.api.chat as chat_module

    monkeypatch.setattr(chat_module.settings, "get_api_key", lambda: "test-api-key")

    api_called = False
    async def mock_api_stream(*args, **kwargs):
        nonlocal api_called
        api_called = True
        yield "Canberra is the capital of Australia."

    mock_api = MagicMock()
    mock_api.model = "gpt-4o"
    mock_api.api_key = "test-api-key"
    mock_api.stream_chat = mock_api_stream

    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "What is the capital of Australia?"}],
        "stream": False
    })
    assert res.status_code == 200
    data = res.json()
    assert data["backend"] == "api"
    assert "Canberra" in data["content"]
    assert api_called is True

def test_e2e_personal_statement_stays_local(monkeypatch):
    import backend.api.chat as chat_module

    local_called = False
    async def mock_local_stream(*args, **kwargs):
        nonlocal local_called
        local_called = True
        yield "Noted. VS Code is well configured."

    mock_local = MagicMock()
    mock_local.default_model = "qwen3.5:4b"
    mock_local.stream_chat = mock_local_stream

    mock_api = MagicMock()
    mock_api.model = "gpt-4o"
    mock_api.api_key = "test-key"
    async def fail_api(*args, **kwargs):
        pytest.fail("API was called for a personal statement!")
        yield ""
    mock_api.stream_chat = fail_api

    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "My favorite editor is VS Code for python"}],
        "stream": False
    })
    assert res.status_code == 200
    data = res.json()
    assert data["backend"] == "local"
    assert local_called is True

def test_e2e_memory_injection_and_persona_in_context(monkeypatch):
    """
    Verify that relevant memories are retrieved and injected into the system prompt
    sent to the model adapter during an /api/chat call.
    """
    import backend.api.chat as chat_module

    # Mock embedder to avoid needing live Ollama for embedding query
    dummy_vec = [1.0] + [0.0] * 1023
    monkeypatch.setattr(chat_module.memory_storage, "embed_query", lambda q: dummy_vec)
    monkeypatch.setattr(chat_module.memory_storage, "embed_documents", lambda texts: [dummy_vec for _ in texts])

    # Seed a memory
    chat_module.memory_storage.add_memory("Uses a laptop with an RTX 4050 and 6 GB VRAM")

    received_system_prompt = None
    async def capture_local_stream(messages, *args, **kwargs):
        nonlocal received_system_prompt
        for m in messages:
            if m["role"] == "system":
                received_system_prompt = m["content"]
        yield "Plan training for 6 GB VRAM."

    mock_local = MagicMock()
    mock_local.default_model = "qwen3.5:4b"
    mock_local.stream_chat = capture_local_stream

    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    # Ensure local routing for memory injection test
    monkeypatch.setattr(chat_module.model_router, "mode", "local_only")

    # Ask something related to the GPU memory
    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "Which GPU should I plan training around?"}],
        "stream": False
    })
    assert res.status_code == 200
    assert received_system_prompt is not None
    # Persona should be in system prompt
    assert "HINAKU" in received_system_prompt
    # Memory should be injected into system prompt
    assert "RTX 4050" in received_system_prompt or "6 GB VRAM" in received_system_prompt
