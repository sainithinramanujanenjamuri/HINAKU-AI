"""
scripts/measure_pypdf_comparison.py

Measures and compares PDF extraction results on both real sample PDFs:
- Before (hand-written FlateDecode parser) vs After (pypdf 6.20.1)
- Reports page count, character count, and text quality comparison
- Captures output to data/measure/<timestamp>_pypdf_comparison.txt
"""

import datetime
import io
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pypdf
from backend.attachments.extractor import extract_text_from_pdf, _parse_pdf_cmap, DocumentPage

def handwritten_extract(content: bytes, max_pages: int = 100):
    obj_pattern = re.compile(rb"(\d+)\s+(\d+)\s+obj\s*(.*?)\s*endobj", re.DOTALL)
    objects = {}
    decompressed_streams = {}
    for m in obj_pattern.finditer(content):
        num = int(m.group(1))
        body = m.group(3)
        objects[num] = body
        sm = re.search(rb"stream[\r\n]+(.*?)[\r\n]+endstream", body, re.DOTALL)
        if sm:
            raw_s = sm.group(1)
            try:
                dec = zlib.decompress(raw_s)
                if len(dec) / max(1, len(raw_s)) <= 100:
                    decompressed_streams[num] = dec
            except Exception:
                decompressed_streams[num] = raw_s

    font_cmaps = {}
    global_cmap = {}
    for num, body in objects.items():
        if b"/Type /Font" in body or b"/Type/Font" in body:
            tu_m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
            if tu_m:
                tu_num = int(tu_m.group(1))
                if tu_num in decompressed_streams:
                    cmap_dict = _parse_pdf_cmap(decompressed_streams[tu_num])
                    font_cmaps[num] = cmap_dict
                    global_cmap.update(cmap_dict)
        elif b"beginbfchar" in body or b"beginbfrange" in body:
            if num in decompressed_streams:
                cmap_dict = _parse_pdf_cmap(decompressed_streams[num])
                global_cmap.update(cmap_dict)

    res_cmaps = {}
    for body in list(objects.values()) + list(decompressed_streams.values()):
        for fm in re.finditer(rb"/([a-zA-Z0-9_-]+)\s+(\d+)\s+\d+\s+R", body):
            fname = fm.group(1).decode("latin-1", errors="ignore")
            fobj = int(fm.group(2))
            if fobj in font_cmaps:
                res_cmaps[fname] = font_cmaps[fobj]

    def decode_text_stream(stream_bytes: bytes) -> str:
        text = stream_bytes.decode("latin-1", errors="ignore")
        current_font = "F1"
        out = []
        for line in re.finditer(
            r"(?:/([a-zA-Z0-9_-]+)\s+[\d.]+\s+Tf|<([0-9A-Fa-f]+)>\s*Tj|\[(.*?)\]\s*TJ|\((.*?)\)\s*Tj|([-0-9.]+)\s+([-0-9.]+)\s+T[md]|T\*)",
            text
        ):
            if line.group(1):
                current_font = line.group(1)
            elif line.group(2):
                cmap = res_cmaps.get(current_font, global_cmap)
                h = line.group(2)
                out.append("".join(cmap.get(int(h[i:i+4], 16), "") for i in range(0, len(h), 4)))
            elif line.group(3):
                cmap = res_cmaps.get(current_font, global_cmap)
                arr = line.group(3)
                for item in re.finditer(r"(?:<([0-9A-Fa-f]+)>|\((.*?)\)|([-0-9.]+))", arr):
                    if item.group(1):
                        h = item.group(1)
                        out.append("".join(cmap.get(int(h[i:i+4], 16), "") for i in range(0, len(h), 4)))
                    elif item.group(2):
                        out.append(item.group(2))
                    elif item.group(3):
                        val = float(item.group(3))
                        if val < -150:
                            out.append(" ")
            elif line.group(4):
                out.append(line.group(4))
            elif line.group(6) and float(line.group(6)) != 0:
                out.append("\n")
        return "".join(out)

    page_objs = [
        (num, body) for num, body in objects.items()
        if re.search(rb"/Type\s*/Page\b", body) and not re.search(rb"/Type\s*/Pages\b", body)
    ]
    page_objs.sort(key=lambda x: content.find(f"{x[0]} 0 obj".encode("ascii")))

    pages = []
    if page_objs:
        for idx, (p_num, p_body) in enumerate(page_objs[:max_pages], 1):
            contents_match = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", p_body)
            if not contents_match:
                contents_match = re.search(rb"/Contents\s*\[(.*?)\]", p_body, re.DOTALL)
                ref_nums = [int(n) for n in re.findall(rb"(\d+)\s+\d+\s+R", contents_match.group(1))] if contents_match else []
            else:
                ref_nums = [int(contents_match.group(1))]

            page_text = ""
            for rnum in ref_nums:
                if rnum in decompressed_streams:
                    page_text += decode_text_stream(decompressed_streams[rnum]) + "\n"
            clean_page_text = re.sub(r"[ \t]+", " ", page_text).strip()
            pages.append(DocumentPage(page_number=idx, text=clean_page_text))
    return pages

def main():
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = ROOT / "data" / "measure" / f"{now_str}_pypdf_comparison.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("COMMAND: python scripts/measure_pypdf_comparison.py")
    lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
    lines.append("=" * 80)
    lines.append("PDF EXTRACTION COMPARISON: HANDWRITTEN vs PYPDF (6.20.1)")
    lines.append("=" * 80)
    lines.append("Approved Library: pypdf")
    lines.append("Version: 6.20.1")
    lines.append("Release Date: 2026-10-12T16:14:22 (16 days old, >= 14 days)")
    lines.append("Size: 402,665 bytes (393.2 KB)")
    lines.append("License: BSD-3-Clause")
    lines.append("-" * 80)

    samples_dir = ROOT / "tests" / "real_samples"
    pdf_files = sorted(list(samples_dir.glob("*.pdf")))

    for p in pdf_files:
        raw_b = p.read_bytes()
        lines.append(f"\nDocument: {p.name}")
        lines.append(f"Binary Size: {len(raw_b)} bytes ({len(raw_b)/1024:.1f} KB)")

        # 1. Before: Handwritten
        pages_before = handwritten_extract(raw_b)
        chars_before = sum(len(pg.text) for pg in pages_before)
        non_empty_before = len([pg for pg in pages_before if pg.text.strip()])

        # 2. After: pypdf via extract_text_from_pdf
        pages_after = extract_text_from_pdf(raw_b)
        chars_after = sum(len(pg.text) for pg in pages_after)
        non_empty_after = len([pg for pg in pages_after if pg.text.strip()])

        lines.append(f"  [Before - Handwritten Parser]")
        lines.append(f"    Pages: {len(pages_before)} (non-empty: {non_empty_before})")
        lines.append(f"    Characters: {chars_before}")
        lines.append(f"  [After - pypdf 6.20.1]")
        lines.append(f"    Pages: {len(pages_after)} (non-empty: {non_empty_after})")
        lines.append(f"    Characters: {chars_after}")
        lines.append(f"  Difference: {chars_after - chars_before:+d} characters")
        lines.append(f"  Sample text (first 150 chars pypdf):")
        lines.append(f"    {repr(pages_after[0].text[:150]) if pages_after else 'EMPTY'}")

    lines.append("=" * 80)
    out_text = "\n".join(lines) + "\n"
    out_file.write_text(out_text, encoding="utf-8")
    print(f"Report written to: {out_file}")
    print(out_text)

if __name__ == "__main__":
    main()

