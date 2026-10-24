import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path
import httpx

DETAIL_PROMPTS = [
    "Explain how gradient descent works in deep learning in more detail.",
    "Can you give a longer explanation of how virtual memory and paging work?",
    "Explain the difference between TCP and UDP in depth.",
]

MODELS = ["gemma3:4b", "qwen3.5:4b", "bonsai-2:9b"]
THINK_MODELS = {"qwen3.5:4b", "bonsai-2:9b"}

OUT_DIR = Path("data/bakeoff")
OUT_DIR.mkdir(parents=True, exist_ok=True)
TIMESTAMP_STR = datetime.now().strftime("%Y-%m-%d_%H%M%S")
JSONL_PATH = OUT_DIR / f"detail_mode_{TIMESTAMP_STR}.jsonl"

def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def count_sentences(text: str) -> int:
    clean = text.replace("vs.", "").replace("e.g.", "").replace("i.e.", "")
    parts = [p.strip() for p in re.split(r"[.!?]+", clean) if p.strip()]
    return len(parts)

async def test_call(client: httpx.AsyncClient, model: str, prompt: str, think: bool, run_idx: int) -> dict:
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are HINAKU, a personal AI. Default to four sentences or fewer. "
                    "If the owner asks for more detail, a longer explanation, or an in-depth answer, "
                    "give a complete, well-organized explanation (short paragraphs, up to about 350 words) "
                    "and ignore the four-sentence limit for that reply. Stay on the topic asked and do not pad."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "options": {
            "num_predict": 900,
            "temperature": 0.6
        },
        "think": think,
        "stream": False
    }

    t0 = time.perf_counter()
    res = await client.post(url, json=payload, timeout=120.0)
    dur = time.perf_counter() - t0
    data = res.json()
    reply = data.get("message", {}).get("content", "").strip()

    words = count_words(reply)
    sentences = count_sentences(reply)

    record = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "think": think,
        "run": run_idx,
        "prompt": prompt,
        "word_count": words,
        "sentence_count": sentences,
        "duration_seconds": round(dur, 2),
        "meets_criteria": (sentences >= 6 and 150 <= words <= 350),
        "reply_preview": reply[:150] + ("..." if len(reply) > 150 else "")
    }

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record

async def main():
    print(f"Detail Mode Benchmark starting...")
    print(f"Output JSONL: {JSONL_PATH}\n")
    results = []

    async with httpx.AsyncClient() as client:
        for model in MODELS:
            think_options = [False, True] if model in THINK_MODELS else [False]
            for think in think_options:
                think_label = "Think: ON" if think else "Think: OFF"
                print(f"--- Testing {model} ({think_label}) ---")
                for p_idx, prompt in enumerate(DETAIL_PROMPTS):
                    for run in range(1, 4):
                        rec = await test_call(client, model, prompt, think, run)
                        results.append(rec)
                        print(f"  [{model} | {think_label} | P{p_idx+1} Run {run}] "
                              f"{rec['word_count']} words, {rec['sentence_count']} sentences, "
                              f"{rec['duration_seconds']}s -> {'PASS' if rec['meets_criteria'] else 'FAIL'}")

    print("\n=== SUMMARY TABLE ===")
    print(f"{'Model':<15} | {'Think':<6} | {'Avg Words':<10} | {'Avg Sents':<10} | {'Target Met (150-350w, >=6s)'}")
    print("-" * 65)

    for model in MODELS:
        think_options = [False, True] if model in THINK_MODELS else [False]
        for think in think_options:
            matched = [r for r in results if r["model"] == model and r["think"] == think]
            if matched:
                avg_w = sum(r["word_count"] for r in matched) / len(matched)
                avg_s = sum(r["sentence_count"] for r in matched) / len(matched)
                passes = sum(1 for r in matched if r["meets_criteria"])
                print(f"{model:<15} | {str(think):<6} | {avg_w:<10.1f} | {avg_s:<10.1f} | {passes}/{len(matched)} passed")

if __name__ == "__main__":
    asyncio.run(main())
