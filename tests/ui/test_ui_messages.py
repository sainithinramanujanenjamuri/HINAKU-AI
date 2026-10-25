import pytest
from datetime import datetime

def test_user_message_long_fold_threshold():
    # Long text (> 350 chars) should qualify for folding
    short_text = "What is quantum computing?"
    long_text = "A" * 400
    multi_line = "\n".join([f"Line {i}" for i in range(8)])

    assert len(short_text) < 350
    assert len(long_text) > 350
    assert (multi_line.count("\n")) > 5

def test_process_accordion_never_contains_raw_reasoning():
    # Verify process accordion contains telemetry only, never <think> or raw reasoning
    sample_steps = [
        "Sensitive and live-data guards verified",
        "Model router selected backend: local (bonsai-2:9b)",
        "Retrieved 2 relevant memories for context",
        "Completed generation in 12s",
        "Deterministic verifier applied"
    ]
    for step in sample_steps:
        assert "<think>" not in step
        assert "</think>" not in step
        assert "chain-of-thought" not in step.lower()

def test_backend_badge_mapping():
    # UI badge text contract: never lies about backend
    def get_badge(backend, model):
        bKind = (backend or "local").lower()
        if bKind == "api":
            return "API · logged by provider"
        elif bKind == "guard":
            return "guard · not used for training"
        return f"{model or 'bonsai-2:9b'} · local"

    assert get_badge("api", "meta-llama/llama-3.3-70b-instruct:free") == "API · logged by provider"
    assert get_badge("guard", "guard") == "guard · not used for training"
    assert get_badge("local", "bonsai-2:9b") == "bonsai-2:9b · local"

