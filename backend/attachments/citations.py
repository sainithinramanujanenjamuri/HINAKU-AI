"""
backend/attachments/citations.py

Parses and strips wrapper tags (<document_reference>, </document_reference>)
and converts citations into structured metadata chips:
[{"file": "hardware_memo.txt", "page": 1}]
"""

import re
from typing import Any, Dict, List, Tuple

WRAPPER_BLOCK_REGEX = re.compile(
    r"<document_reference>[\s\S]*?</document_reference>",
    re.IGNORECASE
)
WRAPPER_TAG_REGEX = re.compile(
    r"</?document_reference(?:\s[^>]*)?>",
    re.IGNORECASE
)

# Citation patterns:
# 1. Bracketed or parenthesized with explicit page: [File: x.pdf, Page: 4] or (Source: x.pdf, Page: 4)
# 2. Bracketed or parenthesized without page: [File: x.pdf] or (Source: x.pdf)
# 3. Explicit prefix without page: Source: x.pdf or File: x.pdf
FILE_PAGE_PATTERNS = [
    re.compile(r"[\[\(]?(?:Source|File:\s*)?([a-zA-Z0-9_\-\. ]+\.[a-zA-Z0-9]+)[,\s]+(?:Page|p\.?)\s*:?\s*(\d+)[\]\)]?", re.IGNORECASE),
    re.compile(r"[\[\(](?:Source|File:\s*)?([a-zA-Z0-9_\-\. ]+\.[a-zA-Z0-9]+)[\]\)]", re.IGNORECASE),
    re.compile(r"(?:Source|File):\s*([a-zA-Z0-9_\-\. ]+\.[a-zA-Z0-9]+)", re.IGNORECASE),
]

def strip_wrapper_tags_and_extract_citations(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Strips <document_reference> blocks and standalone wrapper tags from text.
    Extracts structured citation chips: [{"file": filename, "page": page_number}].
    Returns (cleaned_text, citations_list).
    """
    if not text:
        return "", []

    citations: List[Dict[str, Any]] = []
    seen = set()

    def add_citation(filename: str, page: Any):
        clean_file = filename.strip()
        try:
            page_num = int(page) if page is not None else 1
        except (ValueError, TypeError):
            page_num = 1
        key = (clean_file.lower(), page_num)
        if key not in seen:
            seen.add(key)
            citations.append({"file": clean_file, "page": page_num})

    # 1. Run patterns in specificity order (explicit page first)
    for pattern in FILE_PAGE_PATTERNS:
        for match in pattern.finditer(text):
            f = match.group(1)
            p = match.group(2) if len(match.groups()) >= 2 and match.group(2) else None
            # If this is pattern 2 or 3 (no page), and we already have citations for this file with explicit page, skip
            if p is None and any(c["file"].lower() == f.strip().lower() for c in citations):
                continue
            add_citation(f, p)

    # 2. Strip all <document_reference> blocks completely
    cleaned = WRAPPER_BLOCK_REGEX.sub("", text)

    # 3. Strip any dangling open/close <document_reference> tags
    cleaned = WRAPPER_TAG_REGEX.sub("", cleaned)

    # 4. Clean up excessive trailing newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned, citations

