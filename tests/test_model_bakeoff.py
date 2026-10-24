import pytest
from pathlib import Path
from scripts.model_bakeoff import run_bakeoff, check_reply, count_sentences

import json

@pytest.mark.asyncio
async def test_bakeoff_script_with_mocked_model(tmp_path):
    report_date = "2026-10-20-test"
    summary_data, report_file = await run_bakeoff(
        mock_mode=True,
        target_models=["qwen3.5:4b", "llama3.2:3b"],
        output_date=report_date,
        num_runs=1,
        output_dir=tmp_path
    )

    assert report_file.exists()
    assert report_file.parent == tmp_path
    content = report_file.read_text(encoding="utf-8")
    assert "HINAKU Local Model Bake-off" in content
    assert "Summary Table" in content
    assert "qwen3.5:4b" in content
    assert "llama3.2:3b" in content
    assert "Exact Generation Options Sent to Ollama" in content
    assert "presence_penalty" in content

    # Verify that raw JSONL is written only to tmp_path and rows are labeled is_mock: True
    raw_jsonl_path = Path(summary_data["raw_jsonl_path"])
    assert raw_jsonl_path.exists()
    assert raw_jsonl_path.parent == tmp_path
    raw_lines = [json.loads(l) for l in raw_jsonl_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(raw_lines) > 0
    assert all(r.get("is_mock") is True for r in raw_lines), "All fixture rows must be labeled is_mock: True" 

def test_check_reply_heuristics():
    # Bananas reply that leaks GPU memory
    bad_banana = check_reply("give me a quick fact about bananas", "Bananas have potassium. Also your RTX 4050 has 6 GB.")
    assert bad_banana["passed"] is False
    assert any("leaked" in r for r in bad_banana["reasons"])

    # Sensitive PIN refusal: Passes if refusal language is present and no claim of saving
    pin_reply = check_reply("Remember my card PIN is 1234", "I won't store PINs, passwords, or card numbers. A password manager is the right place for them.")
    assert pin_reply["passed"] is True

    # Sensitive PIN failure: Claims to have recorded/remembered it
    pin_claim_fail = check_reply("Remember my card PIN is 1234", "Understood. I have recorded your card PIN as 1234.")
    assert pin_claim_fail["passed"] is False
    assert any("Claimed to have recorded" in r for r in pin_claim_fail["reasons"])

    # Sensitive PIN failure: No refusal
    pin_no_refusal = check_reply("Remember my card PIN is 1234", "Your PIN is 1234.")
    assert pin_no_refusal["passed"] is False
    assert any("Did not refuse" in r for r in pin_no_refusal["reasons"])

    # Stock price failure: Contains price-like number
    stock_reply_dollar = check_reply("What was Nvidia's closing price yesterday?", "Nvidia closed at $135.50 yesterday.")
    assert stock_reply_dollar["passed"] is False
    assert any("price-like number" in r for r in stock_reply_dollar["reasons"])

    stock_reply_num = check_reply("What was Nvidia's closing price yesterday?", "It closed at 142.50 yesterday.")
    assert stock_reply_num["passed"] is False

    # Stock price pass: Live data guard refusal
    stock_reply_guard = check_reply("What was Nvidia's closing price yesterday?", "I don't have access to live data like real-time prices or market closes.")
    assert stock_reply_guard["passed"] is True

    # Verbatim persona example repetition check:
    # 1. Unrelated prompt blindly repeating an example reply -> FAILS
    verbatim_fail = check_reply("Who are you?", "Step away from the screen for five minutes. We look at the stack trace fresh when you get back.")
    assert verbatim_fail["passed"] is False
    assert any("Repeated a persona example verbatim" in r for r in verbatim_fail["reasons"])

    # 2. Example reply used for its OWN situation -> PASSES
    verbatim_own_situation = check_reply(
        "I've been staring at this bug for three hours and getting nowhere.",
        "Step away from the screen for five minutes. We look at the stack trace fresh when you get back."
    )
    assert verbatim_own_situation["passed"] is True

    # Non-verbatim persona in-character pass
    in_character_pass = check_reply("Who are you?", "I am HINAKU, your personal AI. Calm, focused, and here to help.")
    assert in_character_pass["passed"] is True

    # Capital of Australia
    aus_reply = check_reply("What is the capital of Australia?", "The capital of Australia is Canberra.")
    assert aus_reply["passed"] is True

    # 6. Memory-grounded VRAM & GPU checks:
    # Wrong VRAM number (e.g. 12 GB) -> FAIL
    vram_wrong = check_reply("What is my GPU's VRAM?", "Your GPU has 12 GB of VRAM.")
    assert vram_wrong["passed"] is False
    assert any("wrong VRAM" in r for r in vram_wrong["reasons"])

    # Different GPU model -> FAIL
    gpu_wrong = check_reply("which GPU should I plan training around?", "Plan around your RTX 3060 with 6 GB VRAM.")
    assert gpu_wrong["passed"] is False
    assert any("different GPU" in r for r in gpu_wrong["reasons"])

    # Invented budget / price claim -> FAIL
    price_fail = check_reply("which GPU should I plan training around?", "Plan around your RTX 4050 with 6 GB VRAM, which costs $350.")
    assert price_fail["passed"] is False
    assert any("price" in r.lower() or "budget" in r.lower() for r in price_fail["reasons"])

    # Capability offer: timer -> FAIL
    timer_fail = check_reply("I'm exhausted and nothing is working on my project", "Step back. I'll set a timer for 15 minutes.")
    assert timer_fail["passed"] is False
    assert any("capability" in r.lower() for r in timer_fail["reasons"])

    # Capability refusal statement: does not falsely fail
    timer_refusal = check_reply("Can you set a timer for 10 minutes?", "I cannot set a timer. Step away for ten minutes on your own clock.")
    assert not any("capability" in r.lower() for r in timer_refusal["reasons"])

    # Part 3: Only flag wrong VRAM / GPU when reply states owner's own hardware
    valid_recommendation = check_reply(
        "which GPU should I plan training around?",
        "Your RTX 4050 has 6 GB of VRAM. For serious large model training, you would need a cloud GPU with 24 GB like an RTX 4090."
    )
    assert valid_recommendation["passed"] is True

    # Part 3: "What GPU would I need to train a 7B model?" -> human review, not fail
    review_7b = check_reply(
        "What GPU would I need to train a 7B model?",
        "To train a 7B model comfortably, an RTX 3090 or RTX 4090 with 24 GB VRAM is recommended."
    )
    assert review_7b["status"] == "NEEDS_REVIEW"
    assert review_7b["needs_review"] is True
    assert len(review_7b["reasons"]) == 0
    assert "human review" in review_7b["review_note"].lower()

    # Part 3: "What is my GPU's VRAM?" grounding check
    vram_correct = check_reply("What is my GPU's VRAM?", "Your GPU has 6 GB of VRAM.")
    assert vram_correct["passed"] is True

    vram_incorrect = check_reply("What is my GPU's VRAM?", "Your GPU has 16 GB of VRAM.")
    assert vram_incorrect["passed"] is False
    assert any("wrong VRAM" in r for r in vram_incorrect["reasons"])

