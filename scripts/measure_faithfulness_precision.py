import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import datetime
from backend.attachments.extractor import extract_text_from_pdf
from backend.attachments.outline import extract_outline_from_pages
from backend.attachments.faithfulness import verify_explanation_faithfulness, extract_named_items

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = ROOT / "data" / "measure" / f"{now_str}_faithfulness_precision_report.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

lines = []
lines.append("COMMAND: python scripts/measure_faithfulness_precision.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("FAITHFULNESS CHECK PRECISION & FALSE POSITIVE EVALUATION ON REAL SAMPLES")
lines.append("=" * 80)

samples = [
    ROOT / "tests/real_samples/Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf",
    ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"
]

total_named_items_tested = 0
total_false_positives = 0

for pdf_path in samples:
    if not pdf_path.exists():
        lines.append(f"Skipping {pdf_path.name} (not found)")
        continue

    pages = extract_text_from_pdf(pdf_path.read_bytes())
    doc_title, sections = extract_outline_from_pages(pages, pdf_path.name)
    full_doc_text = "\n\n".join(p.text for p in pages)

    lines.append(f"\nDocument: {pdf_path.name}")
    lines.append(f"Title: {doc_title}")
    lines.append(f"Total Sections: {len(sections)}")

    doc_items = 0
    doc_mismatches = 0

    for sec in sections:
        sec_title = sec.title
        sec_text = sec.text
        # Use source section text itself as ground truth explanation to test precision
        # Every named item extracted from the source text MUST be found in the document (0% false positives)
        items = extract_named_items(sec_text)
        if not items:
            continue

        doc_items += len(items)
        is_faithful, missing, _ = verify_explanation_faithfulness(
            explanation_text=sec_text,
            section_text=sec_text,
            full_document_text=full_doc_text,
            sec_title=sec_title
        )
        if missing:
            doc_mismatches += len(missing)
            lines.append(f"  [MISMATCH] Section: '{sec_title}' -> Flagged: {missing}")

    false_positive_rate = (doc_mismatches / max(1, doc_items)) * 100
    total_named_items_tested += doc_items
    total_false_positives += doc_mismatches

    lines.append(f"Tested Named Items: {doc_items}")
    lines.append(f"Flagged Mismatches: {doc_mismatches}")
    lines.append(f"False-Positive Rate: {false_positive_rate:.2f}%")

overall_fp_rate = (total_false_positives / max(1, total_named_items_tested)) * 100
lines.append("\n" + "=" * 80)
lines.append(f"OVERALL SUMMARY ACROSS SAMPLES")
lines.append(f"Total Named Items Tested: {total_named_items_tested}")
lines.append(f"Total False Positives: {total_false_positives}")
lines.append(f"Overall False-Positive Rate: {overall_fp_rate:.2f}%")
lines.append("=" * 80)

out_text = "\n".join(lines) + "\n"
output_path.write_text(out_text, encoding="utf-8")
print(f"Report written to: {output_path}")
print(out_text)

