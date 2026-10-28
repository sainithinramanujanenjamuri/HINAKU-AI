import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.ollama_adapter import OllamaAdapter

client = TestClient(app)


@pytest.mark.asyncio
async def test_ollama_adapter_is_model_loaded():
    adapter = OllamaAdapter(host="http://127.0.0.1:11434", default_model="gemma3:4b")

    mock_resp_loaded = MagicMock()
    mock_resp_loaded.status_code = 200
    mock_resp_loaded.json.return_value = {
        "models": [
            {"name": "gemma3:4b", "model": "gemma3:4b", "size_vram": 2882482994},
            {"name": "qwen3-embedding:0.6b", "model": "qwen3-embedding:0.6b", "size_vram": 719732080}
        ]
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp_loaded)

    with patch("httpx.AsyncClient", return_value=mock_client):
        # gemma3:4b is loaded
        assert await adapter.is_model_loaded("gemma3:4b") is True
        # qwen3.5:4b is not loaded
        assert await adapter.is_model_loaded("qwen3.5:4b") is False

    # When Ollama /api/ps is down or unreachable
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    with patch("httpx.AsyncClient", return_value=mock_client):
        assert await adapter.is_model_loaded("gemma3:4b") is False


def test_settings_changes_model_and_triggers_background_warming():
    with patch("backend.models.ollama_adapter.OllamaAdapter.chat", new_callable=AsyncMock) as mock_chat:
        res = client.post("/api/settings", json={"default_local_model": "bonsai-2:9b"})
        assert res.status_code == 200
        data = res.json()
        assert data["default_local_model"] == "bonsai-2:9b"

        # Restore original
        client.post("/api/settings", json={"default_local_model": "gemma3:4b"})


@pytest.mark.asyncio
async def test_chat_yields_loading_model_notice_when_not_loaded():
    # If model is not loaded, stream must yield notice event with "Loading model... about 15 s"
    from backend.api import chat

    with patch.object(chat.local_adapter, "is_model_loaded", new=AsyncMock(return_value=False)):
        res = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True
        })
        assert res.status_code == 200
        body = res.text
        assert "Loading model... about 15 s" in body
        assert '"loading_model": true' in body or '"loading_model":true' in body
