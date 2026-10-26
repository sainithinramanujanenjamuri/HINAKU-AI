"""
backend/attachments/extractor.py

Text and content extraction for attachments:
- Text-like files: UTF-8 / Latin-1 decoding
- PDF: Text layer extraction using standard-library FlateDecode stream decompression and PDF operand parsing
- DOCX: Paragraph and table text extraction from word/document.xml
- Images: PIL Image metadata verification
"""

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

def extract_text_from_docx(content: bytes) -> List[DocumentPage]:
    """
    Extracts structured paragraphs and tables from DOCX archive.
    Uses Python stdlib zipfile and xml.etree.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        if "word/document.xml" not in zf.namelist():
            return []
        doc_xml = zf.read("word/document.xml")
    
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

def extract_text_from_pdf(content: bytes, max_pages: int = 50) -> List[DocumentPage]:
    """
    Extracts text layer from PDF using standard library zlib decompression
    and PDF text stream token extraction.
    Supports FlateDecode compressed content streams.
    """
    pages: List[DocumentPage] = []

    # Find all /Contents references or stream objects
    # Pattern to find stream ... endstream
    stream_pattern = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    
    extracted_text_blocks = []
    for match in stream_pattern.finditer(content):
        raw_stream = match.group(1)
        # Try zlib inflate
        decompressed = None
        try:
            decompressed = zlib.decompress(raw_stream)
        except Exception:
            # Try raw stream if uncompressed
            if b"BT" in raw_stream and b"ET" in raw_stream:
                decompressed = raw_stream

        if decompressed:
            # Look for PDF text objects between BT (Begin Text) and ET (End Text)
            text_chunks = []
            
            # Extract parenthesized strings: (Hello World) Tj
            for tj_match in re.finditer(rb"\((.*?)\)\s*Tj", decompressed):
                raw_str = tj_match.group(1)
                try:
                    text_chunks.append(raw_str.decode("utf-8", errors="ignore"))
                except Exception:
                    pass

            # Extract array strings: [(Hello) 10 (World)] TJ
            for array_match in re.finditer(rb"\[(.*?)\]\s*TJ", decompressed):
                arr_content = array_match.group(1)
                for item_match in re.finditer(rb"\((.*?)\)", arr_content):
                    raw_str = item_match.group(1)
                    try:
                        text_chunks.append(raw_str.decode("utf-8", errors="ignore"))
                    except Exception:
                        pass

            if text_chunks:
                block_text = " ".join(text_chunks).strip()
                if block_text:
                    extracted_text_blocks.append(block_text)

    if not extracted_text_blocks:
        # Fallback regex for raw plain-text strings in uncompressed PDFs
        raw_strings = re.findall(rb"\(([A-Za-z0-9 .,;:!?'\"\-\n\r]{3,})\)", content)
        if raw_strings:
            fallback = " ".join(s.decode("latin-1", errors="ignore") for s in raw_strings[:200])
            return [DocumentPage(page_number=1, text=fallback)]
        return [DocumentPage(page_number=1, text="")]

    # Group into pages (approximate grouping if multiple streams, capped at max_pages)
    for i, block in enumerate(extracted_text_blocks[:max_pages], 1):
        pages.append(DocumentPage(page_number=i, text=block))

    return pages

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
