import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.models.router import ModelRouter

@pytest.mark.asyncio
async def test_error_event_not_persisted_to_db():
    """
    Test that when an error occurs during model streaming,
    the error event is returned as type 'error' and NOT saved
    to the messages or interactions tables.
    """
    from backend.api import chat
    transport = ASGITransport(app=app)
    
    # Mock stream_chat on model_router to yield an error event
    async def mock_error_stream(*args, **kwargs):
        yield {
            "type": "error",
            "error_type": "local_error",
            "chunk": "",
            "error": "Unable to connect to local Ollama service at http://localhost:11434. Is Ollama running?",
            "backend": "local",
            "model": "gemma3:4b",
            "notice": "Local model error"
        }

    with patch.object(chat.model_router, "stream_chat", side_effect=mock_error_stream):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "Hello HINAKU"}],
                    "stream": True
                }
            )
            assert res.status_code == 200
            content = res.text
            assert '"type": "error"' in content
            assert "Unable to connect" in content

    # Verify that NO assistant message was saved to database
    convs = chat.history_manager.list_conversations()
    if convs:
        for c in convs:
            full_c = chat.history_manager.get_conversation(c["id"])
            assistant_msgs = [m for m in full_c.get("messages", []) if m["role"] == "assistant"]
            assert len(assistant_msgs) == 0, f"Error was saved as an assistant message: {assistant_msgs}"

    # Verify interactions table has no error rows
    import sqlite3
    conn = sqlite3.connect(chat.history_manager.db_path)
    count = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    assert count == 0, "Error row was saved to interactions table"
    conn.close()

@pytest.mark.asyncio
async def test_ollama_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health/ollama")
        assert res.status_code == 200
        data = res.json()
        assert "online" in data
