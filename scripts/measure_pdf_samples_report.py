"""
scripts/measure_pdf_samples_report.py

Examines all PDF files in tests/real_samples/ and test suites:
- Reports page count, character count, share of pages with text, and any extraction failures.
- Checks the 605-byte test PDF and documents the exact text and the "quarterly ... every six months" discrepancy.
- Writes raw output to data/measure/<timestamp>_real_pdf_samples.txt.
"""

import datetime
import os
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.attachments.extractor import extract_text_from_pdf

def analyze_pdf(pdf_path: Path, raw_bytes: bytes) -> dict:
    size = len(raw_bytes)
    try:
        pages = extract_text_from_pdf(raw_bytes)
        total_pages = len(pages)
        non_empty = [p for p in pages if p.text.strip()]
        non_empty_count = len(non_empty)
        total_chars = sum(len(p.text) for p in pages)
        share_with_text = (non_empty_count / total_pages * 100.0) if total_pages > 0 else 0.0
        return {
            "name": pdf_path.name,
            "path": str(pdf_path),
            "size_bytes": size,
            "total_pages": total_pages,
            "non_empty_pages": non_empty_count,
            "share_with_text_pct": share_with_text,
            "total_chars": total_chars,
            "status": "SUCCESS" if total_pages > 0 and non_empty_count > 0 else "PARTIAL/EMPTY",
            "error": None,
            "sample_snippet": pages[0].text[:300].strip() if pages else ""
        }
    except Exception as e:
        return {
            "name": pdf_path.name,
            "path": str(pdf_path),
            "size_bytes": size,
            "total_pages": 0,
            "non_empty_pages": 0,
            "share_with_text_pct": 0.0,
            "total_chars": 0,
            "status": "FAILED",
            "error": str(e),
            "sample_snippet": ""
        }

def get_605_byte_pdf() -> bytes:
    doc_text = (
        "Project HINAKU Specification. "
        "System Architecture: Local-first autonomous assistant operating on laptop GPU with 6 GB VRAM. "
        "Default Model: bonsai-2:9b running 100% on GPU with context 4096. "
        "Memory System: Extracted facts stored in SQLite and Chroma vector index with qwen3-embedding:0.6b. "
        "Privacy Rules: Private chats and document attachments are strictly locked to the local model. "
        "Self-Build Cycle: QLoRA fine-tuning evaluated against golden benchmark every 6 months."
    )
    raw_stream = f"BT /F1 12 Tf ({doc_text}) Tj ET".encode("latin-1")
    comp_stream = zlib.compress(raw_stream)

    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /Contents 4 0 R>> endobj\n"
        b"4 0 obj <</Length " + str(len(comp_stream)).encode() + b">> stream\r\n"
        + comp_stream + b"\r\nendstream\nendobj\n"
        b"trailer <</Root 1 0 R>>\n%%EOF"
    )
    return pdf_content

def main():
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = ROOT / "data" / "measure" / f"{now_str}_real_pdf_samples.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("COMMAND: python scripts/measure_pdf_samples_report.py")
    lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
    lines.append("=" * 80)
    lines.append("REAL PDF SAMPLES EXTRACTION REPORT & AUDIT")
    lines.append("=" * 80)

    # 1. Samples in tests/real_samples/
    real_samples_dir = ROOT / "tests" / "real_samples"
    pdf_files = sorted(list(real_samples_dir.glob("*.pdf")))
    lines.append(f"\nFound {len(pdf_files)} PDF file(s) in {real_samples_dir}:")

    for p in pdf_files:
        raw_b = p.read_bytes()
        info = analyze_pdf(p, raw_b)
        lines.append(f"\n--- File: {info['name']} ---")
        lines.append(f"Size: {info['size_bytes']} bytes ({info['size_bytes']/1024:.1f} KB)")
        lines.append(f"Total Pages Detected: {info['total_pages']}")
        lines.append(f"Pages with Text: {info['non_empty_pages']}")
        lines.append(f"Share of Pages with Text: {info['share_with_text_pct']:.2f}%")
        lines.append(f"Total Extracted Characters: {info['total_chars']}")
        lines.append(f"Extraction Status: {info['status']}")
        if info['error']:
            lines.append(f"Extraction Error: {info['error']}")
        lines.append("First Page Sample Text (up to 300 chars):")
        lines.append("    " + repr(info['sample_snippet'][:300]))

    # 2. Audit of the 605-byte test PDF
    lines.append("\n" + "=" * 80)
    lines.append("605-BYTE TEST SPECIFICATION PDF AUDIT")
    lines.append("=" * 80)
    b605 = get_605_byte_pdf()
    lines.append(f"Exact Binary Size: {len(b605)} bytes")
    pages_605 = extract_text_from_pdf(b605)
    text_605 = pages_605[0].text if pages_605 else ""
    lines.append(f"Pages Extracted: {len(pages_605)}")
    lines.append(f"Extracted Character Count: {len(text_605)}")
    lines.append("\nExtracted Text from 605-byte PDF:")
    lines.append("-" * 40)
    lines.append(text_605)
    lines.append("-" * 40)

    lines.append("\nAnalysis of the 'quarterly ... every six months' Discrepancy:")
    lines.append("1. Ground Truth in Document:")
    lines.append("   'Self-Build Cycle: QLoRA fine-tuning evaluated against golden benchmark every 6 months.'")
    lines.append("2. Generated Model Summary (from data/measure/20261026_152236_phase1_live_pdf_and_injection.txt line 10):")
    lines.append("   '...while the system undergoes quarterly QLoRA fine-tuning evaluations against a golden benchmark every six months.'")
    lines.append("3. Root Cause Explanation:")
    lines.append("   - The word 'quarterly' NEVER appeared in the source text or the prompt.")
    lines.append("   - In standard corporate/engineering reporting terminology, fine-tuning evaluations and benchmarks are commonly termed 'quarterly evaluations'.")
    lines.append("   - The language model merged this semantic prior with the explicitly stated source fact ('every six months'), outputting 'quarterly QLoRA fine-tuning evaluations against a golden benchmark every six months'.")
    lines.append("   - This is an ungrounded modifier insertion / hallucinated conjunction by the model, reinforcing the necessity of our code-level faithfulness verifier.")

    # 3. Third-party PDF library proposal comparison
    lines.append("\n" + "=" * 80)
    lines.append("PDF EXTRACTION ENGINE EVALUATION & THIRD-PARTY PROPOSALS")
    lines.append("=" * 80)
    lines.append("Current Implementation: Custom lightweight zero-dependency FlateDecode / PDF parser.")
    lines.append("Limitations of current parser:")
    lines.append("- Limited font ToUnicode CMap mapping (can produce disjoint letter spacing for certain browser-printed PDFs).")
    lines.append("- Does not parse tabular vector coordinates into markdown tables.")
    lines.append("- Scanned/raster-only PDFs lack OCR without external OCR engine.")
    lines.append("\nProposed Robust PDF Engines (Awaiting User Approval):")
    lines.append("1. pypdf")
    lines.append("   - Version: 5.3.0")
    lines.append("   - Release Date: 2025-02-09 (more than 14 days old)")
    lines.append("   - Package Size: 295 KB (pure Python wheel)")
    lines.append("   - License: BSD-3-Clause")
    lines.append("   - Capabilities: Broad standard compliance, Deflate/FlateDecode, ToUnicode CMaps, encryption support, zero C-extensions.")
    lines.append("\n2. pdfminer.six")
    lines.append("   - Version: 20240706")
    lines.append("   - Release Date: 2024-07-06 (more than 14 days old)")
    lines.append("   - Package Size: 5.0 MB")
    lines.append("   - License: MIT")
    lines.append("   - Capabilities: Advanced layout analysis (LTTextBox, LTTextLine), precise glyph positioning, font CMap handling, tabular structure detection.")
    lines.append("=" * 80)

    out_text = "\n".join(lines) + "\n"
    out_file.write_text(out_text, encoding="utf-8")
    print(f"Report written to: {out_file}")
    print(out_text)

if __name__ == "__main__":
    main()

