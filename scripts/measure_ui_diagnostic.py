import os
import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEASURE_DIR = ROOT / "data" / "measure"
MEASURE_DIR.mkdir(parents=True, exist_ok=True)

ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
out_path = MEASURE_DIR / f"{ts}_ui_diagnostic.txt"

lines = []
lines.append("=== HINAKU UI DIAGNOSTIC & VERIFICATION REPORT ===")
lines.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
lines.append("")

# 1. Check sqlite conversations count in real data/hinaku.db
db_path = ROOT / "data" / "hinaku.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM conversations")
conv_count = cur.fetchone()[0]
cur.execute("SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 5")
recent_convs = cur.fetchall()
conn.close()

lines.append(f"Real database: {db_path}")
lines.append(f"Total conversations in data/hinaku.db: {conv_count}")
lines.append("Top 5 recent conversations:")
for c in recent_convs:
    lines.append(f"  - [{c[0]}] {c[1]} (updated: {c[2]})")
lines.append("")

# 2. Check Node module import of markdown.js
lines.append("Checking ES Module imports via Node.js:")
node_cmd = [
    "node", "--input-type=module", "-e",
    "import { attachCodeBlockCopyHandlers, formatMarkdown, parseOfflineMarkdown } from './ui/js/markdown.js';"
    "console.log('markdown.js exports attachCodeBlockCopyHandlers:', typeof attachCodeBlockCopyHandlers);"
    "console.log('markdown.js exports formatMarkdown:', typeof formatMarkdown);"
]
node_res = subprocess.run(node_cmd, cwd=ROOT, capture_output=True, text=True)
lines.append(f"Command: {' '.join(node_cmd)}")
lines.append(f"Return code: {node_res.returncode}")
lines.append(f"Stdout:\n{node_res.stdout.strip()}")
if node_res.stderr.strip():
    lines.append(f"Stderr:\n{node_res.stderr.strip()}")
lines.append("")

# 3. Run pytest for UI markdown & import integrity
lines.append("Running pytest tests/ui/test_ui_markdown.py:")
pytest_cmd = [str(ROOT / "venv" / "Scripts" / "pytest.exe"), "-v", "tests/ui/test_ui_markdown.py"]
pytest_res = subprocess.run(pytest_cmd, cwd=ROOT, capture_output=True, text=True)
lines.append(f"Command: {' '.join(pytest_cmd)}")
lines.append(f"Return code: {pytest_res.returncode}")
lines.append(f"Stdout:\n{pytest_res.stdout.strip()}")
if pytest_res.stderr.strip():
    lines.append(f"Stderr:\n{pytest_res.stderr.strip()}")
lines.append("")

out_text = "\n".join(lines) + "\n"
out_path.write_text(out_text, encoding="utf-8")
print(f"Report written to: {out_path}")
print(out_text)

