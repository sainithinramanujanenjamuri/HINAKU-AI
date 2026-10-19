import argparse
import sys
import threading
import time
import httpx
import uvicorn
from backend.config import get_settings

def run_server(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run("backend.main:app", host=host, port=port, log_level="info")

def wait_for_server(url: str, timeout: float = 5.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with httpx.Client(timeout=1.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False

def main():
    parser = argparse.ArgumentParser(description="HINAKU Desktop Runner")
    parser.add_argument("--server-only", action="store_true", help="Run only the FastAPI backend server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    args = parser.parse_args()

    settings = get_settings()
    app_name = settings.app_name

    if args.server_only:
        run_server(args.host, args.port)
        return

    # Start FastAPI in background daemon thread
    server_thread = threading.Thread(
        target=run_server,
        args=(args.host, args.port),
        daemon=True
    )
    server_thread.start()

    url = f"http://{args.host}:{args.port}"
    if not wait_for_server(f"{url}/health"):
        print(f"Warning: Timed out waiting for server at {url}/health, attempting to open window anyway...")

    try:
        import webview
        window = webview.create_window(
            title=app_name,
            url=url,
            width=1000,
            height=750,
            min_size=(640, 500),
            background_color="#06070a"
        )
        webview.start()
    except Exception as e:
        print(f"pywebview failed to start GUI ({e}). Falling back to browser / server mode.")
        print(f"HINAKU is accessible at: {url}")
        server_thread.join()

if __name__ == "__main__":
    main()

