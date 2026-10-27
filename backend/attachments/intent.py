"""
backend/attachments/intent.py

Deterministic intent routing for document queries:
- Distinguishes OVERVIEW requests (walkthrough, explain whole document, study guide)
  from SPECIFIC inquiries (targeted questions, definitions).
- Pure code pattern matching (regex) - zero model inference cost or latency.
"""

import re
from typing import Optional

OVERVIEW_PATTERNS = [
    # Explicit overview phrases: explain this, explain the pdf, summarize the notes
    r"(?i)\b(?:explain|walk\s*me\s*through|summarize|summary|overview|break\s*down|teach\s*me|study\s*guide|review)\b.*\b(?:this|the\s*(?:pdf|doc|document|notes|file|material)|all|whole|everything)\b",
    # Direct short requests: explain this, explain pdf, summarize, walk me through
    r"(?i)^(?:explain\s*(?:this|the\s*(?:pdf|doc|document|notes|file)|everything)?|summarize(?:\s*it|\s*this|\s*the\s*pdf)?|walk\s*me\s*through(?:\s*this)?|what\s+is\s+this(?:\s+about)?)$",
    # Unit / continuation triggers: explain unit 1, continue to unit 2
    r"(?i)\b(?:explain\s+the\s+whole\s+document|explain\s+unit\s+\d+|continue\s+to\s+unit\s+\d+|unit\s+\d+\s+walkthrough)\b",
    # Single word overview
    r"(?i)^(?:explain|overview|summary|walkthrough|notes)$"
]

def is_overview_intent(query_text: str) -> bool:
    """Returns True if the user is asking for a comprehensive walkthrough / overview of the document."""
    q = query_text.strip().lower()
    for pat in OVERVIEW_PATTERNS:
        if re.search(pat, q):
            return True
    return False

def extract_target_unit(query_text: str) -> Optional[int]:
    """Extracts explicit unit number from request like 'continue to unit 2' or 'explain unit 1'."""
    m = re.search(r"(?i)unit\s+(\d+)", query_text)
    if m:
        return int(m.group(1))
    return None

