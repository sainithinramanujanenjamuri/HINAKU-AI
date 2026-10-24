import re
from datetime import datetime
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
    r"(?i)\blatest\b\s+(?:news|headlines|score|stock\s+price)\b"
]

CLOCK_DATETIME_PATTERNS = [
    r"(?i)\b(?:what\s+(?:is\s+the\s+)?(?:date\s+and\s+time|time\s+and\s+date)|current\s+(?:date\s+and\s+time|time\s+and\s+date))\b",
]

CLOCK_DATE_PATTERNS = [
    r"(?i)\b(?:what\s+is\s+today'?s?\s+date|what\s+date\s+is\s+(?:it|today)|today'?s?\s+date|current\s+date)\b",
    r"(?i)\b(?:what'?s?\s+the\s+date\s+today|date\s+today)\b",
]

CLOCK_DAY_PATTERNS = [
    r"(?i)\b(?:what\s+day\s+is\s+(?:it|today)|which\s+day\s+is\s+(?:it|today)|what\s+day\s+of\s+the\s+week\s+is\s+it)\b",
    r"(?i)\b(?:what\s+is\s+today'?s?\s+day|day\s+of\s+(?:the\s+)?week)\b",
]

CLOCK_TIME_PATTERNS = [
    r"(?i)\b(?:what\s+time\s+is\s+it|what'?s?\s+the\s+time|current\s+time|time\s+right\s+now|time\s+now)\b",
]

def is_clock_query(text: str) -> bool:
    """Checks if a user query is asking for the current day, date, or time from the system clock."""
    if not text:
        return False
    clean = text.strip()
    all_patterns = CLOCK_DATETIME_PATTERNS + CLOCK_DAY_PATTERNS + CLOCK_DATE_PATTERNS + CLOCK_TIME_PATTERNS
    return any(re.search(pat, clean) for pat in all_patterns)

def get_clock_reply(text: str, dt: Optional[datetime] = None) -> Optional[str]:
    """
    Answers questions about current day, date, or time directly from the system clock.
    Returns None if the query is not a clock query.
    """
    if not text:
        return None
    clean = text.strip()
    now = dt or datetime.now().astimezone()

    # Check combined date + time first
    if any(re.search(pat, clean) for pat in CLOCK_DATETIME_PATTERNS):
        return f"Today is {now.strftime('%A, %B %d, %Y')}. It is {now.strftime('%I:%M %p').lstrip('0')}."

    # Check day only
    is_day = any(re.search(pat, clean) for pat in CLOCK_DAY_PATTERNS)
    # Check date only
    is_date = any(re.search(pat, clean) for pat in CLOCK_DATE_PATTERNS)
    # Check time only
    is_time = any(re.search(pat, clean) for pat in CLOCK_TIME_PATTERNS)

    if is_day and not is_time and not is_date:
        return f"Today is {now.strftime('%A')}."
    if is_date and not is_time:
        return f"Today is {now.strftime('%B %d, %Y')}."
    if is_time and not is_date and not is_day:
        return f"It is {now.strftime('%I:%M %p').lstrip('0')}."
    if is_day or is_date or is_time:
        return f"Today is {now.strftime('%A, %B %d, %Y')}. It is {now.strftime('%I:%M %p').lstrip('0')}."

    return None

def get_system_clock_context(dt: Optional[datetime] = None) -> str:
    """Formats current local date, day of week, and time for injection into system context."""
    now = dt or datetime.now().astimezone()
    weekday = now.strftime("%A")
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p").lstrip("0")
    tz_name = now.tzname() or ""
    tz_part = f" ({tz_name})" if tz_name else ""
    return f"Current local time: {weekday}, {date_str} {time_str}{tz_part}."

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


DETAIL_PATTERNS = [
    r"(?i)\b(?:in\s+more\s+detail|in\s+detail|in-depth|in\s+depth|longer\s+explanation|longer|more\s+detail|elaborate|explain\s+more|step\s+by\s+step|step-by-step|deep\s+dive|detailed|break\s+it\s+down\s+more)\b",
]

SHORT_FOLLOWUP_DETAIL_WORDS = {
    "more", "go on", "continue", "keep going", "elaborate", "expand", "longer"
}

def is_detail_request(text: str) -> bool:
    """
    Checks if a user query asks for more detail, a longer explanation,
    an in-depth answer, or is a short follow-up like 'more' or 'go on'.
    """
    if not text:
        return False
    clean = text.strip().lower()
    clean_stripped = re.sub(r"[^\w\s]", "", clean).strip()
    if clean_stripped in SHORT_FOLLOWUP_DETAIL_WORDS:
        return True
    return any(re.search(pat, clean) for pat in DETAIL_PATTERNS)

def trim_to_last_complete_sentence(text: str) -> Tuple[str, bool]:
    """
    If a text ends mid-sentence (e.g. cut off by token limit),
    trims it back to the last complete sentence boundary.
    Returns (trimmed_text, was_cut).
    """
    if not text or not text.strip():
        return text, False
    stripped = text.rstrip()
    # Sentence ending punctuation followed optionally by quotes or parens
    if re.search(r'[.!?]["\')\]]?$', stripped):
        return stripped, False

    matches = list(re.finditer(r'[.!?]["\')\]]?(?:\s+|$)', stripped))
    if not matches:
        return stripped, False

    last_match = matches[-1]
    trimmed = stripped[:last_match.end()].rstrip()
    return trimmed, True


SENSITIVE_TOPIC_PATTERNS = {
    "mental_health": [
        r"(?i)\b(?:mental\s+health|depression|depressed|anxiety|anxious|panic(?:\s+attack)?|feeling\s+low|feel\s+low|feeling\s+lost|feel\s+lost|feeling\s+sad|feel\s+sad|hopeless(?:ness)?|suicid\w*|kill\s+myself|end\s+my\s+life|self-?harm|hurting\s+myself|want\s+to\s+die|nothing\s+matters|burnout|burned\s+out|overthinking|overwhelmed|nervous\s+breakdown|crying|lonely|loneliness|unhappy|miserable|hate\s+myself|can'?t\s+go\s+on|can'?t\s+take\s+this|tired\s+of\s+living|low\s+mood)\b"
    ],
    "mood": [
        r"(?i)\b(?:bad\s+mood|terrible\s+mood|foul\s+mood|low\s+mood|feeling\s+down|feeling\s+empty|feeling\s+broken|feeling\s+worthless|feeling\s+numb|feeling\s+hopeless)\b"
    ],
    "health": [
        r"(?i)\b(?:doctor|hospital|clinic|physician|therapist|psychiatrist|counselor|medication|prescribed|prescription|pills|diagnosis|diagnosed|disease|illness|infection|cancer|diabetes|blood\s+pressure|fever|cough|chest\s+pain|chronic\s+pain|surgery|biopsy|medical\s+condition|sick|injury|injured|tumor|symptom\w*)\b"
    ],
    "money_trouble": [
        r"(?i)\b(?:broke(?!\s+up\b)|out\s+of\s+money|can'?t\s+afford|cannot\s+afford|can'?t\s+pay\s+rent|cannot\s+pay\s+rent|in\s+debt|massive\s+debt|bankruptcy|bankrupt|foreclosure|eviction|evicted|losing\s+money|financial\s+(?:crisis|trouble|ruin|struggle)|defaulted\s+on\s+loan|no\s+money\s+for\s+food|unemployed|lost\s+my\s+job|laid\s+off|behind\s+on\s+bills)\b"
    ],
    "personal_relationships": [
        r"(?i)\b(?:breakup|broke\s+up|divorce|divorced|divorcing|separation|separated\s+from\s+(?:wife|husband|partner)|cheating\s+on|cheated\s+on|toxic\s+relationship|abusive\s+relationship|fight\s+with\s+(?:my\s+)?(?:wife|husband|partner|girlfriend|boyfriend|parents|mom|dad|family)|family\s+dispute|child\s+custody|heartbreak|heartbroken|estranged)\b"
    ]
}

def is_sensitive_topic(text: str) -> Tuple[bool, str]:
    """
    Checks if a user query is about mental health, mood, health,
    money trouble, or personal relationships.
    Returns (is_sensitive, category_name).
    """
    if not text:
        return False, ""
    clean = text.strip()
    for cat, patterns in SENSITIVE_TOPIC_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, clean):
                return True, cat
    return False, ""
