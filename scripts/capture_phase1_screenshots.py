import asyncio
import os
import sys
import subprocess
import time
from pathlib import Path

# Ensure ROOT_DIR in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import uvicorn
from multiprocessing import Process

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SCREENSHOT_DIR = ROOT_DIR / "docs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def run_server():
    os.environ["HINAKU_UI_DEMO"] = "1"
    sys.path.insert(0, str(ROOT_DIR))
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")

def take_screenshot(url: str, output_path: Path, width: int, height: int):
    cmd = [
        EDGE_EXE,
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={width},{height}",
        f"--screenshot={str(output_path.resolve())}",
        url
    ]
    subprocess.run(cmd, check=True)

def main():
    p = Process(target=run_server)
    p.start()
    time.sleep(3)

    try:
        widths = [1280, 960, 720]
        # Dark theme
        for w in widths:
            out_file = SCREENSHOT_DIR / f"phase1_shell_dark_{w}px.png"
            print(f"Capturing Dark Theme at {w}px -> {out_file}")
            take_screenshot(f"http://127.0.0.1:8001/?theme=dark", out_file, w, 800)

        # Light theme
        for w in widths:
            out_file = SCREENSHOT_DIR / f"phase1_shell_light_{w}px.png"
            print(f"Capturing Light Theme at {w}px -> {out_file}")
            # inject light mode via URL param or script
            take_screenshot(f"http://127.0.0.1:8001/?theme=light", out_file, w, 800)

        print("Screenshots captured successfully.")
    finally:
        p.terminate()
        p.join()

if __name__ == "__main__":
    main()
