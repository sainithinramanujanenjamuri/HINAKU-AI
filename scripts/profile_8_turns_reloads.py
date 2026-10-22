#!/usr/bin/env python3
"""
scripts/profile_8_turns_reloads.py

Profiles 8 turns with memory on for gemma3:4b:
- Measures load_duration and total_duration for every Ollama call (chat, extraction, embeddings)
- Tracks llama-server process IDs to detect if processes change / reload
- Runs 8 turns twice
- Outputs a comprehensive comparison table
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Enable Ollama profiling mode
os.environ["HINAKU_PROFILE_OLLAMA"] = "1"

from backend.config import get_settings
from backend.persona import PersonaManager
from backend.history import ChatHistoryManager
from backend.memory.storage import MemoryStorage
from backend.memory.extractor import MemoryExtractor
from backend.memory.manager import MemoryManager
from backend.models.ollama_adapter import OllamaAdapter
from backend.models.prewarm import prewarm_local_models
from backend.models.ollama_shared import get_shared_llm_settings, get_shared_embedding_settings
from backend.guards import get_system_clock_context

TURNS = [
    "Hi, I am testing the app today.",
    "I have an HP laptop with an RTX 4050 GPU and 6 GB VRAM.",
    "My favorite code editor is VS Code.",
    "Which GPU should I plan my fine-tuning around?",
    "Which editor did I say I prefer?",
    "I also like developing with Python 3.11.",
    "Can you summarize what you know about my tech stack?",
    "Thank you, that is all for now."
]

def get_llama_server_pids() -> List[int]:
    try:
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        pids = [int(p.strip()) for p in res.stdout.strip().splitlines() if p.strip().isdigit()]
        return sorted(pids)
    except Exception:
        return []

def get_ollama_ps_summary() -> str:
    try:
        res = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=5)
        lines = [l for l in res.stdout.strip().splitlines() if l.strip()]
        if len(lines) <= 1:
            return "None"
        models = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 3:
                models.append(f"{parts[0]} ({parts[2]})")
        return ", ".join(models)
    except Exception:
        return "Unknown"

async def execute_8_turns_run(run_number: int, prewarm: bool = True) -> Dict[str, Any]:
    print(f"\n{'='*75}")
    print(f" EXECUTION: Run {run_number} of 2 (Prewarm={prewarm})")
    print(f"{'='*75}")

    settings = get_settings()
    host = settings.local_host
    persona_mgr = PersonaManager(file_path=settings.persona_file)
    persona_text = persona_mgr.get_persona().content

    if prewarm:
        print(" -> Pre-warming local models with canonical settings...", end="", flush=True)
        await prewarm_local_models()
        print(" done.", flush=True)

    temp_dir = tempfile.mkdtemp(prefix=f"hinaku_reload_run{run_number}_")
    temp_path = Path(temp_dir)

    history = ChatHistoryManager(db_path=temp_path / "test.db")
    conv_id = f"test-conv-run-{run_number}"
    history.create_conversation(conv_id=conv_id, is_private=False)

    storage = MemoryStorage(
        db_path=temp_path / "test.db",
        chroma_path=temp_path / "chroma",
        embedding_model=settings.memory_embedding_model,
        embedding_dims=settings.memory_embedding_dims,
        query_prefix=settings.memory_query_prefix,
        document_prefix=settings.memory_document_prefix,
        ollama_host=host,
        embedding_keep_alive=settings.memory_embedding_keep_alive,
        embedding_num_ctx=settings.memory_embedding_num_ctx
    )

    adapter = OllamaAdapter(host=host)

    extractor = MemoryExtractor(
        local_adapter=adapter,
        storage=storage,
        never_store_categories=settings.memory_never_store,
        merge_threshold=settings.memory_merge_threshold
    )

    manager = MemoryManager(
        storage=storage,
        extractor=extractor,
        enabled=True,
        learn_from_private_chats=False,
        retrieve_top_k=settings.memory_retrieve_top_k,
        min_similarity=settings.memory_min_similarity
    )

    initial_pids = get_llama_server_pids()
    print(f" Initial llama-server PIDs: {initial_pids}")
    print(f" Initial Ollama PS:         {get_ollama_ps_summary()}\n")

    turns_data = []

    for idx, prompt in enumerate(TURNS, 1):
        print(f"--- [Run {run_number} | Turn {idx}/8] \"{prompt}\" ---", flush=True)
        pids_before = get_llama_server_pids()

        # 1. Retrieval (calls embedding model)
        t_ret_0 = time.perf_counter()
        mem_ctx = manager.retrieve_context(prompt, is_private=False, is_api_request=False)
        t_ret = time.perf_counter() - t_ret_0
        pids_mid1 = get_llama_server_pids()

        # 2. Chat stream (calls LLM)
        clock_ctx = get_system_clock_context()
        sys_parts = [persona_text, clock_ctx]
        if mem_ctx:
            sys_parts.append(mem_ctx)
        sys_prompt = "\n\n".join(sys_parts)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ]

        t_chat_0 = time.perf_counter()
        chat_chunks = []
        async for chunk in adapter.stream_chat(messages, call_type="chat"):
            chat_chunks.append(chunk)
        t_chat = time.perf_counter() - t_chat_0
        chat_response = "".join(chat_chunks)
        chat_load_dur = adapter.last_load_duration / 1e9
        chat_total_dur = adapter.last_total_duration / 1e9
        pids_mid2 = get_llama_server_pids()

        # 3. Background extraction (calls LLM + embeddings)
        t_ext_0 = time.perf_counter()
        saved_mems = await manager.extract_and_store(
            conversation_id=conv_id,
            user_message=prompt,
            assistant_message=chat_response,
            is_private=False
        )
        t_ext = time.perf_counter() - t_ext_0
        ext_load_dur = adapter.last_load_duration / 1e9
        pids_after = get_llama_server_pids()

        # Check PID stability
        all_pids_turn = [pids_before, pids_mid1, pids_mid2, pids_after]
        pid_stable = all(p == pids_before for p in all_pids_turn)

        print(f"   Chat load_duration: {chat_load_dur:.4f}s | total_duration: {chat_total_dur:.3f}s (wall: {t_chat:.3f}s)")
        print(f"   Ext  load_duration: {ext_load_dur:.4f}s | wall: {t_ext:.3f}s")
        print(f"   PIDs: {pids_before} -> {pids_after} (Stable: {pid_stable})")
        print(f"   Ollama PS: {get_ollama_ps_summary()}\n", flush=True)

        turns_data.append({
            "turn": idx,
            "prompt": prompt,
            "chat_load_dur": chat_load_dur,
            "chat_total_dur": chat_total_dur,
            "chat_wall": t_chat,
            "ext_load_dur": ext_load_dur,
            "ext_wall": t_ext,
            "ret_wall": t_ret,
            "pids_before": pids_before,
            "pids_after": pids_after,
            "pid_stable": pid_stable,
            "extracted_count": len(saved_mems)
        })

    return {
        "run": run_number,
        "initial_pids": initial_pids,
        "final_pids": get_llama_server_pids(),
        "turns": turns_data
    }

async def main():
    print("=" * 75)
    print(" HINAKU 8-TURNS OLLAMA RELOAD & PID STABILITY AUDIT")
    print(f" Target Model: {get_shared_llm_settings()['model']}")
    print(f" Canonical LLM Settings:       {get_shared_llm_settings()}")
    print(f" Canonical Embedding Settings: {get_shared_embedding_settings()}")
    print("=" * 75)

    # Make sure GPU has no conflicting models
    print("\nEnsuring dedicated GPU state...")
    try:
        subprocess.run(["ollama", "stop", "qwen3.5:4b"], capture_output=True, timeout=5)
    except Exception:
        pass

    # Run 1
    run1 = await execute_8_turns_run(1, prewarm=True)

    # Run 2
    run2 = await execute_8_turns_run(2, prewarm=True)

    # Print Summary Tables
    print("\n" + "=" * 95)
    print(" SUMMARY: 8-TURNS RUN 1 (LOAD DURATION & PID STABILITY)")
    print("=" * 95)
    print(f"| Turn | Prompt | Chat load_dur | Chat total_dur | Ext load_dur | PIDs Before -> After | PID Stable? |")
    print(f"| :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
    for t in run1["turns"]:
        p_short = t["prompt"] if len(t["prompt"]) <= 35 else t["prompt"][:32] + "..."
        pids_str = f"{t['pids_before']} -> {t['pids_after']}"
        stable_str = "YES (Preserved)" if t["pid_stable"] else "NO (Changed)"
        print(f"| {t['turn']} | {p_short} | {t['chat_load_dur']:.4f}s | {t['chat_total_dur']:.3f}s | {t['ext_load_dur']:.4f}s | {pids_str} | {stable_str} |")

    print("\n" + "=" * 95)
    print(" SUMMARY: 8-TURNS RUN 2 (LOAD DURATION & PID STABILITY)")
    print("=" * 95)
    print(f"| Turn | Prompt | Chat load_dur | Chat total_dur | Ext load_dur | PIDs Before -> After | PID Stable? |")
    print(f"| :---: | :--- | :---: | :---: | :---: | :---: | :---: |")
    for t in run2["turns"]:
        p_short = t["prompt"] if len(t["prompt"]) <= 35 else t["prompt"][:32] + "..."
        pids_str = f"{t['pids_before']} -> {t['pids_after']}"
        stable_str = "YES (Preserved)" if t["pid_stable"] else "NO (Changed)"
        print(f"| {t['turn']} | {p_short} | {t['chat_load_dur']:.4f}s | {t['chat_total_dur']:.3f}s | {t['ext_load_dur']:.4f}s | {pids_str} | {stable_str} |")

if __name__ == "__main__":
    asyncio.run(main())
