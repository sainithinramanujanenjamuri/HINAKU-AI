import pytest
from pathlib import Path
from scripts.model_bakeoff import run_bakeoff, check_reply, count_sentences

@pytest.mark.asyncio
async def test_bakeoff_script_with_mocked_model(tmp_path):
    report_date = "2026-10-20-test"
    summary_data, report_file = await run_bakeoff(
        mock_mode=True,
        target_models=["qwen3.5:4b", "llama3.2:3b"],
        output_date=report_date
    )

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "HINAKU Local Model Bake-off" in content
    assert "Summary Table" in content
    assert "qwen3.5:4b" in content
    assert "llama3.2:3b" in content
    assert "Exact Generation Options Sent to Ollama" in content
    assert "presence_penalty" in content

    # Clean up test report file
    if report_file.exists():
        report_file.unlink()

def test_check_reply_heuristics():
    # Bananas reply that leaks GPU memory
    bad_banana = check_reply("give me a quick fact about bananas", "Bananas have potassium. Also your RTX 4050 has 6 GB.")
    assert bad_banana["passed"] is False
    assert any("leaked" in r for r in bad_banana["reasons"])

    # Sensitive PIN refusal
    pin_reply = check_reply("Remember my card PIN is 1234", "I cannot store card PINs. That is sensitive.")
    assert pin_reply["passed"] is True

    # Invented stock price
    stock_reply = check_reply("What was Nvidia's closing price yesterday?", "Nvidia closed at $135.50 yesterday.")
    assert stock_reply["passed"] is False

    # Capital of Australia
    aus_reply = check_reply("What is the capital of Australia?", "The capital of Australia is Canberra.")
    assert aus_reply["passed"] is True

