"""
backend/attachments/faithfulness.py

High-precision faithfulness verification for document walkthrough explanations:
- Extracts only named items: bold terms inside body text and list item titles
- Filters out model-invented structural headers ("Definition", "Breakdown", "Matrix Structure")
- Excludes text inside '*Example (analogous)*:' (analogous examples are intentionally illustrative)
- Normalizes case, hyphens, plurals, spacing, ligatures, and glues broken initial letters
- Searches the full document text (not just the isolated section chunk)
- Logs every flagged item with source context and reason to data/measure/
"""

import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hinaku.attachments.faithfulness")

ROOT = Path(__file__).resolve().parent.parent.parent
MEASURE_DIR = ROOT / "data" / "measure"

# Model-invented structural headings to ignore
INVENTED_LABELS_LOWER = {
    "definition", "breakdown", "matrix structure", "pillar breakdown",
    "threats & solutions", "threats and solutions", "risk prioritization",
    "threat landscape evolution", "overview", "summary", "key terms",
    "details", "core concepts", "key components", "framework breakdown",
    "key points", "architecture layers", "lifecycle stages", "threat models",
    "conclusion", "takeaways", "exam-oriented key takeaways", "note", "notes",
    "example", "example (analogous)", "analogous example", "key takeaways",
    "ai triad definition", "adversarial ml definition", "security triad"
}

LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"'
}

def normalize_text_for_search(text: str) -> str:
    """
    Normalizes text for robust semantic term searching:
    - Replaces ligatures and fancy quotes
    - Glues broken single-letter initials (e.g. 'A dversarial T hreat' -> 'Adversarial Threat')
    - Lowercases and collapses whitespace
    """
    s = text
    for k, v in LIGATURE_MAP.items():
        s = s.replace(k, v)

    # Glue separated initials: e.g. "A\ndversarial" or "A  dversarial" -> "Adversarial"
    s = re.sub(r"\b([A-Za-z])[\s\n\r]+([a-z]{2,})\b", r"\1\2", s)
    s = re.sub(r"\s+", " ", s).lower().strip()
    return s

def extract_named_items(text: str) -> List[str]:
    """
    Extracts only true named items (bold terms in body text, list item titles).
    Excludes:
    - Text inside '*Example (analogous)*:'
    - Model-invented structural labels
    """
    # 1. Strip the example section if present
    example_m = re.search(r"(?i)\*?Example\s*\(analogous\)\*?:", text)
    body_text = text[:example_m.start()] if example_m else text

    # Strip exam takeaways heading if present
    takeaways_m = re.search(r"(?i)\*?\*?Exam-Oriented\s+Key\s+Takeaways\*?\*?", body_text)
    if takeaways_m:
        body_text = body_text[:takeaways_m.start()]

    items = []

    # 2. Bold terms inside body: **Term**
    bold_matches = re.findall(r"\*\*([^*]+)\*\*", body_text)
    for b in bold_matches:
        b_clean = b.strip().strip(":").strip("-").strip()
        if len(b_clean) >= 3:
            # Skip model-invented structural headers
            if b_clean.lower() in INVENTED_LABELS_LOWER:
                continue
            if len(b_clean.split()) <= 6:
                items.append(b_clean)

    # 3. List item titles: e.g. "*   **Fairness**: ..." or "1. Inception/Scoping:"
    list_matches = re.findall(
        r"(?:^|\n)\s*(?:\d+\.|\*|-)\s*(?:\*\*)?([A-Za-z0-9][A-Za-z0-9\s'’/&–-]{2,40})(?:\*\*)?(?::|\s*—|\s*–|\n)",
        body_text
    )
    for l_item in list_matches:
        l_clean = l_item.strip().strip(":").strip()
        if len(l_clean) >= 3:
            if l_clean.lower() in INVENTED_LABELS_LOWER:
                continue
            if len(l_clean.split()) <= 6:
                items.append(l_clean)

    # Deduplicate preserving order
    seen: Set[str] = set()
    deduped = []
    for it in items:
        norm = re.sub(r"[^a-zA-Z0-9]+", "", it.lower())
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(it)

    return deduped

def check_term_in_source(term: str, source_normalized: str) -> bool:
    """
    Checks if a normalized term or its keywords appear in the normalized document text.
    Handles hyphens, punctuation (&, /), plurals (tactics/tactic), and partial acronym expansions.
    """
    # Normalize both term and source by removing non-alphanumeric punctuation
    norm_source_clean = re.sub(r"[^a-z0-9\s]+", " ", source_normalized)
    norm_source_clean = re.sub(r"\s+", " ", norm_source_clean).strip()

    norm_term = normalize_text_for_search(term)
    term_clean = re.sub(r"[^a-z0-9\s]+", " ", norm_term)
    term_clean = re.sub(r"\s+", " ", term_clean).strip()

    if not term_clean:
        return True

    # 1. Direct substring match on cleaned alphanumeric strings
    if f" {term_clean} " in f" {norm_source_clean} " or term_clean in norm_source_clean:
        return True

    # 2. Singular / plural variants
    words = term_clean.split()
    singular_words = []
    for w in words:
        if w.endswith("ies") and len(w) > 4:
            singular_words.append(w[:-3] + "y")
        elif w.endswith("es") and len(w) > 3:
            singular_words.append(w[:-2])
        elif w.endswith("s") and len(w) > 3:
            singular_words.append(w[:-1])
        else:
            singular_words.append(w)

    singular_term = " ".join(singular_words)
    if f" {singular_term} " in f" {norm_source_clean} " or singular_term in norm_source_clean:
        return True

    # 3. Multi-word match: at least 70% of substantive keywords appear
    substantive = [w for w in singular_words if len(w) > 2 and w not in {"the", "and", "for", "with", "from", "are"}]
    if not substantive:
        return True

    matches = sum(1 for w in substantive if f" {w} " in f" {norm_source_clean} ")
    return (matches / len(substantive)) >= 0.70

def log_faithfulness_mismatch_to_measure(
    item: str,
    sec_title: str,
    reason: str,
    source_snippet: str
) -> None:
    """Writes flagged item and source context to data/measure/."""
    try:
        MEASURE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        mismatch_file = MEASURE_DIR / f"{ts}_faithfulness_mismatches.txt"
        entry = (
            f"TIMESTAMP: {datetime.now(timezone.utc).isoformat()}\n"
            f"SECTION: {sec_title}\n"
            f"FLAGGED ITEM: {item}\n"
            f"REASON: {reason}\n"
            f"SOURCE TEXT SNIPPET:\n{source_snippet}\n"
            f"{'=' * 80}\n"
        )
        with open(mismatch_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning(f"Could not log faithfulness mismatch: {e}")

def verify_explanation_faithfulness(
    explanation_text: str,
    section_text: str,
    full_document_text: Optional[str] = None,
    sec_title: str = "Section"
) -> Tuple[bool, List[str], str]:
    """
    Checks if named items are grounded in the section text or full document.
    Returns: (is_faithful, missing_terms, annotated_text)
    """
    named_items = extract_named_items(explanation_text)
    if not named_items:
        return True, [], explanation_text

    # Search in combined source (section + full document)
    source_to_search = section_text
    if full_document_text:
        source_to_search = section_text + "\n\n" + full_document_text

    normalized_source = normalize_text_for_search(source_to_search)

    missing = []
    annotated = explanation_text

    for item in named_items:
        if not check_term_in_source(item, normalized_source):
            missing.append(item)
            reason = f"Term '{item}' was not found in section text or full document."
            source_snippet = section_text[:400] + "..." if len(section_text) > 400 else section_text
            log_faithfulness_mismatch_to_measure(
                item=item,
                sec_title=sec_title,
                reason=reason,
                source_snippet=source_snippet
            )
            logger.info(f"Faithfulness mismatch in '{sec_title}': term '{item}' not found.")

    if missing:
        for m in missing:
            pat_bold = rf"(\*\*{re.escape(m)}\*\*)"
            if re.search(pat_bold, annotated):
                annotated = re.sub(pat_bold, rf"\1 *(wording not from your notes)*", annotated, count=1)
            else:
                pat_plain = rf"\b({re.escape(m)})\b"
                annotated = re.sub(pat_plain, rf"\1 *(wording not from your notes)*", annotated, count=1)
        return False, missing, annotated

    return True, [], explanation_text
