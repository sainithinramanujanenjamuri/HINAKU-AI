import os
from pathlib import Path
from backend.models.ollama_shared import (
    get_shared_llm_settings,
    get_shared_embedding_settings,
    log_ollama_call
)
from scripts.train_smoke import check_export_tools

def test_shared_llm_settings():
    llm = get_shared_llm_settings()
    assert llm["model"] == "bonsai-2:9b"
    assert llm["keep_alive"] == "30m"
    assert llm["options"]["num_ctx"] in (4096, 8192)
    assert llm["options"]["temperature"] == 0.6
    assert llm["options"]["top_p"] == 0.9
    assert llm["options"]["num_predict"] == 300

def test_shared_embedding_settings():
    emb = get_shared_embedding_settings()
    assert emb["model"] == "qwen3-embedding:0.6b"
    assert emb["keep_alive"] == "5m"
    assert emb["options"]["num_ctx"] == 512

def test_log_ollama_call_format():
    line = log_ollama_call(
        call_type="test_call",
        model="gemma3:4b",
        num_ctx=4096,
        keep_alive="30m",
        options={"num_ctx": 4096},
        load_duration_ns=12_000_000,
        total_duration_ns=1_500_000_000
    )
    assert "[OLLAMA PROFILE]" in line
    assert "call=test_call" in line
    assert "model=gemma3:4b" in line
    assert "num_ctx=4096" in line
    assert "load_duration=0.0120s" in line
    assert "total_duration=1.5000s" in line

def test_check_export_tools_detection():
    tools_ok, missing = check_export_tools()
    assert isinstance(tools_ok, bool)
    assert isinstance(missing, list)
    if not tools_ok:
        names = [m["name"] for m in missing]
        assert any("gguf" in n.lower() for n in names)

