"""
Disk Safety Preflight and Path Configuration for HINAKU Training.

Guarantees that training or export never exhausts drive space:
- Checks free space on temp and cache drives before export/training.
- Refuses to start if free space < required + 2 GB safety margin.
- Uses configured training temp (D:\\hinaku-tmp) and HF cache (D:\\hf-cache).
- Reports exact paths where large models and weights are written.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, Union

from backend.config import get_settings

logger = logging.getLogger("hinaku.disk_safety")

def get_drive_root(path: Union[str, Path]) -> Path:
    """Returns the drive or mount root for a given path."""
    resolved = Path(path).resolve()
    # On Windows, drive letter like D:\ or C:\
    if resolved.drive:
        return Path(f"{resolved.drive}\\")
    # On Unix, root /
    return Path(resolved.anchor or "/")

def check_disk_space(
    target_path: Union[str, Path],
    required_gb: float = 3.0,
    margin_gb: float = 2.0
) -> Tuple[bool, float, str]:
    """
    Checks if the drive containing target_path has at least (required_gb + margin_gb) free space.
    
    Returns:
        (is_safe, free_gb, message)
    """
    p = Path(target_path)
    # If directory doesn't exist, check parent or drive root
    check_dir = p
    while not check_dir.exists() and check_dir != check_dir.parent:
        check_dir = check_dir.parent

    try:
        usage = shutil.disk_usage(check_dir)
        free_gb = round(usage.free / (1024 ** 3), 2)
        total_needed = required_gb + margin_gb
        drive_name = str(get_drive_root(p))

        if free_gb < total_needed:
            err_msg = (
                f"Refusing to start: Insufficient disk space on drive '{drive_name}'. "
                f"Free: {free_gb:.2f} GB, Required: {total_needed:.2f} GB "
                f"({required_gb:.2f} GB required + {margin_gb:.2f} GB safety margin)."
            )
            logger.error(err_msg)
            return False, free_gb, err_msg

        ok_msg = (
            f"Disk space OK on drive '{drive_name}': {free_gb:.2f} GB free "
            f"(required: {required_gb:.2f} GB + {margin_gb:.2f} GB margin = {total_needed:.2f} GB)."
        )
        return True, free_gb, ok_msg

    except Exception as e:
        err_msg = f"Failed to check disk space for path '{target_path}': {e}"
        logger.error(err_msg)
        return False, 0.0, err_msg

def check_training_disk_safety(
    temp_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    required_temp_gb: float = 3.0,
    required_cache_gb: float = 3.0,
    margin_gb: float = 2.0
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates disk safety across both training temp directory and HF cache directory.
    Refuses if either drive lacks required space + 2 GB margin.
    """
    settings = get_settings()
    t_dir = temp_dir or settings.training_temp_dir
    c_dir = cache_dir or settings.hf_cache_dir

    # Ensure parent directories exist
    t_dir.mkdir(parents=True, exist_ok=True)
    c_dir.mkdir(parents=True, exist_ok=True)

    temp_safe, temp_free, temp_msg = check_disk_space(t_dir, required_gb=required_temp_gb, margin_gb=margin_gb)
    cache_safe, cache_free, cache_msg = check_disk_space(c_dir, required_gb=required_cache_gb, margin_gb=margin_gb)

    details = {
        "temp_dir": str(t_dir),
        "temp_free_gb": temp_free,
        "temp_safe": temp_safe,
        "temp_message": temp_msg,
        "cache_dir": str(c_dir),
        "cache_free_gb": cache_free,
        "cache_safe": cache_safe,
        "cache_message": cache_msg,
        "required_gb_per_drive": required_temp_gb,
        "margin_gb": margin_gb
    }

    if not temp_safe:
        return False, temp_msg, details
    if not cache_safe:
        return False, cache_msg, details

    combined_msg = f"Disk safety verified: Temp drive has {temp_free:.2f} GB free, Cache drive has {cache_free:.2f} GB free."
    return True, combined_msg, details

def get_large_file_locations(
    temp_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    models_dir: Optional[Path] = None
) -> Dict[str, str]:
    """
    Returns the designated disk locations where large files and models are stored.
    """
    settings = get_settings()
    t_dir = temp_dir or settings.training_temp_dir
    c_dir = cache_dir or settings.hf_cache_dir
    m_dir = models_dir or settings.models_dir

    return {
        "huggingface_cache": str(c_dir),
        "training_temp": str(t_dir),
        "promoted_models": str(m_dir)
    }

def setup_training_environment(
    cache_dir: Optional[Path] = None,
    temp_dir: Optional[Path] = None
) -> Dict[str, str]:
    """
    Configures environment variables so HuggingFace, PyTorch, and Python tempfile
    write to the specified fast drives instead of filling up drive C:.
    """
    settings = get_settings()
    c_dir = cache_dir or settings.hf_cache_dir
    t_dir = temp_dir or settings.training_temp_dir

    c_dir.mkdir(parents=True, exist_ok=True)
    t_dir.mkdir(parents=True, exist_ok=True)

    c_str = str(c_dir)
    t_str = str(t_dir)

    # Set Hugging Face cache paths
    os.environ["HF_HOME"] = c_str
    os.environ["TRANSFORMERS_CACHE"] = c_str
    os.environ["HF_DATASETS_CACHE"] = c_str
    os.environ["TORCH_HOME"] = c_str

    # Set temporary directories
    os.environ["TMPDIR"] = t_str
    os.environ["TEMP"] = t_str
    os.environ["TMP"] = t_str

    logger.info(f"Training environment configured: HF_HOME={c_str}, TEMP={t_str}")

    return {
        "HF_HOME": c_str,
        "TRANSFORMERS_CACHE": c_str,
        "TEMP": t_str
    }
