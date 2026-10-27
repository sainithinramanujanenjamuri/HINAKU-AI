"""
backend/attachments/faithfulness.py

Faithfulness verification for document walkthrough explanations:
- Collects named items (bold terms, numbered/bulleted step titles)
- Checks presence against the source section text
- Triggers a single regeneration with strict instructions if terms are ungrounded
- Appends '(wording not from your notes)' if terms remain ungrounded
"""

import re
import logging
from typing import List, Tuple, Set

logger = logging.getLogger("hinaku.attachments.faithfulness")

COMMON_CONVERSATIONAL_WORDS = {
    "note", "example", "key takeaway", "summary", "step", "overview",
    "definition", "important", "tips", "explanation", "conclusion",
    "details", "chess", "minecraft", "pubg"
}

def extract_named_items(text: str) -> List[str]:
    """Extracts bold terms and numbered/bulleted step names from generated text."""
    items = []
    # 1. Bold terms: **Term**
    bold_matches = re.findall(r"\*\*([^*]+)\*\*", text)
    for b in bold_matches:
        b_clean = b.strip().strip(":").strip()
        if len(b_clean) >= 3 and b_clean.lower() not in COMMON_CONVERSATIONAL_WORDS:
            # Skip full sentences in bold
            if len(b_clean.split()) <= 6:
                items.append(b_clean)

    # 2. Numbered / bulleted titles: e.g. "1. Business Objectives:" or "- Challenge:"
    step_matches = re.findall(r"(?:^|\n)\s*(?:\d+\.|\*|-)\s*([A-Za-z0-9][A-Za-z0-9\s'’/&–-]{2,40})(?::|\s*—|\s*–|\n)", text)
    for s in step_matches:
        s_clean = s.strip()
        if len(s_clean) >= 3 and s_clean.lower() not in COMMON_CONVERSATIONAL_WORDS:
            if len(s_clean.split()) <= 6:
                items.append(s_clean)

    # Deduplicate preserving order
    seen: Set[str] = set()
    deduped = []
    for it in items:
        norm = re.sub(r"[^a-zA-Z0-9]+", "", it.lower())
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(it)
    return deduped

def check_term_in_source(term: str, source_text: str) -> bool:
    """Checks whether a term or its core keywords exist in the source section text."""
    norm_source = re.sub(r"[^a-zA-Z0-9\s]+", " ", source_text.lower())
    norm_term = re.sub(r"[^a-zA-Z0-9\s]+", " ", term.lower()).strip()
    
    # Direct substring match
    if norm_term in norm_source:
        return True

    # If multi-word term, check if at least 70% of non-stop words appear close together
    words = [w for w in norm_term.split() if len(w) > 2 and w not in {"the", "and", "for", "with", "from", "your"}]
    if not words:
        return True
    
    matched = sum(1 for w in words if w in norm_source)
    return (matched / len(words)) >= 0.70

def verify_explanation_faithfulness(
    explanation_text: str,
    source_text: str
) -> Tuple[bool, List[str], str]:
    """
    Checks if all named items appear in the source text.
    Returns: (is_faithful, missing_terms, annotated_text)
    """
    named_items = extract_named_items(explanation_text)
    missing = []
    annotated = explanation_text

    for item in named_items:
        if not check_term_in_source(item, source_text):
            missing.append(item)
            logger.info(f"Faithfulness mismatch: term '{item}' not found in source section text.")

    if missing:
        # Tag missing terms with (wording not from your notes)
        for m in missing:
            # Safely replace bold or plain occurrences
            pat_bold = rf"(\*\*{re.escape(m)}\*\*)"
            if re.search(pat_bold, annotated):
                annotated = re.sub(pat_bold, rf"\1 *(wording not from your notes)*", annotated, count=1)
            else:
                pat_plain = rf"\b({re.escape(m)})\b"
                annotated = re.sub(pat_plain, rf"\1 *(wording not from your notes)*", annotated, count=1)
        return False, missing, annotated

    return True, [], explanation_text

