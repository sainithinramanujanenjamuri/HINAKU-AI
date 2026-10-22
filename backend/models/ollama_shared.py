"""
backend/models/ollama_shared.py

Centralized helper for Ollama load-affecting settings and per-call profiling logs.
Ensures that all call sites (chat, memory extraction, prewarm, embeddings)
send identical load-affecting options (num_ctx, keep_alive, num_gpu, flash attention)
so Ollama never re-initializes or reloads the model runner unexpectedly.
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple

from backend.config import get_settings

logger = logging.getLogger("hinaku.ollama")
profile_logger = logging.getLogger("hinaku.ollama.profile")

# Profiling mode toggle: enabled if HINAKU_PROFILE_OLLAMA is set in environment or settings
def is_profiling_enabled() -> bool:
    env_val = os.getenv("HINAKU_PROFILE_OLLAMA", "").lower().strip()
    if env_val in ("1", "true", "yes", "on"):
        return True
    try:
        settings = get_settings()
        return getattr(settings, "profiling_mode", False) or False
    except Exception:
        return False

def get_shared_llm_settings(override_model: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns the canonical load-affecting and inference settings for the local LLM.
    Guarantees that chat, background memory extraction, and prewarm send identical
    runner configurations so llama-server never reloads.
    """
    settings = get_settings()
    model = override_model or settings.default_local_model
    keep_alive = settings.local_keep_alive or "30m"

    # Base options loaded directly from settings.local_options
    base_options = dict(settings.local_options) if settings.local_options else {}

    # Explicitly enforce canonical load-affecting parameters
    canonical_options: Dict[str, Any] = {
        "num_ctx": settings.local_num_ctx or 4096,
        "temperature": base_options.get("temperature", 0.6),
        "top_p": base_options.get("top_p", 0.9),
        "repeat_penalty": base_options.get("repeat_penalty", 1.1),
        "presence_penalty": base_options.get("presence_penalty", 0.0),
        "num_predict": base_options.get("num_predict", 300),
    }

    # Pass through hardware load-affecting flags if present in settings
    if "num_gpu" in base_options:
        canonical_options["num_gpu"] = base_options["num_gpu"]
    if "flash_attention" in base_options:
        canonical_options["flash_attention"] = base_options["flash_attention"]

    return {
        "model": model,
        "keep_alive": keep_alive,
        "options": canonical_options,
        "think": settings.local_think or False
    }

def get_shared_embedding_settings(override_model: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns the canonical load-affecting settings for the embedding model.
    Guarantees that memory storage retrieval, persistence, and prewarm send identical
    runner configurations.
    """
    settings = get_settings()
    model = override_model or settings.memory_embedding_model
    keep_alive = settings.memory_embedding_keep_alive or "5m"
    num_ctx = settings.memory_embedding_num_ctx or 512

    canonical_options: Dict[str, Any] = {
        "num_ctx": num_ctx
    }

    return {
        "model": model,
        "keep_alive": keep_alive,
        "options": canonical_options
    }

def log_ollama_call(
    call_type: str,
    model: str,
    num_ctx: Any,
    keep_alive: Any,
    options: Dict[str, Any],
    load_duration_ns: int,
    total_duration_ns: int,
    extra_info: Optional[str] = None
) -> str:
    """
    Logs every Ollama call with model, num_ctx, keep_alive, all options,
    load_duration, and total_duration.
    When profiling mode is active (or HINAKU_PROFILE_OLLAMA=1), prints one line per call.
    """
    load_s = (load_duration_ns or 0) / 1e9
    total_s = (total_duration_ns or 0) / 1e9

    opts_str = json.dumps(options or {}, sort_keys=True)
    extra_str = f" | {extra_info}" if extra_info else ""

    line = (
        f"[OLLAMA PROFILE] call={call_type} model={model} num_ctx={num_ctx} "
        f"keep_alive={keep_alive} options={opts_str} "
        f"load_duration={load_s:.4f}s total_duration={total_s:.4f}s{extra_str}"
    )

    profile_logger.info(line)

    if is_profiling_enabled():
        print(line, flush=True)

    return line
