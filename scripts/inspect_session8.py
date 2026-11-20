import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pypdf import PdfReader
sec_pdf = ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"
reader = PdfReader(str(sec_pdf))
for idx, page in enumerate(reader.pages):
    txt = page.extract_text()
    if "Session 8" in txt or "MLSecOps" in txt:
        print(f"=== PAGE {idx+1} ===")
        print(txt)

