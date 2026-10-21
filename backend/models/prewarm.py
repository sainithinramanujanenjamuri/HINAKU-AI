import asyncio
import json
import logging
import urllib.request
from typing import Optional

from backend.config import get_settings

logger = logging.getLogger("hinaku.prewarm")

async def prewarm_local_models():
    """
    Background non-blocking task that pre-loads:
      1. Local LLM (gemma3:4b) with keep_alive: 30m, options: num_ctx: 4096
      2. Embedding model (qwen3-embedding:0.6b) with keep_alive: 5m, options: num_ctx: 512
    This ensures the user's very first message does not incur cold-load latency.
    Runs asynchronously and never blocks UI or API startup.
    """
    settings = get_settings()
    host = settings.local_host.rstrip("/")
    model = settings.default_local_model
    keep_alive = settings.local_keep_alive
    num_ctx = settings.local_num_ctx

    embed_model = settings.memory_embedding_model
    embed_keep_alive = settings.memory_embedding_keep_alive
    embed_num_ctx = settings.memory_embedding_num_ctx

    def _warm_llm():
        try:
            url = f"{host}/api/generate"
            payload = {
                "model": model,
                "keep_alive": keep_alive,
                "options": {"num_ctx": num_ctx}
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                logger.info(f"Pre-warmed local LLM '{model}' with num_ctx={num_ctx} (status: {resp.status})")
        except Exception as e:
            logger.warning(f"Could not pre-warm local LLM '{model}': {e}")

    def _warm_embed():
        try:
            url = f"{host}/api/embed"
            payload = {
                "model": embed_model,
                "keep_alive": embed_keep_alive,
                "input": [""],
                "options": {"num_ctx": embed_num_ctx}
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                logger.info(f"Pre-warmed embedding model '{embed_model}' with num_ctx={embed_num_ctx} (status: {resp.status})")
        except Exception as e:
            logger.warning(f"Could not pre-warm embedding model '{embed_model}': {e}")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _warm_llm)
    await loop.run_in_executor(None, _warm_embed)
