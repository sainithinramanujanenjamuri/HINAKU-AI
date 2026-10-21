import asyncio
import time
import sys
from pathlib import Path

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
from backend.models.ollama_adapter import OllamaAdapter
from backend.memory.storage import MemoryStorage
from backend.memory.manager import MemoryManager
from backend.guards import check_and_redact_sensitive_data, is_live_data_query
import tempfile
from pathlib import Path
import shutil

async def profile_pipeline():
    settings = get_settings()
    host = settings.local_host
    model = settings.default_local_model # gemma3:4b
    keep_alive = settings.local_keep_alive # 30m

    print(f"=== HINAKU Speed Profiling ===")
    print(f"Model: {model} | Keep-alive: {keep_alive} | Host: {host}")

    test_prompt = "Who are you?"

    # 1. Guard check time
    t0 = time.perf_counter()
    is_sens, _ = check_and_redact_sensitive_data(test_prompt)
    is_live = is_live_data_query(test_prompt)
    t_guard = (time.perf_counter() - t0) * 1000

    # 2. Temporary memory setup and query embedding
    td = tempfile.mkdtemp()
    try:
        storage = MemoryStorage(
            db_path=Path(td) / "mem.db",
            chroma_path=Path(td) / "chroma",
            embedding_model=settings.memory_embedding_model,
            embedding_dims=settings.memory_embedding_dims,
            query_prefix=settings.memory_query_prefix,
            document_prefix=settings.memory_document_prefix,
            ollama_host=host
        )
        storage.add_memory("Uses a laptop with an RTX 4050 and 6 GB VRAM")
        storage.add_memory("Favorite editor is VS Code")

        mem_mgr = MemoryManager(
            storage=storage,
            extractor=None,
            enabled=True,
            retrieve_top_k=settings.memory_retrieve_top_k,
            min_similarity=settings.memory_min_similarity
        )

        # Measure memory retrieval (including Ollama embedding query)
        t0 = time.perf_counter()
        mem_context = mem_mgr.retrieve_context(test_prompt, is_private=False, is_api_request=False)
        t_memory = (time.perf_counter() - t0) * 1000

    finally:
        shutil.rmtree(td, ignore_errors=True)

    # 3. Model Streaming (TTFT and total generation)
    adapter = OllamaAdapter(
        host=host,
        default_model=model,
        default_options=settings.local_options,
        default_think=False,
        default_keep_alive=keep_alive
    )

    messages = [
        {"role": "system", "content": "You are HINAKU, a personal AI built for one person: your owner. Answer directly in 1-2 sentences."},
        {"role": "user", "content": test_prompt}
    ]

    # Warm up model / first call (cold or warm)
    t0 = time.perf_counter()
    first_token_time = None
    accumulated = []

    async for chunk in adapter.stream_chat(messages, model=model, keep_alive=keep_alive):
        if first_token_time is None and chunk.strip():
            first_token_time = (time.perf_counter() - t0) * 1000
        accumulated.append(chunk)

    total_time = (time.perf_counter() - t0) * 1000
    reply = "".join(accumulated).strip()

    # Second call (demonstrating keep_alive warm latency)
    t0_warm = time.perf_counter()
    first_token_time_warm = None
    accumulated_warm = []
    async for chunk in adapter.stream_chat(messages, model=model, keep_alive=keep_alive):
        if first_token_time_warm is None and chunk.strip():
            first_token_time_warm = (time.perf_counter() - t0_warm) * 1000
        accumulated_warm.append(chunk)
    total_time_warm = (time.perf_counter() - t0_warm) * 1000
    reply_warm = "".join(accumulated_warm).strip()

    print(f"\n--- Measurements ---")
    print(f"Guard Evaluation:                  {t_guard:.2f} ms")
    print(f"Memory Retrieval (Query Embed):    {t_memory:.2f} ms")
    print(f"Initial Run (TTFT):                {first_token_time:.2f} ms")
    print(f"Initial Run Total Generation:      {total_time:.2f} ms ({total_time/1000:.2f}s)")
    print(f"Warm Run with keep_alive (TTFT):   {first_token_time_warm:.2f} ms")
    print(f"Warm Run Total Generation:         {total_time_warm:.2f} ms ({total_time_warm/1000:.2f}s)")
    print(f"\nSample Reply: {reply_warm}")

if __name__ == "__main__":
    asyncio.run(profile_pipeline())
