"""
Detail Mode Benchmark (Real App Path Execution Engine)
Runs the detail benchmark through the real FastAPI app path (/api/chat) on:
  - gemma3:4b
  - qwen3.5:4b
  - bonsai-2:9b
Prompts tested:
  1. "Explain how gradient descent works in detail." (tests "in detail")
  2. "Walk me through how virtual memory and paging work step by step." (tests "step by step")
  3. "Explain the difference between TCP and UDP." (tests "explain the difference")
3 prompts x 3 runs per model (27 total runs).
Stores full reply text, options used, and tracks whether any reply is cut off mid-sentence.
"""

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

from backend.main import app
from backend.config import get_settings

DETAIL_PROMPTS = [
    "Explain how gradient descent works in detail.",
    "Walk me through how virtual memory and paging work step by step.",
    "Explain the difference between TCP and UDP.",
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

async def run_single_turn(client: httpx.AsyncClient, model: str, prompt: str, run_idx: int) -> dict:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "stream": False,
        "is_private": True
    }

    t0 = time.perf_counter()
    res = await client.post("/api/chat", json=payload, timeout=180.0)
    dur = time.perf_counter() - t0

    if res.status_code != 200:
        raise RuntimeError(f"Chat API returned {res.status_code}: {res.text}")

    data = res.json()
    reply = data.get("content", "").strip()
    options_used = data.get("options") or {}
    was_cut = data.get("hit_token_limit", False)
    verify_status = data.get("verify_status")
    verify_reason = data.get("verify_reason") or ""
    regenerated = "Regenerated detail reply" in verify_reason

    w_count = count_words(reply)
    s_count = count_sentences(reply)

    record = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "run": run_idx,
        "prompt": prompt,
        "reply": reply,
        "word_count": w_count,
        "sentence_count": s_count,
        "options_used": options_used,
        "was_cut_off_mid_sentence": was_cut,
        "regenerated_over_350": regenerated,
        "verify_status": verify_status,
        "verify_reason": verify_reason,
        "duration_seconds": round(dur, 2),
        "latency_breakdown": data.get("latency_breakdown") or {},
        "target_met": (s_count >= 5 and 150 <= w_count <= 350 and not was_cut)
    }

    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record

async def main():
    ollama_ver = get_ollama_version()
    print("=" * 80)
    print(f"HINAKU DETAIL MODE BENCHMARK - REAL APP PATH")
    print(f"Ollama Version: {ollama_ver}")
    print(f"Output JSONL:   {JSONL_PATH}")
    print("=" * 80)

    results = []

    # Use ASGITransport to exercise the real FastAPI app in-process
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for model in MODELS:
            # Unload other models to respect the 6 GB VRAM envelope
            for other in MODELS:
                if other != model:
                    stop_model(other)
            time.sleep(1)

            print(f"\n--- Testing Model: {model} ---")
            for p_idx, prompt in enumerate(DETAIL_PROMPTS, 1):
                for run in range(1, 4):
                    print(f"  [P{p_idx} Run {run}/3] \"{prompt[:35]}...\" -> ", end="", flush=True)
                    try:
                        rec = await run_single_turn(client, model, prompt, run)
                        results.append(rec)
                        cut_tag = " [CUT_OFF!]" if rec["was_cut_off_mid_sentence"] else ""
                        regen_tag = " [REGEN_>350]" if rec["regenerated_over_350"] else ""
                        np_opt = rec["options_used"].get("num_predict", "?")
                        print(f"{rec['word_count']} words, {rec['sentence_count']} sents, "
                              f"num_predict={np_opt}, {rec['duration_seconds']}s{cut_tag}{regen_tag} -> "
                              f"{'PASS' if rec['target_met'] else 'OK'}")
                    except Exception as e:
                        print(f"ERROR: {e}")

    print("\n" + "=" * 90)
    print(f"{'Model':<14} | {'Run':<4} | {'Words':<6} | {'Sents':<6} | {'Cut Off?':<9} | {'Regen?':<8} | {'num_predict':<12} | {'Dur (s)':<8}")
    print("-" * 90)
    for r in results:
        np_val = r["options_used"].get("num_predict", "?")
        cut_str = "YES" if r["was_cut_off_mid_sentence"] else "No"
        regen_str = "YES" if r["regenerated_over_350"] else "No"
        print(f"{r['model']:<14} | {r['run']:<4} | {r['word_count']:<6} | {r['sentence_count']:<6} | {cut_str:<9} | {regen_str:<8} | {str(np_val):<12} | {r['duration_seconds']:<8.2f}")

    print("\n=== SUMMARY BY MODEL ===")
    print(f"{'Model':<14} | {'Avg Words':<10} | {'Max Words':<10} | {'Any Cut Off?':<13} | {'Regen Count':<12} | {'Pass Rate':<10}")
    print("-" * 80)
    for model in MODELS:
        m_recs = [r for r in results if r["model"] == model]
        if m_recs:
            avg_w = sum(r["word_count"] for r in m_recs) / len(m_recs)
            max_w = max(r["word_count"] for r in m_recs)
            any_cut = any(r["was_cut_off_mid_sentence"] for r in m_recs)
            regen_cnt = sum(1 for r in m_recs if r["regenerated_over_350"])
            passes = sum(1 for r in m_recs if r["target_met"])
            cut_label = "YES" if any_cut else "None (0/9)"
            print(f"{model:<14} | {avg_w:<10.1f} | {max_w:<10} | {cut_label:<13} | {regen_cnt:<12} | {passes}/{len(m_recs)}")

    print(f"\nAll records saved to: {JSONL_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
