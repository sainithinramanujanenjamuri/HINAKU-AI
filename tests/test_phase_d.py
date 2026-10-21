import pytest
import json
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_chat_returns_message_id_and_interaction_id():
    from backend.api.chat import history_manager
    # Test non-streaming chat returns message_id and interaction_id
    with patch("backend.models.ollama_adapter.OllamaAdapter.stream_chat") as mock_stream:
        async def fake_stream(*args, **kwargs):
            yield "Hello, I am testing feedback."
        mock_stream.side_effect = fake_stream

        resp = client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Hello test message"}],
            "stream": False
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "message_id" in data and data["message_id"] is not None
        assert "interaction_id" in data and data["interaction_id"] is not None
        msg_id = data["message_id"]
        inter_id = data["interaction_id"]

        # Check DB
        inter = history_manager.get_interaction(inter_id)
        assert inter is not None
        assert inter["message_id"] == msg_id
        assert inter["answer"] == "Hello, I am testing feedback."

def test_message_feedback_submission():
    from backend.api.chat import history_manager
    # Create conversation and assistant message
    conv = history_manager.create_conversation("Feedback Test")
    conv_id = conv["id"]
    u_msg = history_manager.add_message(conv_id, "user", "What is 2+2?")
    a_msg = history_manager.add_message(conv_id, "assistant", "It is 4.", model="test", backend="local")
    msg_id = a_msg["id"]
    inter_id = history_manager.log_interaction(
        conv_id=conv_id,
        user_prompt="What is 2+2?",
        answer="It is 4.",
        model="test",
        backend="local",
        message_id=msg_id
    )

    # 1. Thumbs up
    resp = client.post(f"/api/messages/{msg_id}/feedback", json={"feedback": "thumbs_up"})
    assert resp.status_code == 200
    inter = history_manager.get_interaction(inter_id)
    assert inter["feedback"] == "thumbs_up"

    # 2. Thumbs down
    resp = client.post(f"/api/messages/{msg_id}/feedback", json={"feedback": "thumbs_down"})
    assert resp.status_code == 200
    inter = history_manager.get_interaction(inter_id)
    assert inter["feedback"] == "thumbs_down"

    # 3. Clear feedback
    resp = client.post(f"/api/messages/{msg_id}/feedback", json={"feedback": None})
    assert resp.status_code == 200
    inter = history_manager.get_interaction(inter_id)
    assert inter["feedback"] is None

    # 4. Invalid feedback value
    resp = client.post(f"/api/messages/{msg_id}/feedback", json={"feedback": "invalid_vote"})
    assert resp.status_code == 400

    # 5. Non-existent message
    resp = client.post("/api/messages/non-existent-id/feedback", json={"feedback": "thumbs_up"})
    assert resp.status_code == 404

def test_message_edit_reply():
    from backend.api.chat import history_manager
    conv = history_manager.create_conversation("Edit Reply Test")
    conv_id = conv["id"]
    history_manager.add_message(conv_id, "user", "Explain gravity.")
    a_msg = history_manager.add_message(conv_id, "assistant", "Things fall down.", model="test", backend="local")
    msg_id = a_msg["id"]
    inter_id = history_manager.log_interaction(
        conv_id=conv_id,
        user_prompt="Explain gravity.",
        answer="Things fall down.",
        model="test",
        backend="local",
        message_id=msg_id
    )

    # Edit the answer
    new_text = "Gravity is the curvature of spacetime caused by mass and energy."
    resp = client.post(f"/api/messages/{msg_id}/edit", json={"edited_answer": new_text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["edited_answer"] == new_text

    # Verify message in DB was updated
    msg = history_manager.get_message(msg_id)
    assert msg["content"] == new_text

    # Verify interaction has edited_answer
    inter = history_manager.get_interaction(inter_id)
    assert inter["edited_answer"] == new_text

    # Verify conversation endpoint returns updated message with interaction info
    conv_resp = client.get(f"/api/conversations/{conv_id}")
    assert conv_resp.status_code == 200
    conv_data = conv_resp.json()
    ast_in_conv = [m for m in conv_data["messages"] if m["id"] == msg_id][0]
    assert ast_in_conv["content"] == new_text
    assert ast_in_conv["edited_answer"] == new_text

    # Empty edit text validation
    resp_empty = client.post(f"/api/messages/{msg_id}/edit", json={"edited_answer": "   "})
    assert resp_empty.status_code == 400

def test_guard_replies_tagged_as_guard_backend():
    from backend.api.chat import history_manager
    # Sensitive guard
    resp = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "My password is SecretPassword123!"}],
        "stream": False
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "guard"
    msg_id = data.get("message_id")
    assert msg_id is not None

    inter = history_manager.get_interaction_by_message_id(msg_id)
    assert inter is not None
    assert inter["backend"] == "guard"

    # Live guard
    resp_live = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "what is the current price of bitcoin?"}],
        "stream": False
    })
    assert resp_live.status_code == 200
    data_live = resp_live.json()
    assert data_live["backend"] == "guard"
    msg_id_live = data_live.get("message_id")
    assert msg_id_live is not None

    inter_live = history_manager.get_interaction_by_message_id(msg_id_live)
    assert inter_live is not None
    assert inter_live["backend"] == "guard"

def test_direct_interaction_feedback_endpoint():
    from backend.api.chat import history_manager
    conv = history_manager.create_conversation("Direct Interaction Test")
    conv_id = conv["id"]
    inter_id = history_manager.log_interaction(
        conv_id=conv_id,
        user_prompt="Say hi",
        answer="Hi there.",
        model="test",
        backend="local"
    )

    resp = client.post(f"/api/interactions/{inter_id}/feedback", json={"feedback": "thumbs_up"})
    assert resp.status_code == 200
    inter = history_manager.get_interaction(inter_id)
    assert inter["feedback"] == "thumbs_up"

    # Non-existent interaction
    resp_404 = client.post("/api/interactions/fake-id/feedback", json={"feedback": "thumbs_up"})
    assert resp_404.status_code == 404
