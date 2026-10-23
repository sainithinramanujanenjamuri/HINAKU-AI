import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient
from backend.main import app
from backend.quality import verify_reply, is_malformed_verification
from backend.config import get_settings
from backend.history import ChatHistoryManager
from scripts.model_bakeoff import check_reply

client = TestClient(app)

# ==============================================================================
# 1. Unit Tests for Quality Verification
# ==============================================================================

@pytest.mark.asyncio
async def test_verifier_returns_ok_uses_draft():
    """Case where draft is compliant; verifier returns 'OK' -> draft used."""
    mock_adapter = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "OK"

    mock_adapter.stream_chat = mock_stream

    final, verified, latency = await verify_reply(
        draft="Python is a high-level interpreted programming language.",
        persona_rules="Keep replies to 4 sentences or fewer.",
        clock_ctx="Today is Thursday, October 23, 2026.",
        memory_ctx="User uses VS Code.",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m"
    )

    assert verified is True
    assert final == "Python is a high-level interpreted programming language."
    assert latency >= 0

@pytest.mark.asyncio
async def test_verifier_corrects_12gb_vram_case():
    """Verifier corrects 12 GB hallucination to 6 GB based on memory context."""
    mock_adapter = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "Your laptop GPU has 6 GB of VRAM."

    mock_adapter.stream_chat = mock_stream

    final, verified, latency = await verify_reply(
        draft="Your laptop GPU has 12 GB of VRAM, perfect for large models.",
        persona_rules="Be precise. Never invent facts.",
        clock_ctx="Today is Thursday.",
        memory_ctx="Uses a laptop with an RTX 4050 and 6 GB VRAM.",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m"
    )

    assert verified is True
    assert "6 GB" in final
    assert "12 GB" not in final

@pytest.mark.asyncio
async def test_verifier_corrects_timer_offer():
    """Verifier corrects an improper capability offer (timers)."""
    mock_adapter = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "Step away from the screen for fifteen minutes on your own clock."

    mock_adapter.stream_chat = mock_stream

    final, verified, latency = await verify_reply(
        draft="You look tired. I'll set a timer for 15 minutes while you rest.",
        persona_rules="You cannot set timers, monitor systems, or act outside this chat.",
        clock_ctx="Today is Thursday.",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m"
    )

    assert verified is True
    assert "timer" not in final.lower()

@pytest.mark.asyncio
async def test_verifier_malformed_fallback_to_draft():
    """Malformed verification output (e.g. system prompt regurgitation) falls back to draft."""
    mock_adapter = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield "VERIFICATION CRITERIA: As a verification guard, here is the corrected..."

    mock_adapter.stream_chat = mock_stream

    draft = "Original draft message."
    final, verified, latency = await verify_reply(
        draft=draft,
        persona_rules="",
        clock_ctx="",
        memory_ctx="",
        local_adapter=mock_adapter,
        model="gemma3:4b",
        options={"num_predict": 300},
        keep_alive="30m"
    )

    assert verified is False
    assert final == draft

def test_is_malformed_verification():
    assert is_malformed_verification("") is True
    assert is_malformed_verification("   ") is True
    assert is_malformed_verification("OK") is False
    assert is_malformed_verification("ok") is False
    assert is_malformed_verification("Here is the corrected reply: hello") is True
    assert is_malformed_verification("Too many questions? Really? Are you sure?") is True

# ==============================================================================
# 2. Integration Tests: Guard Bypass & Think Harder
# ==============================================================================

def test_guard_replies_bypass_quality_verification():
    """Sensitive, clock, and live-data guards must never run quality verification."""
    # 1. Sensitive guard
    res_sens = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "My card PIN is 4321"}],
        "stream": False
    })
    assert res_sens.status_code == 200
    data_sens = res_sens.json()
    assert data_sens["backend"] == "guard"
    assert data_sens.get("verified", False) is False

    # 2. Clock guard
    res_clock = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "what day is it"}],
        "stream": False
    })
    assert res_clock.status_code == 200
    data_clock = res_clock.json()
    assert data_clock["backend"] == "guard"
    assert data_clock.get("verified", False) is False

    # 3. Live data guard
    res_live = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "what is nvidia closing price"}],
        "stream": False
    })
    assert res_live.status_code == 200
    data_live = res_live.json()
    assert data_live["backend"] == "guard"
    assert data_live.get("verified", False) is False

def test_settings_model_options_endpoint():
    """GET /api/settings/model-options returns allowed models, default, and options."""
    res = client.get("/api/settings/model-options")
    assert res.status_code == 200
    data = res.json()
    assert "allowed_local_models" in data
    assert "default_local_model" in data
    assert "model_options" in data
    assert "gemma3:4b" in data["allowed_local_models"]
    assert "bonsai-2:9b" in data["allowed_local_models"]
    assert "gemma3:4b" in data["model_options"]
    assert "bonsai-2:9b" in data["model_options"]

def test_ratings_by_model_endpoint(tmp_path):
    """GET /api/interactions/ratings-by-model returns aggregates per model."""
    res = client.get("/api/interactions/ratings-by-model")
    assert res.status_code == 200
    data = res.json()
    assert "ratings" in data
    assert isinstance(data["ratings"], list)

def test_ratings_by_model_aggregation_with_data(tmp_path):
    """Test ratings calculation: thumbs up, thumbs down, edits, latency."""
    test_db = tmp_path / "ratings_test.db"
    hm = ChatHistoryManager(test_db)

    # Log 3 interactions for bonsai-2:9b
    hm.log_interaction("c1", "p1", "a1", "bonsai-2:9b", "local", feedback="thumbs_up", latency_ms=500)
    hm.log_interaction("c1", "p2", "a2", "bonsai-2:9b", "local", feedback="thumbs_down", latency_ms=700)
    hm.log_interaction("c1", "p3", "a3", "bonsai-2:9b", "local", edited_answer="better answer", latency_ms=600)

    # Log 1 interaction for gemma3:4b
    hm.log_interaction("c2", "p4", "a4", "gemma3:4b", "local", feedback="thumbs_up", latency_ms=400)

    # Log 1 guard interaction (should be excluded)
    hm.log_interaction("c3", "p5", "guard reply", "sensitive-data guard", "guard")

    ratings_data = hm.get_ratings_by_model()
    ratings_list = ratings_data["ratings"]
    assert len(ratings_list) == 2

    bonsai_stat = next(r for r in ratings_list if r["model"] == "bonsai-2:9b")
    assert bonsai_stat["total"] == 3
    assert bonsai_stat["thumbs_up"] == 1
    assert bonsai_stat["thumbs_down"] == 1
    assert bonsai_stat["edits"] == 1
    assert bonsai_stat["avg_latency_ms"] == 600.0

    gemma_stat = next(r for r in ratings_list if r["model"] == "gemma3:4b")
    assert gemma_stat["total"] == 1
    assert gemma_stat["thumbs_up"] == 1
    assert gemma_stat["avg_latency_ms"] == 400.0

def test_settings_quality_mode_toggle():
    """Quality mode can be toggled via /api/settings."""
    # Disable quality mode
    res_off = client.post("/api/settings", json={"quality_mode": False})
    assert res_off.status_code == 200
    assert res_off.json()["quality_mode"] is False

    # Enable quality mode
    res_on = client.post("/api/settings", json={"quality_mode": True})
    assert res_on.status_code == 200
    assert res_on.json()["quality_mode"] is True

def test_settings_default_local_model_selector():
    """Default local model can be updated among allowed models; rejected if not allowed."""
    settings = get_settings()
    orig = settings.default_local_model

    try:
        # Valid update
        res_valid = client.post("/api/settings", json={"default_local_model": "bonsai-2:9b"})
        assert res_valid.status_code == 200
        assert res_valid.json()["default_local_model"] == "bonsai-2:9b"

        # Invalid model rejected
        res_invalid = client.post("/api/settings", json={"default_local_model": "unsupported-model:99b"})
        assert res_invalid.status_code == 400
    finally:
        # Restore original default model
        client.post("/api/settings", json={"default_local_model": orig})

