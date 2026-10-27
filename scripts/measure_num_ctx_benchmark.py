"""
scripts/measure_num_ctx_benchmark.py

Measures latency, ollama ps, and nvidia-smi for bonsai-2:9b with:
1. num_ctx = 4096 (standard context)
2. num_ctx = 8192 (expanded context for document turns)
Records raw output to data/measure/<timestamp>_num_ctx_benchmark.txt
"""

import datetime
import json
import os
import subprocess
import sys
import time
import httpx
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.config import get_settings

def get_ollama_ps() -> str:
    try:
        res = subprocess.run(["ollama", "ps"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception as e:
        return f"ollama ps error: {e}"

def get_nvidia_smi() -> str:
    try:
        res = subprocess.run(["nvidia-smi"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception as e:
        return f"nvidia-smi error: {e}"

def run_test(num_ctx: int, host: str, model: str):
    prompt = (
        "Explain the core differences between mechanics, dynamics, and aesthetics in game design. "
        "Keep the explanation structured with bullets and provide one clear example."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are HINAKU. Answer concisely and accurately."},
            {"role": "user", "content": prompt}
        ],
        "options": {
            "num_ctx": num_ctx,
            "temperature": 0.6,
            "top_p": 0.95
        },
        "stream": False,
        "keep_alive": "30m"
    }

    t0 = time.perf_counter()
    res = httpx.post(f"{host}/api/chat", json=payload, timeout=60.0)
    dur = time.perf_counter() - t0
    data = res.json()
    eval_count = data.get("eval_count", 0)
    eval_dur_ns = data.get("eval_duration", 1)
    prompt_eval_count = data.get("prompt_eval_count", 0)
    tok_per_sec = eval_count / (eval_dur_ns / 1e9) if eval_dur_ns > 0 else 0

    ps_out = get_ollama_ps()
    smi_out = get_nvidia_smi()

    return {
        "num_ctx": num_ctx,
        "latency_sec": dur,
        "tokens_generated": eval_count,
        "prompt_tokens": prompt_eval_count,
        "tok_per_sec": tok_per_sec,
        "reply_preview": data.get("message", {}).get("content", "")[:200],
        "ollama_ps": ps_out,
        "nvidia_smi": smi_out
    }

def main():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    measure_dir = ROOT_DIR / "data" / "measure"
    measure_dir.mkdir(parents=True, exist_ok=True)
    out_file = measure_dir / f"{timestamp}_num_ctx_benchmark.txt"

    cfg = get_settings()
    host = cfg.local_host
    model = "bonsai-2:9b"

    print("Measuring num_ctx = 4096...")
    res_4096 = run_test(4096, host, model)
    time.sleep(2)

    print("Measuring num_ctx = 8192...")
    res_8192 = run_test(8192, host, model)

    latency_ratio = res_8192["latency_sec"] / res_4096["latency_sec"] if res_4096["latency_sec"] > 0 else 1.0

    lines = []
    lines.append("================================================================================")
    lines.append("HINAKU CONTEXT WINDOW BENCHMARK: bonsai-2:9b (4096 vs 8192 num_ctx)")
    lines.append(f"Timestamp: {datetime.datetime.now().isoformat()}")
    lines.append(f"Model: {model}")
    lines.append("================================================================================")
    lines.append("")
    lines.append(f"[TEST 1: num_ctx = 4096]")
    lines.append(f"Latency: {res_4096['latency_sec']:.2f} s | Tokens: {res_4096['tokens_generated']} | Speed: {res_4096['tok_per_sec']:.1f} tok/s")
    lines.append(f"OLLAMA PS:\n{res_4096['ollama_ps']}\n")
    lines.append(f"NVIDIA-SMI:\n{res_4096['nvidia_smi']}\n")
    lines.append("")
    lines.append(f"[TEST 2: num_ctx = 8192]")
    lines.append(f"Latency: {res_8192['latency_sec']:.2f} s | Tokens: {res_8192['tokens_generated']} | Speed: {res_8192['tok_per_sec']:.1f} tok/s")
    lines.append(f"Latency Ratio (8192 / 4096): {latency_ratio:.2f}x")
    lines.append(f"OLLAMA PS:\n{res_8192['ollama_ps']}\n")
    lines.append(f"NVIDIA-SMI:\n{res_8192['nvidia_smi']}\n")
    lines.append("================================================================================")
    
    is_100_gpu = "100% GPU" in res_8192["ollama_ps"]
    under_2x = latency_ratio < 2.0
    recommendation = "RAISE to 8192 for document turns" if (is_100_gpu and under_2x) else "KEEP 4096 (exceeds VRAM or 2x latency threshold)"
    lines.append(f"VERDICT: {recommendation}")
    lines.append(f"- Stays 100% GPU offload: {is_100_gpu}")
    lines.append(f"- Latency under 2x multiplier ({latency_ratio:.2f}x < 2.0x): {under_2x}")
    lines.append("================================================================================")

    report_str = "\n".join(lines) + "\n"
    out_file.write_text(report_str, encoding="utf-8")
    print(f"Report written to: {out_file}")
    print(report_str.encode("ascii", errors="replace").decode("ascii"))

if __name__ == "__main__":
    main()
