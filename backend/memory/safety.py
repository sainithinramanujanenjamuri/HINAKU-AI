import re
import logging
from typing import List, Tuple

logger = logging.getLogger("hinaku.memory.safety")

# Patterns for memory.never_store
NEVER_STORE_PATTERNS = {
    "passwords": [
        r"(?i)\b(?:password|passwd|pwd|passcode)\b\s*[:=]?\s*\S+",
        r"(?i)\bmy\s+password\s+is\s+\S+",
        r"(?i)\bmaster\s+password\b\s*[:=]?\s*\S+",
    ],
    "api_keys": [
        r"\b(?:sk-[a-zA-Z0-9_\-]{20,}|ghp_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9]{20,}|xox[baprs]-[a-zA-Z0-9]{10,})\b",
        r"(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token|bearer|private[_-]?key)\b\s*[:=]?\s*['\"]?[a-zA-Z0-9_\-\.]{16,}['\"]?",
        r"\bAIza[0-9A-Za-z-_]{35}\b",
    ],
    "government_id_numbers": [
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"(?i)\b(?:ssn|social\s+security(?:\s+number)?)\b\s*[:=]?\s*\d{3}-?\d{2}-?\d{4}\b",
        r"\b\d{4}\s\d{4}\s\d{4}\b",  # Aadhaar format
        r"(?i)\baadhaar\b\s*[:=]?\s*\d{4}\s?\d{4}\s?\d{4}\b",
        r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",  # Indian PAN
        r"(?i)\bpassport(?:\s*(?:number|num|#))?\s*[:=]?\s*[A-PR-WYa-pr-wy][1-9]\d\s?\d{4}[1-9]\b",
        r"(?i)\bpassport(?:\s*(?:number|num|#))?\s*[:=]?\s*[A-Z0-9]{7,10}\b",
    ],
    "bank_or_card_numbers": [
        r"\b(?:\d{4}[ -]?){3}\d{4}\b",  # 16-digit credit cards
        r"\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b",  # Amex 15-digit
        r"(?i)\b(?:credit\s*card|debit\s*card|card\s*number)\b\s*[:=]?\s*[\d -]{13,19}\b",
        r"(?i)\b(?:bank\s+account|account\s+number|iban|routing\s+number)\b\s*[:=]?\s*[A-Z0-9-]{8,34}\b",
    ]
}

def is_safe_to_store(text: str, categories: List[str] = None) -> Tuple[bool, str]:
    """
    Checks if a text contains any confidential data (passwords, api keys, govt IDs, bank cards).
    Returns (True, "") if safe, or (False, reason) if prohibited.
    """
    if not text:
        return True, ""

    cats_to_check = categories or list(NEVER_STORE_PATTERNS.keys())

    for cat in cats_to_check:
        patterns = NEVER_STORE_PATTERNS.get(cat, [])
        for pat in patterns:
            if re.search(pat, text):
                logger.warning(f"Memory safety filter blocked entry due to category '{cat}'")
                return False, f"Contains forbidden data ({cat})"

    return True, ""

def filter_safe_facts(facts: List[str], categories: List[str] = None) -> List[str]:
    """
    Filters out any facts that fail the safety filter.
    """
    safe = []
    for f in facts:
        is_safe, reason = is_safe_to_store(f, categories)
        if is_safe:
            safe.append(f)
        else:
            logger.info(f"Dropped unsafe memory candidate: {reason}")
    return safe

