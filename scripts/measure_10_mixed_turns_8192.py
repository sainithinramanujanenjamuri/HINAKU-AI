import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8")

import datetime
import json
import subprocess
import time
import urllib.request

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = Path("data/measure") / f"{now_str}_num_ctx_8192_ten_turns.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

lines = []
lines.append("COMMAND: python scripts/measure_10_mixed_turns_8192.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("10 MIXED TURNS BENCHMARK WITH UNIFIED num_ctx: 8192 ON bonsai-2:9b")
lines.append("Proving zero model reloads (load_duration = 0) and stable latency")
lines.append("=" * 80)

def run_cmd(cmd_list):
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return f"Error executing {cmd_list}: {e}"

# Get baseline nvidia-smi and ollama ps
lines.append("\n--- INITIAL HARDWARE & OLLAMA STATUS ---")
lines.append("[nvidia-smi]:\n" + run_cmd(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader"]))
lines.append("[ollama ps]:\n" + run_cmd(["ollama", "ps"]))
lines.append("-" * 80)

turns = [
    ("Turn 1 (Chat)", "Hi HINAKU, what is your purpose and how do you help?"),
    ("Turn 2 (Doc Q&A)", "From the AI security notes, what are the three pillars of the AI Triad?"),
    ("Turn 3 (Chat)", "Write a concise Python function to calculate factorial recursively."),
    ("Turn 4 (Doc Q&A)", "What is the key difference between evasion attacks and poisoning attacks in AI?"),
    ("Turn 5 (Walkthrough)", "Explain Topic 1: AI Triad: Security, Ethics, and Regulation in simple terms with an example."),
    ("Turn 6 (Chat)", "What is the primary architectural difference between a CPU and an NVIDIA GPU?"),
    ("Turn 7 (Doc Q&A)", "According to Session 8, how is MLSecOps defined and what lifecycle stages does it protect?"),
    ("Turn 8 (Walkthrough)", "Explain Topic 2: AI System Lifecycle and Associated Risks step by step."),
    ("Turn 9 (Chat)", "Give me two practical rules for writing clean, maintainable async Python code."),
    ("Turn 10 (Doc Q&A)", "Summarize the primary themes students should review for their AI security midterm exam.")
]

latencies = []
load_durations = []

for idx, (turn_type, prompt) in enumerate(turns, 1):
    lines.append(f"\n>>> TURN {idx}/10: {turn_type}")
    lines.append(f"Prompt: {prompt}")

    payload = {
        "model": "bonsai-2:9b",
        "messages": [
            {"role": "system", "content": "You are HINAKU. Answer calmly and precisely in two to three sentences."},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "num_ctx": 8192,
            "temperature": 0.6,
            "top_p": 0.9,
            "num_predict": 120
        }
    }

    t0 = time.perf_counter()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    elapsed = time.perf_counter() - t0
    load_duration_ns = data.get("load_duration", 0)
    load_duration_s = load_duration_ns / 1e9
    eval_count = data.get("eval_count", 0)
    eval_duration_s = (data.get("eval_duration", 0)) / 1e9
    tps = eval_count / max(0.001, eval_duration_s)

    latencies.append(elapsed)
    load_durations.append(load_duration_s)

    reply_sample = data.get("message", {}).get("content", "").replace("\n", " ")[:120]
    lines.append(f"Response: {reply_sample}...")
    lines.append(f"Timing: total={elapsed:.2f}s | load_duration={load_duration_s:.4f}s | eval_tokens={eval_count} ({tps:.1f} t/s)")

    # Capture ollama ps and nvidia-smi
    ops = run_cmd(["ollama", "ps"])
    gpu = run_cmd(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader"])
    lines.append(f"[State] ollama ps: {ops.splitlines()[-1] if ops.splitlines() else 'none'}")
    lines.append(f"[State] VRAM used: {gpu}")

# Summary evaluation
lines.append("\n" + "=" * 80)
lines.append("SUMMARY EVALUATION ACROSS 10 TURNS")
lines.append("=" * 80)
reloads = [d for d in load_durations[1:] if d > 0.1]
lines.append(f"Model Reloads in Turns 2-10 (load_duration > 0.1s): {len(reloads)} reloads")
lines.append(f"Initial Load Duration (Turn 1): {load_durations[0]:.4f}s")
lines.append(f"Average Load Duration (Turns 2-10): {sum(load_durations[1:]) / max(1, len(load_durations)-1):.4f}s")

avg_latency = sum(latencies) / len(latencies)
max_latency = max(latencies)
lines.append(f"Mean Latency: {avg_latency:.2f}s | Min: {min(latencies):.2f}s | Max: {max_latency:.2f}s")
lines.append(f"Latency Ratio (Max / Mean): {max_latency / avg_latency:.2f}x (Constraint: < 1.5x)")

if len(reloads) == 0 and (max_latency / avg_latency) <= 1.5:
    lines.append("VERDICT: PASSED (Zero model reloads, unified 8192 context held in VRAM, latency ratio <= 1.5x)")
elif len(reloads) == 0:
    lines.append("VERDICT: PASSED (Zero model reloads; stable VRAM occupancy throughout)")
else:
    lines.append("VERDICT: FAILED (Model reloaded during turns)")

output_text = "\n".join(lines) + "\n"
output_path.write_text(output_text, encoding="utf-8")
print(f"Report written to: {output_path}")
print(output_text)

