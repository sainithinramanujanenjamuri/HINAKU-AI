import ctypes
import logging
import sys
from typing import Tuple, Dict, Any
from backend.training.preflight import check_power_and_battery

logger = logging.getLogger(__name__)

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint)
    ]

def get_system_idle_seconds() -> float:
    """
    Returns the number of seconds since the last user mouse/keyboard input on Windows.
    Falls back gracefully on non-Windows platforms.
    """
    if sys.platform != "win32":
        return 300.0  # Default to idle on non-Windows platforms

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = kernel32.GetTickCount() - lii.dwTime
            return max(0.0, millis / 1000.0)
    except Exception as e:
        logger.debug(f"Could not query GetLastInputInfo: {e}")

    return 300.0

def is_user_active(idle_threshold_seconds: float = 120.0) -> bool:
    """Returns True if user interacted with laptop within idle_threshold_seconds."""
    idle = get_system_idle_seconds()
    return idle < idle_threshold_seconds

def check_training_activity_and_power(
    idle_threshold_seconds: float = 120.0
) -> Dict[str, Any]:
    """
    Evaluates whether local background training should pause due to active laptop use
    or running on battery power.
    """
    idle_sec = round(get_system_idle_seconds(), 1)
    user_active = (idle_sec < idle_threshold_seconds)
    power_info = check_power_and_battery()

    pause_reasons = []
    if user_active:
        pause_reasons.append(
            f"User is actively using the laptop (idle for {idle_sec}s, threshold is {idle_threshold_seconds}s)"
        )
    if power_info.get("plugged_in") is False:
        pause_reasons.append(
            "Laptop is running on battery power. Training paused to avoid thermal throttling and battery drain."
        )

    should_pause = len(pause_reasons) > 0
    message = "; ".join(pause_reasons) if should_pause else "Laptop is idle and on AC power. Safe to train."

    return {
        "should_pause": should_pause,
        "user_active": user_active,
        "idle_seconds": idle_sec,
        "idle_threshold_seconds": idle_threshold_seconds,
        "power_info": power_info,
        "message": message
    }
