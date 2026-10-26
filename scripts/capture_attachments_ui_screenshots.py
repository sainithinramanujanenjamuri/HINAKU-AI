import os
import sys
import subprocess
import time
from pathlib import Path
from multiprocessing import Process
import uvicorn

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SCREENSHOT_DIR = ROOT_DIR / "docs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def run_server():
    os.environ["HINAKU_UI_DEMO"] = "1"
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8009, log_level="warning")

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
        widths = [(1280, 820), (960, 780), (720, 700)]
        for w, h in widths:
            out_file = SCREENSHOT_DIR / f"phase2_attachments_{w}px.png"
            print(f"Capturing Attachments UI at {w}x{h} -> {out_file}")
            take_screenshot(f"http://127.0.0.1:8009/", out_file, w, h)

        print("Phase 2 Attachments UI screenshots captured successfully.")
    finally:
        p.terminate()
        p.join()

if __name__ == "__main__":
    main()
