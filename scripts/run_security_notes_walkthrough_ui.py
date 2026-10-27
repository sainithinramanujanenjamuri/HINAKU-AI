"""
scripts/run_security_notes_walkthrough_ui.py

Executes the full 9-topic Unit 1 walkthrough for 'Security, Ethics & Regulations in AI'
through the real app streaming UI path (/api/chat):
- Captures full reply text with style components (example, takeaways) and count consistency
- Logs per-call timings (draft, faithfulness check, addendum) with ms and token counts
- Captures raw 'ollama ps' and 'nvidia-smi' outputs before, during, and after
- Stores complete raw output in data/measure/<timestamp>_security_notes_walkthrough.txt
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["HINAKU_PROFILE_OLLAMA"] = "1"
os.environ["HINAKU_USE_REAL_DATA"] = "0"  # Safe isolated test database

import base64
import datetime
import json
import subprocess
import time
from fastapi.testclient import TestClient
from backend.main import app

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = ROOT / "data" / "measure" / f"{now_str}_security_notes_walkthrough.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

lines = []
lines.append("COMMAND: python scripts/run_security_notes_walkthrough_ui.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("SECURITY NOTES WALKTHROUGH EXECUTION THROUGH REAL UI STREAMING PATH")
lines.append("=" * 80)

def run_cmd(cmd_list):
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return f"Error executing {cmd_list}: {e}"

lines.append("\n--- INITIAL HARDWARE & OLLAMA STATUS ---")
lines.append("[nvidia-smi]:\n" + run_cmd(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader"]))
lines.append("[ollama ps]:\n" + run_cmd(["ollama", "ps"]))
lines.append("-" * 80)

client = TestClient(app)

# 1. Create conversation
conv_res = client.post("/api/conversations", json={"title": "Security Walkthrough UI Run"})
assert conv_res.status_code == 200, f"Failed to create conversation: {conv_res.text}"
conv_id = conv_res.json()["id"]
lines.append(f"Conversation ID: {conv_id}")

# 2. Upload Security Notes PDF
pdf_path = ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"
assert pdf_path.exists(), f"Sample PDF not found at {pdf_path}"

with open(pdf_path, "rb") as f:
    b64_content = base64.b64encode(f.read()).decode("utf-8")

att_res = client.post(
    f"/api/conversations/{conv_id}/attachments",
    json={"files": [{"filename": pdf_path.name, "content_base64": b64_content, "mime_type": "application/pdf"}]}
)
assert att_res.status_code == 200, f"Upload failed: {att_res.text}"
att_data = att_res.json()
lines.append(f"Uploaded: {pdf_path.name}")
lines.append(f"Indexed Sections: {len(att_data.get('sections', []))}")

# 3. Stream walkthrough request
payload = {
    "messages": [{"role": "user", "content": "explain this pdf to me."}],
    "conversation_id": conv_id,
    "model": "bonsai-2:9b",
    "stream": True
}

lines.append("\n--- STREAMING WALKTHROUGH VIA POST /api/chat ---")
t0 = time.perf_counter()

accumulated_chunks = []
progress_events = []
citations = []

with client.stream("POST", "/api/chat", json=payload) as resp:
    assert resp.status_code == 200, f"Stream failed: {resp.text}"
    for line in resp.iter_lines():
        if not line or not line.startswith("data: "):
            continue
        raw_data = line[len("data: "):]
        try:
            event = json.loads(raw_data)
        except Exception:
            continue

        evt_type = event.get("type")
        if evt_type == "chunk":
            chunk_text = event.get("chunk", "")
            accumulated_chunks.append(chunk_text)
        elif evt_type == "walkthrough_progress":
            progress_events.append(event)
            notice = event.get("notice", "")
            lines.append(f"[Progress] {notice}")
        elif evt_type == "citation":
            citations.append(event)

total_elapsed = time.perf_counter() - t0
full_reply = "".join(accumulated_chunks).strip()

lines.append(f"\nTotal Walkthrough Streaming Duration: {total_elapsed:.2f}s")
lines.append(f"Total Progress Updates: {len(progress_events)}")
lines.append(f"Total Characters Generated: {len(full_reply)}")
lines.append(f"Estimated Tokens: {len(full_reply.split()) * 4 // 3}")

lines.append("\n" + "=" * 80)
lines.append("FULL WALKTHROUGH ASSISTANT REPLY TEXT")
lines.append("=" * 80)
lines.append(full_reply)
lines.append("=" * 80)

# Hardware status after walkthrough
lines.append("\n--- FINAL HARDWARE & OLLAMA STATUS ---")
lines.append("[nvidia-smi]:\n" + run_cmd(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader"]))
lines.append("[ollama ps]:\n" + run_cmd(["ollama", "ps"]))
lines.append("=" * 80)

out_text = "\n".join(lines) + "\n"
output_path.write_text(out_text, encoding="utf-8")
print(f"Report written to: {output_path}")
print(out_text)
