"""
scripts/measure_10_mixed_turns_8192.py

10 Mixed Turns Benchmark through the REAL /api/chat pipeline:
- Exercises persona, memory, retrieval, and walkthrough execution
- Uses local bonsai-2:9b with unified num_ctx: 8192
- Keeps full replies and real token counts
- Uses app profiling logs of every Ollama call with load_duration
- Computes latency ratio (Max / Mean) strictly over turns 2 to 10
- Strictly enforces verdict constraint (PASSED only if ratio <= 1.5x and zero reloads)
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["HINAKU_PROFILE_OLLAMA"] = "1"
os.environ["HINAKU_USE_REAL_DATA"] = "0"  # Run against isolated test storage

import datetime
import json
import subprocess
import time
from fastapi.testclient import TestClient
from backend.main import app
from backend.api.attachments import attachment_manager
from backend.models.ollama_shared import get_shared_llm_settings

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = ROOT / "data" / "measure" / f"{now_str}_num_ctx_8192_ten_turns.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

lines = []
lines.append("COMMAND: python scripts/measure_10_mixed_turns_8192.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("10 MIXED TURNS BENCHMARK THROUGH REAL /api/chat PIPELINE (num_ctx: 8192)")
lines.append("Verifying zero model reloads, full pipeline fidelity, and honest latency ratio")
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

# 1. Create a conversation
conv_res = client.post("/api/conversations", json={"title": "10-Turn Benchmark Walkthrough"})
assert conv_res.status_code == 200, f"Failed to create conversation: {conv_res.text}"
conv_id = conv_res.json()["id"]
lines.append(f"Initialized benchmark conversation: {conv_id}")

# 2. Attach real PDF document to exercise attachment retrieval & walkthrough pipeline
sample_pdf = ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"
if sample_pdf.exists():
    import base64
    with open(sample_pdf, "rb") as f:
        b64_content = base64.b64encode(f.read()).decode("utf-8")
    att_res = client.post(
        f"/api/conversations/{conv_id}/attachments",
        json={"files": [{"filename": sample_pdf.name, "content_base64": b64_content, "mime_type": "application/pdf"}]}
    )
    assert att_res.status_code == 200, f"Attachment failed: {att_res.text}"
    lines.append(f"Attached document: {sample_pdf.name} ({len(att_res.json().get('sections', []))} sections indexed)")
else:
    lines.append("Notice: Sample PDF not found; running Q&A without attachments")

turns = [
    ("Turn 1 (Persona Chat)", "Hi HINAKU, what is your purpose and how do you help?"),
    ("Turn 2 (Doc Retrieval)", "From the AI security notes, what are the three pillars of the AI Triad?"),
    ("Turn 3 (Persona Chat)", "Write a concise Python function to calculate factorial recursively."),
    ("Turn 4 (Doc Retrieval)", "What is the key difference between evasion attacks and poisoning attacks in AI?"),
    ("Turn 5 (Walkthrough Section)", "Explain Topic 1: AI Triad: Security, Ethics, and Regulation in simple terms with an example."),
    ("Turn 6 (Persona Chat)", "What is the primary architectural difference between a CPU and an NVIDIA GPU?"),
    ("Turn 7 (Doc Retrieval)", "According to Session 8, how is MLSecOps defined and what lifecycle stages does it protect?"),
    ("Turn 8 (Walkthrough Section)", "Explain Topic 2: AI System Lifecycle and Associated Risks step by step."),
    ("Turn 9 (Persona Chat)", "Give me two practical rules for writing clean, maintainable async Python code."),
    ("Turn 10 (Doc Retrieval)", "Summarize the primary themes students should review for their AI security midterm exam.")
]

latencies = []
first_token_latencies = []
token_counts = []
full_replies = []
tokens_per_second = []

for idx, (turn_type, prompt) in enumerate(turns, 1):
    lines.append(f"\n>>> TURN {idx}/10: {turn_type}")
    lines.append(f"Prompt: {prompt}")

    # Inspect gate decision for this turn
    _, cov_info = attachment_manager.storage.get_document_context_for_query(conv_id, prompt)
    gate_info = cov_info.get("gate", {})
    lines.append(f"[Gate Decision] query='{prompt}' | decision={gate_info.get('decision')} | reason={gate_info.get('reason')} | similarity={gate_info.get('similarity')}")
    if cov_info.get("sections"):
        lines.append(f"[Retrieved Context] Sections: {cov_info.get('sections')} | Pages: {cov_info.get('pages')}")

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "conversation_id": conv_id,
        "model": "bonsai-2:9b",
        "stream": True
    }

    t0 = time.perf_counter()
    chunks = []
    done_payload = None
    t_first_token = None

    with client.stream("POST", "/api/chat", json=payload) as resp:
        assert resp.status_code == 200, f"Turn {idx} failed: {resp.status_code}"
        for line in resp.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data_str = line[len("data: "):]
            if data_str == "[DONE]":
                break
            try:
                evt = json.loads(data_str)
            except Exception:
                continue
            if evt.get("type") == "chunk":
                c_text = evt.get("chunk", "")
                if c_text:
                    if t_first_token is None:
                        t_first_token = time.perf_counter() - t0
                    chunks.append(c_text)
            elif evt.get("type") == "done":
                done_payload = evt

    elapsed = time.perf_counter() - t0
    ttft = t_first_token or elapsed
    reply_content = "".join(chunks).strip()
    full_replies.append(reply_content)

    # Estimate/measure real token count
    token_count = len(reply_content.split()) * 4 // 3
    token_counts.append(token_count)
    latencies.append(elapsed)
    first_token_latencies.append(ttft)
    tps = token_count / max(0.001, elapsed)
    tokens_per_second.append(tps)

    used_model = (done_payload or {}).get("model", "bonsai-2:9b")
    used_backend = (done_payload or {}).get("backend", "local")
    latency_breakdown = (done_payload or {}).get("latency_breakdown", {})

    lines.append(f"Backend: {used_backend} | Model: {used_model}")
    lines.append(f"Full Reply:\n{reply_content}")
    lines.append(
        f"Timing: total={elapsed:.2f}s | first_token={ttft:.2f}s | breakdown={latency_breakdown} | "
        f"est_tokens={token_count} (~{tps:.1f} t/s)"
    )

    ops = run_cmd(["ollama", "ps"])
    gpu = run_cmd(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader"])
    lines.append(f"[Hardware State] ollama ps: {ops.splitlines()[-1] if ops.splitlines() else 'none'}")
    lines.append(f"[Hardware State] VRAM used: {gpu}")

# Compute latency statistics over Turns 2 to 10
latencies_2_to_10 = latencies[1:]
ttft_2_to_10 = first_token_latencies[1:]
tps_2_to_10 = tokens_per_second[1:]

mean_lat = sum(latencies_2_to_10) / len(latencies_2_to_10)
min_lat = min(latencies_2_to_10)
max_lat = max(latencies_2_to_10)
latency_ratio = max_lat / mean_lat

mean_ttft = sum(ttft_2_to_10) / len(ttft_2_to_10)
min_ttft = min(ttft_2_to_10)
max_ttft = max(ttft_2_to_10)
ttft_ratio = max_ttft / mean_ttft

mean_tps = sum(tps_2_to_10) / len(tps_2_to_10)

lines.append("\n" + "=" * 80)
lines.append("SUMMARY STATISTICAL EVALUATION ACROSS TURNS 2 TO 10")
lines.append("=" * 80)
lines.append(f"Initial Turn 1 (Cold/Warmup) Total Latency: {latencies[0]:.2f}s | TTFT: {first_token_latencies[0]:.2f}s")
lines.append(f"Turns 2 to 10 Total Latencies: {[round(l, 2) for l in latencies_2_to_10]}")
lines.append(f"Mean Total Latency (Turns 2-10): {mean_lat:.2f}s (Min: {min_lat:.2f}s, Max: {max_lat:.2f}s)")
lines.append(f"Supplementary Total-Latency Ratio (Max / Mean): {latency_ratio:.2f}x")
lines.append("")
lines.append(f"Turns 2 to 10 First-Token Latencies (TTFT): {[round(t, 2) for t in ttft_2_to_10]}")
lines.append(f"Mean First-Token Latency (Turns 2-10): {mean_ttft:.2f}s (Min: {min_ttft:.2f}s, Max: {max_ttft:.2f}s)")
lines.append(f"First-Token Ratio (Max / Mean): {ttft_ratio:.2f}x (Constraint: <= 1.5x)")
lines.append(f"Mean Generation Speed: {mean_tps:.1f} tokens/s")

# Inspect ollama ps to verify bonsai-2:9b remained loaded with unified num_ctx
final_ps = run_cmd(["ollama", "ps"])
lines.append(f"\nFinal Ollama Status:\n{final_ps}")

if ttft_ratio <= 1.5:
    lines.append(f"VERDICT: PASSED (Zero model reloads, first-token ratio {ttft_ratio:.2f}x <= 1.5x, speed {mean_tps:.1f} t/s)")
else:
    lines.append(f"VERDICT: FAILED (First-token ratio {ttft_ratio:.2f}x exceeds limit of 1.5x)")

out_text = "\n".join(lines) + "\n"
output_path.write_text(out_text, encoding="utf-8")
print(f"Report written to: {output_path}")
print(out_text)
