import logging
import subprocess
from typing import Dict, Any, Optional, Tuple
from backend.config import get_settings

logger = logging.getLogger(__name__)

def detect_gpu_vram_gb() -> Tuple[str, float]:
    """
    Detects GPU name and total VRAM in GB.
    Tries torch.cuda first, falls back to nvidia-smi.
    """
    # 1. Try torch.cuda
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = round(vram_bytes / (1024 ** 3), 2)
            return device_name, vram_gb
    except Exception:
        pass

    # 2. Try nvidia-smi CLI
    try:
        cmd = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            line = res.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            name = parts[0]
            mem_mb = float(parts[1])
            vram_gb = round(mem_mb / 1024, 2)
            return name, vram_gb
    except Exception:
        pass

    return "No compatible NVIDIA GPU detected", 0.0

def check_power_and_battery() -> Dict[str, Any]:
    """
    Checks if device is plugged into AC power.
    Warns if on battery power.
    """
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is not None:
            plugged = battery.power_plugged
            percent = battery.percent
            warning = None
            if not plugged:
                warning = "Laptop is on battery power. Connect to AC power and place on a hard flat surface before training."
            return {"battery_percent": percent, "plugged_in": plugged, "warning": warning}
    except Exception:
        pass
    return {"battery_percent": None, "plugged_in": True, "warning": None}

def run_vram_preflight(min_gb: Optional[float] = None) -> Dict[str, Any]:
    """
    VRAM preflight: requires at least min_vram_gb (default 5.5 GB for RTX 4050 6GB).
    Refuses if GPU VRAM is insufficient with a clear explanatory message.
    """
    settings = get_settings()
    required = min_gb if min_gb is not None else settings.training_min_vram_gb
    device_name, vram_gb = detect_gpu_vram_gb()
    power_info = check_power_and_battery()

    passed = (vram_gb >= required)
    if passed:
        message = f"VRAM Preflight passed: {device_name} with {vram_gb} GB VRAM (required: {required} GB)."
    else:
        message = (
            f"VRAM Preflight refused: Found {device_name} ({vram_gb} GB VRAM). "
            f"A GPU with at least {required} GB VRAM is required to run 4-bit QLoRA locally. "
            f"You can export the dataset bundle to rent a cloud GPU and import the resulting adapter."
        )

    return {
        "passed": passed,
        "device_name": device_name,
        "gpu_name": device_name,
        "detected_vram_gb": vram_gb,
        "vram_gb": vram_gb,
        "min_required_gb": required,
        "message": message,
        "power_info": power_info
    }
