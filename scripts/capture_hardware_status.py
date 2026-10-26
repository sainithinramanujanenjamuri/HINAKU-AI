import subprocess
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = ROOT / "data" / "measure" / f"{timestamp}_hardware_status.txt"
    lines = []
    
    lines.append(f"COMMAND: ollama ps && nvidia-smi")
    lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}\n")
    
    lines.append("=== ollama ps ===")
    ps_res = subprocess.run(["ollama", "ps"], capture_output=True, text=True)
    lines.append(ps_res.stdout.strip())
    
    lines.append("\n=== nvidia-smi ===")
    smi_res = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
    lines.append(smi_res.stdout.strip())
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Captured hardware status to {out_path}")
    print("\n".join(lines))

if __name__ == "__main__":
    main()

