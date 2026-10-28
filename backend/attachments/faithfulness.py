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

def stem_word(w: str) -> str:
    """Lightweight zero-dependency morphological stemmer for English inflections."""
    w = w.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    for sfx in ["ing", "tion", "ment", "ed", "es", "s"]:
        if w.endswith(sfx) and len(w) > len(sfx) + 2:
            return w[:-len(sfx)]
    return w

def check_term_in_source(term: str, source_normalized: str) -> bool:
    """
    Checks if a normalized term or its keywords appear in the normalized document text.
    Handles hyphens, punctuation (&, /), plurals, gerunds/participles, and word reordering.
    Enforces that substantive words appear in close proximity (sliding window),
    preventing disjoint words scattered across different pages from matching falsely.
    """
    norm_source = normalize_text_for_search(source_normalized)
    norm_source_clean = re.sub(r"[^a-z0-9\s]+", " ", norm_source)
    norm_source_clean = re.sub(r"\s+", " ", norm_source_clean).strip()

    norm_term = normalize_text_for_search(term)
    term_clean = re.sub(r"[^a-z0-9\s]+", " ", norm_term)
    term_clean = re.sub(r"\s+", " ", term_clean).strip()

    if not term_clean:
        return True

    # 1. Direct substring match on cleaned alphanumeric strings
    if f" {term_clean} " in f" {norm_source_clean} " or term_clean in norm_source_clean:
        return True

    # 2. Substantive words and morphological stemming
    words = term_clean.split()
    substantive = [w for w in words if len(w) > 2 and w not in {"the", "and", "for", "with", "from", "are", "that", "which"}]
    if not substantive:
        return True

    target_stems = set(stem_word(w) for w in substantive)
    source_words = norm_source_clean.split()
    source_stems = [stem_word(sw) for sw in source_words]

    # Enforce proximity: all target stems must appear within a local window (e.g. 15 words)
    win_size = min(18, len(substantive) * 4 + 4)
    for i in range(len(source_stems)):
        window = set(source_stems[i : i + win_size])
        if target_stems.issubset(window):
            return True

    return False

def log_faithfulness_mismatch_to_measure(
    item: str,
    sec_title: str,
    reason: str,
    source_snippet: str,
    nearest_phrase: Optional[str] = None,
    action: str = "FLAGGED"
) -> None:
    """Writes flagged item, nearest source phrase, action, and source context to data/measure/."""
    try:
        MEASURE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        mismatch_file = MEASURE_DIR / f"{ts}_faithfulness_mismatches.txt"
        entry = (
            f"TIMESTAMP: {datetime.now(timezone.utc).isoformat()}\n"
            f"SECTION: {sec_title}\n"
            f"FLAGGED ITEM: {item}\n"
            f"NEAREST SOURCE PHRASE: {nearest_phrase or 'None'}\n"
            f"ACTION: {action}\n"
            f"REASON: {reason}\n"
            f"SOURCE TEXT SNIPPET:\n{source_snippet}\n"
            f"{'=' * 80}\n"
        )
        with open(mismatch_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning(f"Could not log faithfulness mismatch: {e}")

import difflib

def find_nearest_source_phrase(term: str, source_text: str) -> Optional[Tuple[str, float]]:
    """
    Finds the nearest matching candidate phrase in source_text for an ungrounded term.
    Returns (nearest_phrase, similarity_score) if similarity >= 0.65, else None.
    """
    term_lower = term.lower().strip()
    term_words = [w for w in re.findall(r"\b[a-z0-9]{3,}\b", term_lower) if w not in {"the", "and", "for", "with", "from", "are"}]
    if not term_words:
        return None

    term_stems = set(stem_word(w) for w in term_words)

    candidates = []
    # 1. Bold terms in source
    bold_candidates = re.findall(r"\*\*([^*]+)\*\*", source_text)
    for b in bold_candidates:
        bc = b.strip().strip(":").strip("-").strip()
        if 3 <= len(bc) <= 60:
            candidates.append(bc)

    # 2. Lines, list items, and clauses
    for line in source_text.splitlines():
        line = line.strip()
        if not line or line.startswith("http"):
            continue
        clean_line = re.sub(r"^(?:\d+\.|\*|-)\s*", "", line).strip()
        if 3 <= len(clean_line) <= 60:
            candidates.append(clean_line)
        # Also split clauses by comma, semicolon, period, or conjunctions ('and', 'or')
        for clause in re.split(r"[,;.]|\b(?:and|or)\b", clean_line):
            c_clean = clause.strip("-*# ").strip()
            if 3 <= len(c_clean) <= 60:
                candidates.append(c_clean)

    best_match = None
    best_score = 0.0

    for cand in set(candidates):
        cand_lower = cand.lower().strip()
        cand_words = [w for w in re.findall(r"\b[a-z0-9]{3,}\b", cand_lower) if w not in {"the", "and", "for", "with", "from", "are"}]
        cand_stems = set(stem_word(w) for w in cand_words)

        if term_stems and cand_stems:
            overlap = term_stems.intersection(cand_stems)
            jaccard = len(overlap) / max(len(term_stems), len(cand_stems))
        else:
            jaccard = 0.0

        seq_ratio = difflib.SequenceMatcher(None, term_lower, cand_lower).ratio()

        combined_score = max(seq_ratio, (seq_ratio * 0.4 + jaccard * 0.6))
        if len(overlap) >= 2 and jaccard >= 0.5:
            combined_score = max(combined_score, 0.76)

        if combined_score > best_score:
            best_score = combined_score
            best_match = cand

    if best_match and best_score >= 0.65:
        return best_match, best_score
    return None

def verify_explanation_faithfulness(
    explanation_text: str,
    section_text: str,
    full_document_text: Optional[str] = None,
    sec_title: str = "Section"
) -> Tuple[bool, List[str], str]:
    """
    Checks if named items are grounded in the section text or full document.
    - If a term is an ungrounded near-paraphrase of a source term (score >= 0.65),
      it is deterministically replaced with the nearest source phrase.
    - If ungrounded with no match, it is flagged for regeneration.
    Returns: (is_faithful, missing_terms, aligned_text)
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
    aligned = explanation_text
    replacements = []

    for item in named_items:
        if not check_term_in_source(item, normalized_source):
            # Check for nearest source phrase match
            near_match = find_nearest_source_phrase(item, section_text)
            if not near_match and full_document_text:
                near_match = find_nearest_source_phrase(item, full_document_text[:3000])

            source_snippet = section_text[:400] + "..." if len(section_text) > 400 else section_text

            if near_match:
                nearest_phrase, sim_score = near_match
                # Deterministic replacement of the near-paraphrase with the exact source phrase
                pat_bold = rf"\*\*({re.escape(item)})\*\*"
                if re.search(pat_bold, aligned):
                    aligned = re.sub(pat_bold, f"**{nearest_phrase}**", aligned, count=1)
                else:
                    pat_plain = rf"\b{re.escape(item)}\b"
                    aligned = re.sub(pat_plain, nearest_phrase, aligned, count=1)

                replacements.append((item, nearest_phrase, sim_score))
                reason = f"Near-paraphrase '{item}' matched source phrase '{nearest_phrase}' (similarity {sim_score:.2f}). Replaced deterministically."
                log_faithfulness_mismatch_to_measure(
                    item=item,
                    sec_title=sec_title,
                    reason=reason,
                    source_snippet=source_snippet,
                    nearest_phrase=nearest_phrase,
                    action="DETERMINISTIC_REPLACEMENT"
                )
                logger.info(f"Faithfulness auto-aligned '{item}' -> '{nearest_phrase}' in '{sec_title}'.")
            else:
                # No match found: true ungrounded term requiring regeneration
                missing.append(item)
                reason = f"Term '{item}' was not found in section text or full document, with no close candidate match."
                log_faithfulness_mismatch_to_measure(
                    item=item,
                    sec_title=sec_title,
                    reason=reason,
                    source_snippet=source_snippet,
                    nearest_phrase=None,
                    action="REGENERATE_TOPIC"
                )
                logger.info(f"Faithfulness mismatch in '{sec_title}': ungrounded term '{item}'.")

    if missing:
        for m in missing:
            pat_bold = rf"(\*\*{re.escape(m)}\*\*)"
            if re.search(pat_bold, aligned):
                aligned = re.sub(pat_bold, rf"\1 *(wording not from your notes)*", aligned, count=1)
            else:
                pat_plain = rf"\b({re.escape(m)})\b"
                aligned = re.sub(pat_plain, rf"\1 *(wording not from your notes)*", aligned, count=1)
        return False, missing, aligned

    return True, [], aligned
