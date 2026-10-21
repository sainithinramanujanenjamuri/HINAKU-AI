import os
os.environ["HINAKU_USE_REAL_DATA"] = "1"

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Optional
import httpx
import uvicorn
from backend.config import get_settings

def run_server(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run("backend.main:app", host=host, port=port, log_level="info")

def wait_for_server(url: str, timeout: float = 5.0) -> bool:
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

def create_tray_image():
    """Generate a 64x64 icon for the system tray: minimal dark circle with violet core."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Outer dark ring
        draw.ellipse((4, 4, 60, 60), fill=(10, 11, 16, 255), outline=(99, 102, 241, 200), width=3)
        # Inner violet glow core
        draw.ellipse((20, 20, 44, 44), fill=(99, 102, 241, 240))
        return img
    except Exception:
        return None

def setup_global_hotkey(toggle_callback, stop_event: threading.Event):
    """
    Register a global hotkey on Windows (Ctrl+Shift+Space) using ctypes.
    """
    if sys.platform != "win32":
        return

    import ctypes
    from ctypes import wintypes

    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_ALT = 0x0001
    VK_SPACE = 0x20
    HOTKEY_ID = 101

    user32 = ctypes.windll.user32

    # Register Ctrl+Shift+Space, fallback to Alt+Shift+H
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_SPACE):
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT | MOD_SHIFT, 0x48)

    msg = wintypes.MSG()
    try:
        while not stop_event.is_set():
            # PeekMessage to allow non-blocking check
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1): # PM_REMOVE = 1
                if msg.message == 0x0312: # WM_HOTKEY
                    toggle_callback()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)

def main():
    parser = argparse.ArgumentParser(description="HINAKU Desktop Runner")
    parser.add_argument("--server-only", action="store_true", help="Run only the FastAPI backend server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--no-tray", action="store_true", help="Disable system tray icon")
    parser.add_argument("--no-hotkey", action="store_true", help="Disable global hotkey")
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

    window = None
    window_visible = True
    stop_event = threading.Event()
    tray_icon = None

    def toggle_window():
        nonlocal window_visible
        if not window:
            return
        try:
            if window_visible:
                window.hide()
                window_visible = False
            else:
                window.show()
                window.restore()
                window_visible = True
        except Exception as e:
            print(f"Window toggle notice: {e}")

    def show_window():
        nonlocal window_visible
        if window:
            try:
                window.show()
                window.restore()
                window_visible = True
            except Exception:
                pass

    def hide_window():
        nonlocal window_visible
        if window:
            try:
                window.hide()
                window_visible = False
            except Exception:
                pass

    def on_exit():
        stop_event.set()
        if tray_icon:
            try:
                tray_icon.stop()
            except Exception:
                pass
        if window:
            try:
                window.destroy()
            except Exception:
                pass
        sys.exit(0)

    # Start global hotkey listener
    if not args.no_hotkey and sys.platform == "win32":
        hotkey_thread = threading.Thread(
            target=setup_global_hotkey,
            args=(toggle_window, stop_event),
            daemon=True
        )
        hotkey_thread.start()

    # Start system tray icon
    if not args.no_tray:
        try:
            import pystray
            from pystray import MenuItem as item

            icon_img = create_tray_image()
            if icon_img:
                menu = (
                    item("Show HINAKU", lambda: show_window(), default=True),
                    item("Hide HINAKU", lambda: hide_window()),
                    item("Exit", lambda: on_exit())
                )
                tray_icon = pystray.Icon("HINAKU", icon_img, "HINAKU", menu)
                tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
                tray_thread.start()
        except Exception as e:
            print(f"System tray initialization skipped ({e})")

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
    finally:
        on_exit()

if __name__ == "__main__":
    main()
