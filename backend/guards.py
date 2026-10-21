import re
from typing import List, Optional, Tuple

SENSITIVE_REPLACEMENTS = [
    # Explicit PIN declarations: e.g. "my pin is 1234", "pin: 1234", "pin is 1234"
    (r"(?i)(\b(?:my\s+(?:card\s+|atm\s+)?pin\s+is\s+))\d{3,8}\b", r"\1[removed]"),
    (r"(?i)(\b(?:card\s*pin|atm\s*pin|pin\s*code)\s*(?:[:=]|is)\s*)\d{3,8}\b", r"\1[removed]"),
    (r"(?i)(\bpin\s*(?:[:=]|is)\s*)\d{3,8}\b", r"\1[removed]"),

    # Password declarations: e.g. "my password is secret", "password: secret"
    (r"(?i)(\bmy\s+password\s+is\s+)\S+", r"\1[removed]"),
    (r"(?i)(\b(?:password|passwd|pwd|passcode)\s*(?:[:=]|is)\s*)\S+", r"\1[removed]"),
    (r"(?i)(\bmaster\s+password\s*(?:[:=]|is)\s*)\S+", r"\1[removed]"),

    # Card numbers (13-19 digits, with spaces or hyphens)
    (r"(?i)(\b(?:credit\s*card|debit\s*card|card\s*number)\s*(?:[:=]|is)?\s*)[\d -]{13,19}\b", r"\1[removed]"),
    (r"\b(?:\d{4}[ -]?){3}\d{4}\b", "[removed]"),
    (r"\b3[47]\d{2}[ -]?\d{6}[ -]?\d{5}\b", "[removed]"),

    # Bank account numbers / IBAN / routing
    (r"(?i)(\b(?:bank\s+account|account\s+number|iban|routing\s+number)\s*(?:[:=]|is)?\s*)[A-Z0-9-]{8,34}\b", r"\1[removed]"),

    # Government ID numbers (SSN, Aadhaar, PAN, Passport)
    (r"(?i)(\b(?:ssn|social\s+security(?:\s+number)?)\s*(?:[:=]|is)?\s*)\d{3}-?\d{2}-?\d{4}\b", r"\1[removed]"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "[removed]"),
    (r"(?i)(\baadhaar\s*(?:[:=]|is)?\s*)\d{4}\s?\d{4}\s?\d{4}\b", r"\1[removed]"),
    (r"\b\d{4}\s\d{4}\s\d{4}\b", "[removed]"),
    (r"(?i)(\bpan(?:\s+card)?\s*(?:[:=]|is)?\s*)[A-Z]{5}[0-9]{4}[A-Z]\b", r"\1[removed]"),
    (r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "[removed]"),
    (r"(?i)(\bpassport(?:\s*(?:number|num|#))?\s*(?:[:=]|is)?\s*)[A-PR-WYa-pr-wy][1-9]\d\s?\d{4}[1-9]\b", r"\1[removed]"),
    (r"(?i)(\bpassport(?:\s*(?:number|num|#))?\s*(?:[:=]|is)?\s*)[A-Z0-9]{7,10}\b", r"\1[removed]"),

    # API keys / tokens
    (r"\b(?:sk-[a-zA-Z0-9_\-]{20,}|ghp_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9]{20,}|xox[baprs]-[a-zA-Z0-9]{10,})\b", "[removed]"),
    (r"\bAIza[0-9A-Za-z-_]{35}\b", "[removed]"),
]

DEFAULT_LIVE_DATA_PATTERNS = [
    r"(?i)\b(?:current|latest|today'?s?|yesterday'?s?|live)\b.*\b(?:stock|share|crypto|bitcoin|btc|eth|market|price|quote|close|closing)\b",
    r"(?i)\b(?:what\s+is|what's|how\s+much\s+is)\b.*\b(?:stock|share|crypto|bitcoin|btc|eth|market)\s+(?:price|value|worth)\b",
    r"(?i)\b(?:what\s+was)\b.*\b(?:closing\s+price|market\s+close)\b",
    r"(?i)\b(?:nvidia'?s?|apple'?s?|tesla'?s?|google'?s?|microsoft'?s?)\s+(?:closing\s+price|stock\s+price|current\s+price)\b",
    r"(?i)\b(?:what\s+is\s+the\s+weather|current\s+weather|weather\s+today|weather\s+forecast|is\s+it\s+raining\s+outside|temperature\s+outside)\b",
    r"(?i)\b(?:today'?s?|current|breaking|latest)\s+(?:news|headlines)\b",
    r"(?i)\b(?:score\s+of|who\s+won)\b.*\b(?:game|match|today|yesterday|super\s*bowl|world\s*cup|nba|ipl)\b",
    r"(?i)\b(?:what\s+(?:time|day|date)\s+is\s+it|what\s+is\s+today'?s?\s+date|current\s+time)\b",
    r"(?i)\blatest\b\s+(?:news|headlines|score|stock\s+price)\b"
]

def check_and_redact_sensitive_data(text: str) -> Tuple[bool, str]:
    """
    Checks if a user message contains sensitive data (PIN, password, card number,
    account number, government ID, api keys).
    If found, replaces the sensitive portion with '[removed]' and returns (True, redacted_text).
    If clean, returns (False, text).
    """
    if not text:
        return False, text

    redacted = text
    detected = False

    for pattern, replacement in SENSITIVE_REPLACEMENTS:
        new_text, count = re.subn(pattern, replacement, redacted)
        if count > 0:
            detected = True
            redacted = new_text

    return detected, redacted

def is_live_data_query(text: str, custom_patterns: Optional[List[str]] = None) -> bool:
    """
    Checks if a query requires live, real-time data (stock prices, weather, news,
    scores, current time/date) that HINAKU cannot know without internet/live tools.
    Protects against false positives (e.g. 'what is a stock?' goes to model).
    """
    if not text:
        return False

    clean = text.strip()
    patterns = custom_patterns or DEFAULT_LIVE_DATA_PATTERNS

    # Explicit whitelist/false-positive filter
    educational_patterns = [
        r"(?i)^what\s+is\s+(?:a|an)\s+(?:stock|share|bond|mutual\s+fund|cryptocurrency|bitcoin)\??$",
        r"(?i)^how\s+do(?:es)?\s+(?:the\s+)?(?:stock\s+market|cryptocurrency|weather\s+forecasting)\s+work\??$",
        r"(?i)^explain\s+(?:how\s+)?(?:stocks|weather\s+models|crypto|blockchain)\s+(?:work|functions)\b",
        r"(?i)^definition\s+of\s+\S+",
    ]
    for edu in educational_patterns:
        if re.search(edu, clean):
            return False

    for pat in patterns:
        if re.search(pat, clean):
            return True

    return False
