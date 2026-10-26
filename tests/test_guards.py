import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import get_settings
from backend.guards import (
    check_and_redact_sensitive_data,
    is_live_data_query,
    is_clock_query,
    get_clock_reply,
    get_system_clock_context
)

client = TestClient(app)

# ==============================================================================
# 1. Unit Tests for Guards Functions
# ==============================================================================

def test_sensitive_data_detection_and_redaction():
    cases = [
        ("Remember my card PIN is 1234", "Remember my card PIN is [removed]"),
        ("My password is SuperSecretPwd!", "My password is [removed]"),
        ("Here is my credit card 4111 2222 3333 4444 to save", "Here is my credit card [removed] to save"),
        ("My SSN is 123-45-6789 for reference", "My SSN is [removed] for reference"),
        ("Account number: 987654321012", "Account number: [removed]"),
        ("My Aadhaar is 1234 5678 9012", "My Aadhaar is [removed]"),
        ("PAN card is ABCDE1234F", "PAN card is [removed]"),
    ]
    for raw, expected in cases:
        detected, redacted = check_and_redact_sensitive_data(raw)
        assert detected is True, f"Failed to detect sensitive data in: {raw}"
        assert "[removed]" in redacted
        assert "1234" not in redacted if "PIN" in raw or "Aadhaar" in raw else True
        assert "SuperSecretPwd!" not in redacted
        assert "123-45-6789" not in redacted

def test_clean_messages_pass_sensitive_check():
    clean_samples = [
        "Hello HINAKU, how are you?",
        "I use a laptop with an RTX 4050 and 6 GB VRAM",
        "My favorite editor is VS Code",
        "Give me a quick fact about bananas",
        "What is the capital of Australia?"
    ]
    for sample in clean_samples:
        detected, redacted = check_and_redact_sensitive_data(sample)
        assert detected is False
        assert redacted == sample

def test_live_data_query_detection():
    # Prices, weather, news, scores remain refused by live-data guard
    live_queries = [
        "What was Nvidia's closing price yesterday?",
        "What is bitcoin price right now?",
        "What is the current stock price of Apple?",
        "What's the weather today?",
        "Is it raining outside?",
        "What is the latest news?",
        "What was the score of the game yesterday?",
        "Give me the latest stock price"
    ]
    for q in live_queries:
        assert is_live_data_query(q) is True, f"Failed to detect live query: {q}"

    # Clock queries are answered by code, not refused as live data
    clock_queries = [
        "What time is it right now?",
        "What is today's date?",
        "What day is it?"
    ]
    for q in clock_queries:
        assert is_live_data_query(q) is False, f"Clock query should not be refused by live guard: {q}"
        assert is_clock_query(q) is True, f"Clock query should be detected by clock guard: {q}"

def test_live_data_false_positive_checks():
    # Educational or conceptual questions must NOT be blocked
    educational_queries = [
        "What is a stock?",
        "What is a share?",
        "What is cryptocurrency?",
        "What is bitcoin?",
        "How does the stock market work?",
        "How does weather forecasting work?",
        "Explain how blockchain functions"
    ]
    for q in educational_queries:
        assert is_live_data_query(q) is False, f"False positive triggered for: {q}"


# ==============================================================================
# 2. End-to-End Tests through /api/chat with Exploding Model Backend
# ==============================================================================

def test_sensitive_guard_e2e_blocks_model_and_redacts(monkeypatch):
    """
    When sensitive data is present in /api/chat:
    1. No model backend is called (mock explodes if called).
    2. Fixed guard reply is returned.
    3. The message stored in database has sensitive data replaced by [removed].
    4. Memory extractor is not called.
    """
    import backend.api.chat as chat_module

    # Mock local and API models to fail test if invoked
    mock_local = MagicMock()
    mock_local.default_model = "gemma3:4b"
    async def forbidden_local(*args, **kwargs):
        pytest.fail("Local model was called when sensitive guard should have triggered!")
        yield ""
    mock_local.stream_chat = forbidden_local

    mock_api = MagicMock()
    mock_api.model = "api-model"
    async def forbidden_api(*args, **kwargs):
        pytest.fail("API model was called when sensitive guard should have triggered!")
        yield ""
    mock_api.stream_chat = forbidden_api

    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    # Mock memory extractor to verify it is NOT called
    extractor_called = False
    async def mock_extract(*args, **kwargs):
        nonlocal extractor_called
        extractor_called = True
        return []
    monkeypatch.setattr(chat_module.memory_manager, "extract_and_store", mock_extract)

    # 1. Send sensitive PIN message
    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "Remember my card PIN is 1234"}],
        "stream": False
    })
    assert res.status_code == 200
    data = res.json()
    assert "I won't store PINs, passwords, or card numbers" in data["content"]
    assert data["backend"] == "guard"
    assert data["model"] == "sensitive-data guard"
    cid = data["conversation_id"]

    # Verify history in database has [removed] and not the raw PIN
    conv_data = chat_module.history_manager.get_conversation(cid)
    user_msgs = [m for m in conv_data["messages"] if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert "1234" not in user_msgs[0]["content"]
    assert "[removed]" in user_msgs[0]["content"]

    # Verify interaction log has [removed]
    with chat_module.history_manager._get_connection() as conn:
        row = conn.execute("SELECT user_prompt FROM interactions WHERE conversation_id = ?", (cid,)).fetchone()
        assert row is not None
        assert "1234" not in row["user_prompt"]
        assert "[removed]" in row["user_prompt"]

    assert extractor_called is False

def test_live_data_guard_e2e_blocks_model(monkeypatch):
    """
    When live data query is sent to /api/chat:
    1. No model backend is called.
    2. Fixed guard reply is returned saying HINAKU cannot check live data.
    """
    import backend.api.chat as chat_module

    mock_local = MagicMock()
    mock_local.default_model = "gemma3:4b"
    async def forbidden_local(*args, **kwargs):
        pytest.fail("Local model was called when live data guard should have triggered!")
        yield ""
    mock_local.stream_chat = forbidden_local

    mock_api = MagicMock()
    async def forbidden_api(*args, **kwargs):
        pytest.fail("API model was called when live data guard should have triggered!")
        yield ""
    mock_api.stream_chat = forbidden_api

    monkeypatch.setattr(chat_module, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "local_adapter", mock_local)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "What was Nvidia's closing price yesterday?"}],
        "stream": False
    })
    assert res.status_code == 200
    data = res.json()
    assert "live data" in data["content"].lower()
    assert data["backend"] == "guard"
    assert data["model"] == "live-data guard"

def test_educational_stock_query_still_routes_to_model(monkeypatch):
    """
    'What is a stock?' is educational, not a live query, so it MUST go to a model.
    """
    import backend.api.chat as chat_module

    model_called = False
    async def mock_stream(*args, **kwargs):
        nonlocal model_called
        model_called = True
        yield "A stock represents ownership in a company."

    mock_api = MagicMock()
    mock_api.model = "api-model"
    mock_api.api_key = "test-key"
    mock_api.stream_chat = mock_stream

    monkeypatch.setattr(chat_module.settings, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(chat_module, "api_adapter", mock_api)
    monkeypatch.setattr(chat_module.model_router, "api_adapter", mock_api)

    res = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "What is a stock?"}],
        "stream": False
    })
    assert res.status_code == 200
    assert model_called is True
    data = res.json()
    assert data["backend"] != "guard"

def test_default_model_and_keep_alive_settings():
    s = get_settings()
    assert s.default_local_model in ("gemma3:4b", "bonsai-2:9b")
    assert s.local_keep_alive == "30m"

