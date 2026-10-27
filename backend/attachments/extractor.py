"""
backend/attachments/extractor.py

Text and content extraction for attachments:
- Text-like files: UTF-8 / Latin-1 decoding
- PDF: Structured text layer extraction using standard-library FlateDecode stream decompression,
  /ToUnicode CMap parsing, and PDF operand decoding
- DOCX: Paragraph and table text extraction from word/document.xml
- Images: PIL Image metadata verification
"""

import html
from html.parser import HTMLParser
import io
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image

class DocumentPage:
    def __init__(self, page_number: int, text: str):
        self.page_number = page_number
        self.text = text.strip()

def extract_text_from_file(content: bytes) -> List[DocumentPage]:
    """Extract plain text from txt, md, csv, json, code files."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")
    return [DocumentPage(page_number=1, text=text)]

class SafeHTMLTextExtractor(HTMLParser):
    """
    Standard-library HTML-to-text converter:
    - Drops script, style, noscript, head, iframe elements
    - Drops hidden elements (display:none, visibility:hidden, hidden attribute, zero font size)
    - Formats headings (#, ##, etc.) for outline extraction
    - Correctly handles HTML5 void tags without end tags
    - Treats output strictly as untrusted user text
    """
    IGNORE_TAGS = {"script", "style", "noscript", "head", "iframe", "object", "embed"}
    VOID_TAGS = {"meta", "link", "img", "br", "hr", "input", "base", "area", "col", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore_stack = []

    def _is_hidden(self, attrs):
        for k, v in attrs:
            if k == "hidden":
                return True
            if k == "style" and v:
                v_clean = v.lower().replace(" ", "")
                if any(rule in v_clean for rule in ("display:none", "visibility:hidden", "font-size:0", "opacity:0")):
                    return True
        return False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.ignore_stack:
            if tag not in self.VOID_TAGS:
                self.ignore_stack.append(tag)
            return

        if tag in self.IGNORE_TAGS or self._is_hidden(attrs):
            if tag not in self.VOID_TAGS:
                self.ignore_stack.append(tag)
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self.text_parts.append("\n\n" + "#" * level + " ")
        elif tag in {"p", "div", "section", "article", "tr"}:
            self.text_parts.append("\n\n")
        elif tag == "li":
            self.text_parts.append("\n* ")
        elif tag == "br":
            self.text_parts.append("\n")
        elif tag in {"td", "th"}:
            self.text_parts.append(" | ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.ignore_stack:
            if tag in self.ignore_stack:
                while self.ignore_stack:
                    popped = self.ignore_stack.pop()
                    if popped == tag:
                        break
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.text_parts.append("\n\n")

    def handle_data(self, data):
        if not self.ignore_stack and data:
            self.text_parts.append(data)

def extract_text_from_html(content: bytes) -> List[DocumentPage]:
    """Extract structured, sanitised plain text from HTML content."""
    try:
        raw_html = content.decode("utf-8")
    except UnicodeDecodeError:
        raw_html = content.decode("latin-1", errors="replace")

    parser = SafeHTMLTextExtractor()
    parser.feed(raw_html)
    raw_text = "".join(parser.text_parts)
    unescaped = html.unescape(raw_text)
    cleaned = re.sub(r"\n{3,}", "\n\n", unescaped).strip()
    return [DocumentPage(page_number=1, text=cleaned)]


def extract_text_from_docx(content: bytes) -> List[DocumentPage]:
    """
    Extracts structured paragraphs and tables from DOCX archive.
    Uses Python stdlib zipfile and xml.etree.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        if "word/document.xml" not in zf.namelist():
            return []
        doc_xml = zf.read("word/document.xml")

    # Protection against entity expansion / billion-laughs XML attacks
    if b"<!ENTITY" in doc_xml or b"<!DOCTYPE" in doc_xml:
        raise ValueError("XML entity expansion / DTD is prohibited for security.")

    root = ET.fromstring(doc_xml)
    # XML namespace for WordprocessingML
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    paragraphs = []
    # Search for all paragraph nodes
    for p in root.iter(f"{{{ns['w']}}}p"):
        texts = [node.text for node in p.iter(f"{{{ns['w']}}}t") if node.text]
        if texts:
            paragraphs.append("".join(texts))

    full_text = "\n\n".join(paragraphs).strip()
    return [DocumentPage(page_number=1, text=full_text)]

def _parse_pdf_cmap(cmap_data: bytes) -> Dict[int, str]:
    """Parse a PDF /ToUnicode CMap stream into a char-code -> Unicode string mapping."""
    mapping: Dict[int, str] = {}
    text = cmap_data.decode("latin-1", errors="ignore")
    
    # Parse beginbfchar blocks: <0001> <0020>
    for block in re.finditer(r"beginbfchar\s*(.*?)\s*endbfchar", text, re.DOTALL):
        for line in block.group(1).splitlines():
            m = re.findall(r"<([0-9A-Fa-f]+)>", line)
            if len(m) >= 2:
                try:
                    src = int(m[0], 16)
                    dst = chr(int(m[1], 16))
                    mapping[src] = dst
                except Exception:
                    pass

    # Parse beginbfrange blocks: <0001> <0005> <0041>
    for block in re.finditer(r"beginbfrange\s*(.*?)\s*endbfrange", text, re.DOTALL):
        for line in block.group(1).splitlines():
            m = re.findall(r"<([0-9A-Fa-f]+)>", line)
            if len(m) == 3:
                try:
                    start = int(m[0], 16)
                    end = int(m[1], 16)
                    dst_start = int(m[2], 16)
                    for code in range(start, end + 1):
                        mapping[code] = chr(dst_start + (code - start))
                except Exception:
                    pass
    return mapping

def extract_text_from_pdf(content: bytes, max_pages: int = 100) -> List[DocumentPage]:
    """
    Extracts structured pages from PDF using standard library zlib decompression,
    /ToUnicode CMap glyph resolution, and PDF operand decoding.
    Handles multi-page PDFs, subsetted fonts, and FlateDecode streams.
    """
    # 1. Parse all PDF indirect objects: N M obj ... endobj
    obj_pattern = re.compile(rb"(\d+)\s+(\d+)\s+obj\s*(.*?)\s*endobj", re.DOTALL)
    objects: Dict[int, bytes] = {}
    decompressed_streams: Dict[int, bytes] = {}

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

    # 2. Extract and resolve all /ToUnicode CMaps across fonts (tracked per font object and resource)
    font_cmaps: Dict[int, Dict[int, str]] = {}
    global_cmap: Dict[int, str] = {}
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

    # Map resource font names (e.g. /F1, /F5) to their CMap dictionaries
    res_cmaps: Dict[str, Dict[int, str]] = {}
    for body in list(objects.values()) + list(decompressed_streams.values()):
        for fm in re.finditer(rb"/([a-zA-Z0-9_-]+)\s+(\d+)\s+\d+\s+R", body):
            fname = fm.group(1).decode("latin-1", errors="ignore")
            fobj = int(fm.group(2))
            if fobj in font_cmaps:
                res_cmaps[fname] = font_cmaps[fobj]

    def decode_text_stream(stream_bytes: bytes) -> str:
        text = stream_bytes.decode("latin-1", errors="ignore")
        current_font = "F1"
        out: List[str] = []
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

    # 3. Locate /Type /Page objects in document order
    page_objs = [
        (num, body) for num, body in objects.items()
        if re.search(rb"/Type\s*/Page\b", body) and not re.search(rb"/Type\s*/Pages\b", body)
    ]
    page_objs.sort(key=lambda x: content.find(f"{x[0]} 0 obj".encode("ascii")))

    pages: List[DocumentPage] = []
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

    if not pages or all(len(p.text) == 0 for p in pages):
        extracted_text_blocks = []
        for num, stream_data in decompressed_streams.items():
            if b"BT" in stream_data and b"ET" in stream_data:
                decoded = decode_text_stream(stream_data)
                clean = re.sub(r"\s+", " ", decoded).strip()
                if clean:
                    extracted_text_blocks.append(clean)
        pages = [DocumentPage(page_number=i, text=b) for i, b in enumerate(extracted_text_blocks[:max_pages], 1)]

    return pages if pages else [DocumentPage(page_number=1, text="")]

def validate_and_inspect_image(content: bytes) -> Dict[str, Any]:
    """
    Validates image bytes using PIL.
    Returns metadata dict: format, width, height, mode.
    """
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
        with Image.open(io.BytesIO(content)) as img:
            return {
                "format": img.format.lower() if img.format else "unknown",
                "width": img.width,
                "height": img.height,
                "mode": img.mode
            }
    except Exception as e:
        raise ValueError(f"Invalid image file: {e}")
