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

    # 4. Strip any model-written citations or pseudo-citations with tolerant patterns
    # Tolerant pattern matches: "*Based on ...*", "Based on ...", "*Source: ...*", "According to ...", etc.
    cleaned = re.sub(r"(?im)^\s*\*?(?:Based\s+on|Source:|According\s+to|References?:|Ref:)\s+.*?(?:\*|\.)?\s*$", "", cleaned)
    cleaned = re.sub(r"(?i)\n+\s*\*?(?:Based\s+on|Source:|According\s+to)\s+.*?(?:\*|\.)?\s*$", "", cleaned)
    cleaned = re.sub(r"\[Explain the whole document\]\([^)]*\)", "", cleaned).strip()

    # 5. Clean up excessive trailing newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned, citations


def check_section_answer_overlap(
    answer: str,
    section_text: str,
    section_title: str = "",
    min_distinctive_ngrams: int = 2
) -> bool:
    """
    Verifies that the answer actually used/grounded in this section's content:
    Checks for distinctive content words/n-grams between the section and the answer.
    Prevents citing sections that were retrieved but not actually used by the model
    (e.g., citing Unity UI when answering about Player Types, or Topic 6 when answering Topic 7).
    """
    if not answer or not (section_text or section_title):
        return False

    a_lower = answer.lower()
    t_lower = (section_title or "").lower()
    s_lower = (section_text or "").lower()

    stopwords = {
        "this", "that", "these", "those", "with", "from", "have", "been", "were",
        "they", "what", "when", "where", "which", "will", "would", "could", "should",
        "about", "their", "there", "other", "after", "before", "between", "under",
        "above", "notes", "based", "according", "document", "unit", "section", "topic",
        "also", "into", "over", "such", "than", "more", "most", "some", "many", "each"
    }

    # Distinctive words from section (length >= 4, non-stopword)
    combined = t_lower + " " + s_lower
    sec_words = [w for w in re.findall(r"\b[a-z]{4,}\b", combined) if w not in stopwords]
    if not sec_words:
        return False

    # Check for distinctive bigrams
    bigrams = set()
    for i in range(len(sec_words) - 1):
        w1, w2 = sec_words[i], sec_words[i+1]
        if w1 != w2:
            bigrams.add(f"{w1} {w2}")

    shared_bigrams = [bg for bg in bigrams if bg in a_lower]
    if len(shared_bigrams) >= min_distinctive_ngrams:
        return True

    # Check for distinctive terms (length >= 6)
    distinct_terms = set(w for w in sec_words if len(w) >= 6)
    shared_terms = [w for w in distinct_terms if re.search(r"\b" + re.escape(w) + r"\b", a_lower)]
    if len(shared_terms) >= 3:
        return True

    # Check if key title phrase appears in answer (e.g. "player types", "mda framework", "mlsecops", "evasion")
    clean_title = re.sub(r"^(?:Topic|Session|Section|\d+[\.\s\-]+)+", "", section_title, flags=re.IGNORECASE).strip().lower()
    if len(clean_title) >= 5 and clean_title in a_lower:
        return True

    return False


def format_outline_citations(sections_meta: List[Dict[str, Any]]) -> str:
    """
    Generates exact citation string in code from retrieved outline section metadata:
    e.g. '*Based on Topic 1 — AI Triad: Security, Ethics, and Regulation (pp. 1-2).*'
    or '*Based on 9. Player Types (pp. 3-3).*'
    Never model-written. Only generated when answer used retrieved chunks.
    """
    if not sections_meta:
        return ""

    parts = []
    seen = set()
    for s in sections_meta:
        title = s.get("title", "").strip()
        sp = s.get("start_page", 1)
        ep = s.get("end_page", sp)
        if not title:
            continue
        key = (title.lower(), sp, ep)
        if key in seen:
            continue
        seen.add(key)
        page_str = f"p. {sp}" if sp == ep else f"pp. {sp}-{ep}"
        parts.append(f"{title} ({page_str})")
        if len(parts) >= 2:
            break

    if not parts:
        return ""
    if len(parts) == 1:
        return f"\n\n*Based on {parts[0]}.*"
    return f"\n\n*Based on {parts[0]} and {parts[1]}.*"

