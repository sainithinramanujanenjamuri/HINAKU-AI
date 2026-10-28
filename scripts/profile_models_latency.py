#!/usr/bin/env python3
"""
Profiles real app pipeline TTFT and VRAM latency for local models:
- One model at a time
- Stops other models before running
- 6 turns each with memory on, persona, clock context, settings.yaml options
- Captures ollama ps and nvidia-smi after every turn
- Verifies think: false for qwen3.5:4b (no reasoning tokens)
- Checks whether other processes use GPU
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from backend.config import get_settings
from backend.persona import PersonaManager
from backend.memory.storage import MemoryStorage
from backend.memory.manager import MemoryManager
from backend.models.ollama_adapter import OllamaAdapter, strip_thinking
from backend.guards import get_system_clock_context, is_clock_query, get_clock_reply

TURNS = [
    "Who are you?",
    "how is today",
    "which GPU should I plan training around?",
    "which editor should I set up my shortcuts in?",
    "should I skip testing and ship tonight?",
    "How long should your replies be?"
]

SAMPLE_MEMORIES = [
    "Uses a laptop with an RTX 4050 and 6 GB VRAM",
    "Favorite editor is VS Code",
    "Prefers short direct answers"
]

def run_ollama_stop(model_name: str, host: str = "http://127.0.0.1:11434"):
    try:
        subprocess.run(["ollama", "stop", model_name], capture_output=True, text=True, timeout=10)
    except Exception as e:
        pass

def get_nvidia_smi_snapshot() -> Dict[str, Any]:
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            used_mb = float(parts[0])
            total_mb = float(parts[1])
            gpu_util = int(parts[2])
            temp_c = int(parts[3])
        else:
            used_mb, total_mb, gpu_util, temp_c = 0.0, 6141.0, 0, 0

        # Query compute processes
        cmd_proc = ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"]
        res_proc = subprocess.run(cmd_proc, capture_output=True, text=True, timeout=5)
        proc_list = []
        if res_proc.returncode == 0 and res_proc.stdout.strip():
            for line in res_proc.stdout.strip().splitlines():
                if line.strip():
                    proc_list.append(line.strip())

        return {
            "used_mb": used_mb,
            "total_mb": total_mb,
            "gpu_util_pct": gpu_util,
            "temp_c": temp_c,
            "processes": proc_list,
            "summary": f"{used_mb:,.0f} MiB / {total_mb:,.0f} MiB ({gpu_util}% util, {temp_c}°C)"
        }
    except Exception as e:
        return {
            "used_mb": 0.0,
            "total_mb": 6141.0,
            "gpu_util_pct": 0,
            "temp_c": 0,
            "processes": [],
            "summary": f"Unavailable ({e})"
        }

def get_ollama_ps_snapshot(host: str = "http://127.0.0.1:11434") -> Dict[str, Any]:
    try:
        url = f"{host.rstrip('/')}/api/ps"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            items = []
            total_vram = 0
            for m in models:
                vram_mb = m.get("size_vram", 0) / (1024 * 1024)
                total_vram += vram_mb
                items.append(f"{m.get('name')}: {vram_mb:,.0f} MB")
            return {
                "models": models,
                "total_vram_mb": total_vram,
                "summary": ", ".join(items) if items else "None"
            }
    except Exception as e:
        return {"models": [], "total_vram_mb": 0.0, "summary": f"Error: {e}"}

async def profile_model(
    model_name: str,
    other_model: str,
    host: str,
    options: Dict[str, Any],
    persona_text: str,
    mem_manager: MemoryManager,
    settings: Any
) -> Dict[str, Any]:
    print(f"\n=======================================================================", flush=True)
    print(f" PROFILING: {model_name} (One Model at a Time)", flush=True)
    print(f"=======================================================================", flush=True)

    # 1. Stop other model to prevent VRAM competition or swapping
    print(f" -> Stopping '{other_model}' via ollama stop...", end="", flush=True)
    run_ollama_stop(other_model, host)
    print(" done.", flush=True)

    # Give Ollama a moment to release memory
    await asyncio.sleep(1.0)

    adapter = OllamaAdapter(
        host=host,
        default_model=model_name,
        default_options=options,
        default_think=False,
        default_keep_alive="30m"
    )

    turn_results = []
    reasoning_tokens_detected = False

    for turn_idx, prompt in enumerate(TURNS, 1):
        print(f"\n[Turn {turn_idx}/6] \"{prompt}\"", flush=True)

        clock_ctx = get_system_clock_context()
        mem_ctx = mem_manager.retrieve_context(prompt, is_private=False, is_api_request=False)
        sys_parts = [persona_text, clock_ctx]
        if mem_ctx:
            sys_parts.append(mem_ctx)
        sys_prompt = "\n\n".join(sys_parts)

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]

        t0 = time.perf_counter()
        first_token_time = None
        raw_chunks = []

        try:
            async for chunk in adapter.stream_chat(
                messages=messages,
                model=model_name,
                options=options,
                think=False,
                keep_alive="30m"
            ):
                if first_token_time is None and chunk.strip():
                    first_token_time = time.perf_counter() - t0
                raw_chunks.append(chunk)
                # Check for reasoning tokens (<think> tags)
                if "<think>" in chunk or "</think>" in chunk:
                    reasoning_tokens_detected = True

        except Exception as e:
            raw_chunks.append(f"[Error: {e}]")

        t1 = time.perf_counter()
        latency_sec = t1 - t0
        ttft_sec = first_token_time if first_token_time is not None else latency_sec
        reply_text = strip_thinking("".join(raw_chunks)).strip()

        # Query Ollama PS & nvidia-smi immediately after turn
        ollama_ps = get_ollama_ps_snapshot(host)
        smi = get_nvidia_smi_snapshot()

        print(f"  TTFT:        {ttft_sec:.3f}s", flush=True)
        print(f"  Total Time:  {latency_sec:.3f}s", flush=True)
        print(f"  Ollama PS:   {ollama_ps['summary']}", flush=True)
        print(f"  NVIDIA-SMI:  {smi['summary']}", flush=True)
        print(f"  Reply:       {reply_text[:100]}...", flush=True)

        turn_results.append({
            "turn": turn_idx,
            "prompt": prompt,
            "ttft": ttft_sec,
            "latency": latency_sec,
            "ollama_ps": ollama_ps["summary"],
            "nvidia_smi": smi["summary"],
            "gpu_processes": smi["processes"],
            "reply": reply_text
        })

    avg_ttft = sum(r["ttft"] for r in turn_results) / len(turn_results)
    avg_warm_ttft = sum(r["ttft"] for r in turn_results[1:]) / len(turn_results[1:]) if len(turn_results) > 1 else avg_ttft
    avg_latency = sum(r["latency"] for r in turn_results) / len(turn_results)

    return {
        "model": model_name,
        "turns": turn_results,
        "avg_ttft": avg_ttft,
        "avg_warm_ttft": avg_warm_ttft,
        "avg_latency": avg_latency,
        "reasoning_tokens_detected": reasoning_tokens_detected
    }

async def main_profile():
    settings = get_settings()
    host = settings.local_host
    persona_mgr = PersonaManager(file_path=settings.persona_file)
    persona_text = persona_mgr.get_persona().content

    options = dict(settings.local_options)
    options.setdefault("presence_penalty", 0.0)

    # Initial GPU state
    initial_smi = get_nvidia_smi_snapshot()
    print("Initial NVIDIA-SMI state:", initial_smi["summary"])
    if initial_smi["processes"]:
        print("Initial GPU processes:", initial_smi["processes"])
    else:
        print("Initial GPU processes: None (GPU is completely dedicated to HINAKU)")

    # Isolated memory
    temp_dir = tempfile.mkdtemp(prefix="hinaku_profile_")
    temp_path = Path(temp_dir)
    mem_storage = MemoryStorage(
        db_path=temp_path / "mem.db",
        chroma_path=temp_path / "chroma",
        embedding_model=settings.memory_embedding_model,
        embedding_dims=settings.memory_embedding_dims,
        query_prefix=settings.memory_query_prefix,
        document_prefix=settings.memory_document_prefix,
        ollama_host=host,
        embedding_keep_alive="30m",
        embedding_num_ctx=settings.memory_embedding_num_ctx
    )
    mem_manager = MemoryManager(storage=mem_storage, extractor=None, enabled=True)
    for m in SAMPLE_MEMORIES:
        mem_storage.add_memory(m)

    try:
        # Profile gemma3:4b first
        res_gemma = await profile_model(
            model_name="gemma3:4b",
            other_model="qwen3.5:4b",
            host=host,
            options=options,
            persona_text=persona_text,
            mem_manager=mem_manager,
            settings=settings
        )

        # Profile qwen3.5:4b second
        res_qwen = await profile_model(
            model_name="qwen3.5:4b",
            other_model="gemma3:4b",
            host=host,
            options=options,
            persona_text=persona_text,
            mem_manager=mem_manager,
            settings=settings
        )

        # Output Summary
        print("\n" + "=" * 80)
        print(" LATENCY & VRAM PROFILE SUMMARY TABLE")
        print("=" * 80)
        print(f"| Model | Turn 1 TTFT (Cold) | Turns 2-6 Avg TTFT (Warm) | Overall Avg TTFT | Avg Latency | Peak NVIDIA-SMI | Reasoning Tokens? |")
        print(f"| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")

        for res in [res_gemma, res_qwen]:
            t1_ttft = f"{res['turns'][0]['ttft']:.3f}s"
            warm_ttft = f"{res['avg_warm_ttft']:.3f}s"
            overall_ttft = f"{res['avg_ttft']:.3f}s"
            avg_lat = f"{res['avg_latency']:.3f}s"
            peak_smi = max(float(r['nvidia_smi'].split()[0].replace(',', '')) for r in res['turns'])
            reasoning = "NONE (think:false respected)" if not res['reasoning_tokens_detected'] else "DETECTED"
            print(f"| **{res['model']}** | {t1_ttft} | **{warm_ttft}** | {overall_ttft} | {avg_lat} | {peak_smi:,.0f} MiB | {reasoning} |")

        # Save results to data/latency_profile.json
        out_file = ROOT_DIR / "data" / "latency_profile.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "initial_gpu_processes": initial_smi["processes"],
                "gemma3:4b": res_gemma,
                "qwen3.5:4b": res_qwen
            }, f, indent=2)
        print(f"\nSaved profile details to: {out_file}")

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(main_profile())
