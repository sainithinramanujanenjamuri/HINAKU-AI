import asyncio
import json
import logging
import urllib.request
from typing import Optional

from backend.config import get_settings
from backend.models.ollama_shared import (
    get_shared_llm_settings,
    get_shared_embedding_settings,
    log_ollama_call
)

logger = logging.getLogger("hinaku.prewarm")

async def prewarm_local_models():
    """
    Background non-blocking task that pre-loads:
      1. Local LLM (gemma3:4b) with keep_alive: 30m, options: num_ctx: 4096
      2. Embedding model (qwen3-embedding:0.6b) with keep_alive: 5m, options: num_ctx: 512
    Uses shared canonical settings so chat and background extraction never trigger reloads.
    This ensures the user's very first message does not incur cold-load latency.
    Runs asynchronously and never blocks UI or API startup.
    """
    settings = get_settings()
    host = settings.local_host.rstrip("/")

    def _warm_llm():
        try:
            llm_settings = get_shared_llm_settings()
            url = f"{host}/api/generate"
            payload = {
                "model": llm_settings["model"],
                "keep_alive": llm_settings["keep_alive"],
                "options": llm_settings["options"]
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                load_dur = data.get("load_duration", 0)
                total_dur = data.get("total_duration", 0)
                log_ollama_call(
                    call_type="prewarm_llm",
                    model=llm_settings["model"],
                    num_ctx=llm_settings["options"].get("num_ctx"),
                    keep_alive=llm_settings["keep_alive"],
                    options=llm_settings["options"],
                    load_duration_ns=load_dur,
                    total_duration_ns=total_dur
                )
                logger.info(f"Pre-warmed local LLM '{llm_settings['model']}' with num_ctx={llm_settings['options'].get('num_ctx')} (load: {load_dur/1e9:.3f}s)")
        except Exception as e:
            logger.warning(f"Could not pre-warm local LLM: {e}")

    def _warm_embed():
        try:
            embed_settings = get_shared_embedding_settings()
            url = f"{host}/api/embed"
            payload = {
                "model": embed_settings["model"],
                "keep_alive": embed_settings["keep_alive"],
                "input": [""],
                "options": embed_settings["options"]
            }
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                load_dur = data.get("load_duration", 0)
                total_dur = data.get("total_duration", 0)
                log_ollama_call(
                    call_type="prewarm_embed",
                    model=embed_settings["model"],
                    num_ctx=embed_settings["options"].get("num_ctx"),
                    keep_alive=embed_settings["keep_alive"],
                    options=embed_settings["options"],
                    load_duration_ns=load_dur,
                    total_duration_ns=total_dur
                )
                logger.info(f"Pre-warmed embedding model '{embed_settings['model']}' with num_ctx={embed_settings['options'].get('num_ctx')} (load: {load_dur/1e9:.3f}s)")
        except Exception as e:
            logger.warning(f"Could not pre-warm embedding model: {e}")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _warm_llm)
    await loop.run_in_executor(None, _warm_embed)
