"""
backend/attachments/style_checker.py

Enforces study style and count consistency for document walkthrough topics:
1. Style verification:
   - Ensures each topic has a concise explanation
   - Exactly one "*Example (analogous)*:"
   - "Exam-Oriented Key Takeaways" (at least 2 bullets)
   - If either is missing, generates ONLY the missing component with a targeted short call
     without redacting or regenerating the existing explanation.
2. Count consistency:
   - Detects "N stages/phases/types/steps/pillars" statements
   - Compares N with the actual number of listed bullet/numbered items
   - Corrects N in code to match the actual items listed (or flags for regeneration).
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hinaku.attachments.style_checker")

WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12
}
NUM_TO_WORD = {v: k for k, v in WORD_TO_NUM.items()}

COUNT_STATEMENT_PATTERN = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+"
    r"(distinct\s+)?(stages|phases|types|steps|pillars|categories|principles|components|tiers|layers|classes)\b",
    re.IGNORECASE
)

def check_study_style(explanation_text: str) -> Dict[str, Any]:
    """
    Checks if the topic explanation contains:
    - One '*Example (analogous)*:'
    - 'Exam-Oriented Key Takeaways' with 2 bullets
    Returns dict with booleans and list of missing parts.
    """
    # 1. Check for Example (analogous)
    has_example = bool(
        re.search(r"(?i)\*?Example\s*\(analogous\)\*?:", explanation_text) or
        re.search(r"(?i)\*\*Example\s*\(analogous\)\*\*:", explanation_text) or
        re.search(r"(?i)Example\s*\(analogous\)", explanation_text)
    )

    # 2. Check for Exam-Oriented Key Takeaways
    takeaways_match = re.search(r"(?i)Exam-Oriented\s+Key\s+Takeaways", explanation_text)
    has_takeaways = False
    if takeaways_match:
        # Check text following the heading for at least 2 bullet/numbered items
        after_heading = explanation_text[takeaways_match.end():]
        bullets = re.findall(r"(?:^|\n)\s*(?:[*+-]|\d+\.)\s+[^\n]+", after_heading)
        if len(bullets) >= 2:
            has_takeaways = True

    missing_parts = []
    if not has_example:
        missing_parts.append("example")
    if not has_takeaways:
        missing_parts.append("takeaways")

    return {
        "has_example": has_example,
        "has_takeaways": has_takeaways,
        "is_complete": len(missing_parts) == 0,
        "missing_parts": missing_parts
    }

def build_addendum_prompt(
    missing_parts: List[str],
    sec_title: str,
    sec_text: str,
    existing_explanation: str
) -> str:
    """
    Constructs a minimal targeted prompt to generate ONLY the missing study aids
    using the section text and the explanation already produced.
    """
    instructions = []
    if "example" in missing_parts:
        instructions.append(
            "1. Exactly ONE concrete real-world analogous example (e.g. from everyday systems, games, or physical security):\n"
            "   *Example (analogous)*: <your clear analogous example here>"
        )
    if "takeaways" in missing_parts:
        instructions.append(
            f"{'2' if 'example' in missing_parts else '1'}. Exactly TWO exam-oriented key takeaways:\n"
            "   **Exam-Oriented Key Takeaways**\n"
            "   * <Key exam takeaway or definition 1>\n"
            "   * <Key exam takeaway or definition 2>"
        )

    task_desc = "\n\n".join(instructions)

    return (
        f"Topic Title: {sec_title}\n\n"
        f"Section Notes Text:\n{sec_text}\n\n"
        f"Explanation Already Produced:\n{existing_explanation}\n\n"
        f"IMPORTANT INSTRUCTIONS:\n"
        f"Generate ONLY the missing study components listed below. "
        f"Do NOT repeat, rewrite, or summarize the explanation already produced.\n\n"
        f"{task_desc}\n\n"
        f"Begin directly with the missing components."
    )

def check_and_fix_count_consistency(explanation_text: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Detects statements like 'three distinct phases' followed by list items.
    If claimed count N != actual listed items M, corrects N to M in the text.
    Returns: (was_modified, fixed_text, list_of_fixes)
    """
    fixes = []
    
    # Split text into paragraphs
    paragraphs = explanation_text.split("\n\n")
    modified_paragraphs = []
    overall_modified = False

    for para in paragraphs:
        match = COUNT_STATEMENT_PATTERN.search(para)
        if not match:
            modified_paragraphs.append(para)
            continue

        full_statement = match.group(0)
        num_str = match.group(1).lower()
        distinct_str = match.group(2) or ""
        noun_str = match.group(3)

        claimed = WORD_TO_NUM.get(num_str)
        if claimed is None:
            try:
                claimed = int(num_str)
            except ValueError:
                modified_paragraphs.append(para)
                continue

        # Count bullets in the paragraph or subsequent lines
        after_stmt = para[match.end():]
        bullets = re.findall(r"(?:^|\n)\s*(?:[*+-]|\d+\.)\s+", after_stmt)
        actual = len(bullets)

        if actual > 0 and actual != claimed:
            new_num_word = NUM_TO_WORD.get(actual, str(actual))
            if match.group(1)[0].isupper():
                new_num_word = new_num_word.capitalize()

            fixed_stmt = f"{new_num_word} {distinct_str}{noun_str}"
            fixed_para = para[:match.start()] + fixed_stmt + para[match.end():]
            modified_paragraphs.append(fixed_para)
            overall_modified = True
            fixes.append({
                "original": full_statement,
                "fixed": fixed_stmt,
                "claimed": claimed,
                "actual": actual
            })
            logger.info(f"Count consistency fix: '{full_statement}' -> '{fixed_stmt}' (actual items: {actual})")
        else:
            modified_paragraphs.append(para)

    fixed_text = "\n\n".join(modified_paragraphs)
    return overall_modified, fixed_text, fixes

