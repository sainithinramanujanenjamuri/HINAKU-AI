import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8")

import datetime
from backend.attachments.extractor import extract_text_from_pdf
from backend.attachments.outline import extract_outline_from_pages

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = Path("data/measure") / f"{now_str}_pdf_page_ranges.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

files = [
    "Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf",
    "Security, Ethics & Regulations in AI - Midterm Notes.pdf"
]

lines = []
lines.append("COMMAND: python scripts/measure_pdf_page_ranges.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("PDF SECTION PAGE RANGES MEASUREMENT (SAMPLE DOCUMENTS)")
lines.append("=" * 80)

for fname in files:
    fpath = Path("tests/real_samples") / fname
    if not fpath.exists():
        lines.append(f"\nERROR: File {fname} not found in tests/real_samples/")
        continue

    content = fpath.read_bytes()
    pages = extract_text_from_pdf(content)
    title, sections = extract_outline_from_pages(pages, fname)

    lines.append(f"\nDOCUMENT: {fname}")
    lines.append(f"PARSED TITLE: {title}")
    lines.append(f"TOTAL PAGES: {len(pages)}")
    lines.append(f"TOTAL SECTIONS: {len(sections)}")

    topics = [s for s in sections if not s.is_study_aid]
    study_aids = [s for s in sections if s.is_study_aid]
    u1 = [s for s in topics if "UNIT 1" in s.unit_name.upper()]
    u2 = [s for s in topics if "UNIT 2" in s.unit_name.upper()]

    lines.append(f"TOPICS IN UNIT 1: {len(u1)}")
    lines.append(f"TOPICS/SESSIONS IN UNIT 2: {len(u2)}")
    lines.append(f"STUDY AIDS: {len(study_aids)}")
    lines.append("-" * 80)
    lines.append(f"{'Order':<6}{'Type':<10}{'Pages':<12}{'Unit':<22}{'Title'}")
    lines.append("-" * 80)

    for s in sections:
        page_range_str = f"pp. {s.start_page}-{s.end_page}" if s.start_page != s.end_page else f"p. {s.start_page}"
        sec_type = "study_aid" if s.is_study_aid else s.section_type
        lines.append(f"{s.section_order:<6}{sec_type:<10}{page_range_str:<12}{s.unit_name[:20]:<22}{s.title}")

output_text = "\n".join(lines) + "\n"
output_path.write_text(output_text, encoding="utf-8")
print(f"Report written to: {output_path}")
print(output_text)

