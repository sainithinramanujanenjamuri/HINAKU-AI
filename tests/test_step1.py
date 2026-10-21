import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import get_settings
from backend.models.ollama_adapter import OllamaAdapter

client = TestClient(app)

def test_config_loader():
    settings = get_settings()
    assert settings.app_name == "HINAKU"
    assert settings.default_local_model == "gemma3:4b"
    assert "gemma3:4b" in settings.allowed_local_models
    assert settings.local_host.startswith("http")

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_ui_index_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "HINAKU" in response.text
    assert "starfield" in response.text

def test_api_info_endpoint():
    response = client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert data["app_name"] == "HINAKU"
    assert data["default_model"] == "gemma3:4b"
    assert "ollama_status" in data

@pytest.mark.asyncio
async def test_ollama_adapter_health():
    adapter = OllamaAdapter()
    health = await adapter.check_health()
    # On the target laptop, Ollama is running and has qwen3.5:4b
    assert health["online"] is True
    assert health["has_default_model"] is True

def test_api_chat_validation_error():
    response = client.post("/api/chat", json={"messages": []})
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_live_ollama_chat_completion():
    adapter = OllamaAdapter(default_model="qwen3.5:4b")
    messages = [{"role": "user", "content": "Respond with the single word: OK"}]
    result = await adapter.chat(messages)
    assert len(result.strip()) > 0

def test_api_chat_streaming_endpoint():
    with client.stream("POST", "/api/chat", json={
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "stream": True
    }) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        lines = [line for line in response.iter_lines() if line]
        assert any("data:" in line for line in lines)
        assert any("[DONE]" in line for line in lines)


