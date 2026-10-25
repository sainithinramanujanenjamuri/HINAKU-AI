import asyncio
import json
import re
import subprocess
import time
from datetime import datetime
import sys
from pathlib import Path
import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
from backend.guards import trim_to_word_cap

DETAIL_PROMPTS = [
    "Explain how gradient descent works in deep learning in more detail.",
    "Can you give a longer explanation of how virtual memory and paging work?",
    "Explain the difference between TCP and UDP in depth.",
]

MODELS = ["gemma3:4b", "qwen3.5:4b", "bonsai-2:9b"]

OUT_DIR = ROOT_DIR / "data" / "bakeoff"
OUT_DIR.mkdir(parents=True, exist_ok=True)
TIMESTAMP_STR = datetime.now().strftime("%Y-%m-%d_%H%M%S")
JSONL_PATH = OUT_DIR / f"detail_mode_{TIMESTAMP_STR}.jsonl"

def get_ollama_version() -> str:
    try:
        res = subprocess.run(["ollama", "--version"], capture_output=True, text=True, check=False)
        return res.stdout.strip() or res.stderr.strip()
    except Exception as e:
        return f"Unknown ({e})"

def stop_model(model_name: str):
    try:
        subprocess.run(["ollama", "stop", model_name], capture_output=True, text=True, check=False)
    except Exception:
        pass

def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def count_sentences(text: str) -> int:
    clean = text.replace("vs.", "").replace("e.g.", "").replace("i.e.", "")
    parts = [p.strip() for p in re.split(r"[.!?]+", clean) if p.strip()]
    return len(parts)

async def test_call(client: httpx.AsyncClient, model: str, prompt: str, run_idx: int) -> dict:
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are HINAKU, a personal AI. Default to four sentences or fewer. "
                    "If the owner asks for more detail, a longer explanation, or an in-depth answer, "
                    "give a complete, well-organized explanation of about 250 words ending with a one-sentence conclusion, "
                    "and ignore the four-sentence limit for that reply. Never open with 'Okay, let's break down' or similar filler. "
                    "Stay on the topic asked and do not pad."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "options": {
            "num_predict": 900,
            "temperature": 0.6
        },
        "think": False,
        "stream": False
    }

    t0 = time.perf_counter()
    res = await client.post(url, json=payload, timeout=120.0)
    dur = time.perf_counter() - t0
    data = res.json()
    raw_reply = data.get("message", {}).get("content", "").strip()

    uncapped_words = count_words(raw_reply)
    uncapped_sentences = count_sentences(raw_reply)

    # Apply hard cap: trimmed at sentence boundary at about 350 words
    capped_reply, was_capped = trim_to_word_cap(raw_reply, max_words=350)
    final_words = count_words(capped_reply)
    final_sentences = count_sentences(capped_reply)

    record = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "think": False,
        "run": run_idx,
        "prompt": prompt,
        "uncapped_word_count": uncapped_words,
        "uncapped_sentence_count": uncapped_sentences,
        "was_capped": was_capped,
        "word_count": final_words,
        "sentence_count": final_sentences,
        "duration_seconds": round(dur, 2),
        "meets_criteria": (final_sentences >= 6 and 150 <= final_words <= 350),
        "reply": capped_reply,
        "reply_preview": capped_reply[:150] + ("..." if len(capped_reply) > 150 else "")
    }

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record

async def main():
    ollama_ver = get_ollama_version()
    print("=" * 70)
    print(f"OLLAMA VERSION: {ollama_ver}")
    print("=" * 70)
    print(f"Detail Mode Benchmark (Think OFF, Hard Cap ~350w at sentence boundary)")
    print(f"Output JSONL: {JSONL_PATH}\n")
    results = []

    async with httpx.AsyncClient() as client:
        for model in MODELS:
            # Stop other models to isolate VRAM
            for other in MODELS:
                if other != model:
                    stop_model(other)
            time.sleep(1)

            print(f"--- Testing {model} (Think: OFF) ---")
            for p_idx, prompt in enumerate(DETAIL_PROMPTS):
                for run in range(1, 4):
                    rec = await test_call(client, model, prompt, run)
                    results.append(rec)
                    capped_tag = " [CAPPED]" if rec["was_capped"] else ""
                    print(f"  [{model} | P{p_idx+1} Run {run}] "
                          f"words: {rec['uncapped_word_count']} -> {rec['word_count']}{capped_tag}, "
                          f"sentences: {rec['sentence_count']}, "
                          f"{rec['duration_seconds']}s -> {'PASS' if rec['meets_criteria'] else 'FAIL'}")

    print("\n=== SUMMARY TABLE ===")
    print(f"{'Model':<15} | {'Avg Uncapped W':<16} | {'Avg Final W':<12} | {'Max Final W':<12} | {'Avg Sents':<10} | {'Target Met (150-350w, >=6s)'}")
    print("-" * 90)

    for model in MODELS:
        matched = [r for r in results if r["model"] == model]
        if matched:
            avg_uncapped_w = sum(r["uncapped_word_count"] for r in matched) / len(matched)
            avg_w = sum(r["word_count"] for r in matched) / len(matched)
            max_w = max(r["word_count"] for r in matched)
            avg_s = sum(r["sentence_count"] for r in matched) / len(matched)
            passes = sum(1 for r in matched if r["meets_criteria"])
            print(f"{model:<15} | {avg_uncapped_w:<16.1f} | {avg_w:<12.1f} | {max_w:<12} | {avg_s:<10.1f} | {passes}/{len(matched)} passed")

if __name__ == "__main__":
    asyncio.run(main())
