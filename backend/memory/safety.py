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


# Memory Quality Patterns (Part 5)
MOOD_MENTAL_HEALTH_PATTERNS = [
    r"(?i)\b(?:feel(?:ing)?\s+(?:low|lost|sad|depressed|anxious|hopeless|down|bad|lonely|heartbroken|empty|worthless|numb))\b",
    r"(?i)\b(?:depression|depressed|anxiety|anxious|panic(?:\s+attack)?|hopeless(?:ness)?|suicid\w*|kill\s+myself|end\s+my\s+life|self-?harm|hurting\s+myself|want\s+to\s+die|nothing\s+matters|burnout|burned\s+out|overthinking|overwhelmed|nervous\s+breakdown|crying|lonely|loneliness|unhappy|miserable|hate\s+myself|can'?t\s+go\s+on|can'?t\s+take\s+this|tired\s+of\s+living|low\s+mood)\b",
    r"(?i)\b(?:doctor|hospital|clinic|physician|therapist|psychiatrist|counselor|medication|prescribed|prescription|pills|diagnosis|diagnosed|disease|illness|infection|cancer|diabetes|blood\s+pressure|fever|cough|chest\s+pain|chronic\s+pain|surgery|biopsy|medical\s+condition|sick|injury|injured|tumor|symptom\w*)\b",
]

TEMPORARY_STATE_PATTERNS = [
    r"(?i)\b(?:tired(?:\s+after|\s+from)?|exhausted|sleepy|hungry|thirsty|busy|bored|starving|headache|fatigued|drained|restless)\b",
    r"(?i)\b(?:working\s+on\s+it\s+now|doing\s+this\s+now|eating|drinking|sitting|standing|waking\s+up|going\s+to\s+sleep|going\s+to\s+bed|on\s+my\s+way)\b",
]

TIME_REFERENCE_PATTERNS = [
    r"(?i)\b(?:today|tomorrow|yesterday|tonight)\b",
    r"(?i)\bthis\s+(?:morning|afternoon|evening|night|week|weekend|month|year)\b",
    r"(?i)\bnext\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"(?i)\blast\s+(?:night|week|month|year)\b",
    r"(?i)\b(?:right\s+now|at\s+the\s+moment|currently|earlier\s+today|just\s+now)\b",
]

UNRESOLVED_PRONOUN_PATTERNS = [
    r"(?i)\b(?:it|this|that|them|they|these|those)\b"
]


def is_mood_or_health_statement(text: str) -> bool:
    """Checks if text mentions mood, mental state, or health statements."""
    if not text:
        return False
    return any(bool(re.search(pat, text)) for pat in MOOD_MENTAL_HEALTH_PATTERNS)


def is_temporary_state(text: str) -> bool:
    """Checks if text contains temporary states or fleeting conditions."""
    if not text:
        return False
    return any(bool(re.search(pat, text)) for pat in TEMPORARY_STATE_PATTERNS)


def contains_time_reference(text: str) -> bool:
    """Checks if text contains relative time references like today, tomorrow, etc."""
    if not text:
        return False
    return any(bool(re.search(pat, text)) for pat in TIME_REFERENCE_PATTERNS)


def is_verbatim_copy(fact: str, user_message: str) -> bool:
    """Checks if the fact candidate is simply the user's message copied word-for-word."""
    if not fact or not user_message:
        return False
    clean_fact = re.sub(r"[^\w\s]", "", fact).strip().lower()
    clean_user = re.sub(r"[^\w\s]", "", user_message).strip().lower()
    return clean_fact == clean_user


def format_to_third_person(text: str) -> str:
    """
    Transforms first-person statements to concise third-person phrasing with plain wording.
    E.g.
    'I want to build an LLM' -> 'Wants to build an LLM'
    'I cook for myself' -> 'Cooks for himself'
    'My laptop has 6 GB VRAM' -> 'Laptop has 6 GB VRAM'
    """
    if not text:
        return text
    clean = text.strip()

    # Reflexive & object pronouns
    clean = re.sub(r"(?i)\bmyself\b", "himself", clean)
    clean = re.sub(r"(?i)\bme\b", "him", clean)

    # Possessives: 'my ...' at start
    m_my = re.match(r"(?i)^my\s+(.*)$", clean)
    if m_my:
        rest = m_my.group(1)
        clean = rest[0].upper() + rest[1:] if rest else ""

    # Common verb prefixes
    clean = re.sub(r"(?i)^i\s+want\s+to\s+", "Wants to ", clean)
    clean = re.sub(r"(?i)^i\s+need\s+to\s+", "Needs to ", clean)
    clean = re.sub(r"(?i)^i\s+would\s+like\s+to\s+", "Wants to ", clean)
    clean = re.sub(r"(?i)^i\s+plan\s+to\s+", "Plans to ", clean)
    clean = re.sub(r"(?i)^i\s+hope\s+to\s+", "Hopes to ", clean)
    clean = re.sub(r"(?i)^i\s+prefer\s+to\s+", "Prefers to ", clean)
    clean = re.sub(r"(?i)^i\s+like\s+to\s+", "Likes to ", clean)
    clean = re.sub(r"(?i)^i\s+love\s+to\s+", "Loves to ", clean)
    clean = re.sub(r"(?i)^i\s+am\s+", "Is ", clean)
    clean = re.sub(r"(?i)^i'?m\s+", "Is ", clean)
    clean = re.sub(r"(?i)^i\s+have\s+been\s+", "Has been ", clean)
    clean = re.sub(r"(?i)^i\s+have\s+", "Has ", clean)
    clean = re.sub(r"(?i)^i'?ve\s+", "Has ", clean)
    clean = re.sub(r"(?i)^i\s+use\s+", "Uses ", clean)
    clean = re.sub(r"(?i)^i\s+cook\s+for\s+", "Cooks for ", clean)
    clean = re.sub(r"(?i)^i\s+cook\s+", "Cooks ", clean)
    clean = re.sub(r"(?i)^i\s+code\s+in\s+", "Codes in ", clean)
    clean = re.sub(r"(?i)^i\s+code\s+", "Codes ", clean)
    clean = re.sub(r"(?i)^i\s+work\s+", "Works ", clean)
    clean = re.sub(r"(?i)^i\s+program\s+in\s+", "Programs in ", clean)
    clean = re.sub(r"(?i)^i\s+live\s+in\s+", "Lives in ", clean)
    clean = re.sub(r"(?i)^i\s+speak\s+", "Speaks ", clean)
    clean = re.sub(r"(?i)^i\s+drink\s+", "Drinks ", clean)
    clean = re.sub(r"(?i)^i\s+study\s+", "Studies ", clean)
    clean = re.sub(r"(?i)^i\s+prefer\s+", "Prefers ", clean)
    clean = re.sub(r"(?i)^i\s+like\s+", "Likes ", clean)
    clean = re.sub(r"(?i)^i\s+love\s+", "Loves ", clean)
    clean = re.sub(r"(?i)^i\s+own\s+", "Owns ", clean)
    clean = re.sub(r"(?i)^i\s+build\s+", "Builds ", clean)

    # Strip "The owner " or "Owner " prefix if redundant
    clean = re.sub(r"(?i)^(?:the\s+)?owner\s+(?:is|has|uses|prefers|wants|works)\s+", lambda m: m.group(0).split()[-1].capitalize() + " ", clean)

    # General fallback for "^I ([a-z]+) "
    m_i = re.match(r"(?i)^i\s+([a-z]+)\s+(.*)$", clean)
    if m_i:
        verb = m_i.group(1).lower()
        rest = m_i.group(2)
        if verb.endswith("y") and verb not in ("play", "stay", "buy", "enjoy"):
            third_verb = verb[:-1] + "ies"
        elif verb.endswith(("s", "sh", "ch", "x", "z", "o")):
            third_verb = verb + "es"
        else:
            third_verb = verb + "s"
        clean = f"{third_verb.capitalize()} {rest}"

    return clean


def resolve_pronouns_in_fact(fact: str, user_message: str = "", context: str = "") -> Tuple[str, bool]:
    """
    Attempts to resolve pronouns like 'it' or 'this' in a fact using user message context.
    E.g. If user said 'I want to build an LLM model and open source it'
    and fact is 'Wants to open source it', resolves to 'Wants to open source the LLM model'.
    Returns (resolved_fact, is_fully_resolved).
    """
    if not fact:
        return fact, False

    # Check if fact contains any unresolved pronouns
    has_pronoun = any(bool(re.search(pat, fact)) for pat in UNRESOLVED_PRONOUN_PATTERNS)
    if not has_pronoun:
        return fact, True

    combined_ctx = f"{user_message} {context}".strip()
    if not combined_ctx:
        return fact, False

    # Try to identify an entity/noun phrase from the user context
    # E.g. build an LLM model -> LLM model
    NON_ENTITY_WORDS = {
        "it", "this", "that", "something", "anything", "nothing", "things",
        "lot", "a lot", "bit", "a bit", "little", "while", "few", "time", "day", "way"
    }

    entity = None
    m_action = re.search(r"(?i)\b(?:build|train|make|create|develop|write|code|design|deploy)\s+(?:an?|the)?\s*([a-zA-Z0-9_\- ]{2,30}?)(?:\s+(?:and|to|so|,|\.|$))", combined_ctx)
    if m_action:
        candidate_entity = m_action.group(1).strip()
        # Avoid generic verbs/pronouns/adverbials
        if candidate_entity.lower() not in NON_ENTITY_WORDS and candidate_entity.lower() != "model":
            entity = candidate_entity
        elif candidate_entity.lower() == "model":
            # look for preceding acronym/adjective e.g. "LLM model"
            m_model = re.search(r"(?i)\b([a-zA-Z0-9_\-]+\s+model)\b", combined_ctx)
            if m_model:
                entity = m_model.group(1).strip()
            else:
                entity = "the model"

    if not entity:
        # Search for capitalized or acronym nouns e.g. "an LLM", "a REST API", "Ollama"
        m_noun = re.search(r"(?i)\b(?:an?|the)\s+([A-Z0-9_\-]{2,}(?:\s+[a-zA-Z0-9_\-]+)?)\b", combined_ctx)
        if m_noun:
            candidate = m_noun.group(1).strip()
            if candidate.lower() not in NON_ENTITY_WORDS:
                entity = candidate

    if entity:
        resolved = re.sub(r"(?i)\b(?:it|this|that)\b", f"the {entity}", fact).strip()
        # Ensure no remaining unresolved pronouns
        if not any(bool(re.search(pat, resolved)) for pat in UNRESOLVED_PRONOUN_PATTERNS):
            return resolved, True
        return resolved, False

    return fact, False


def validate_memory_quality(fact: str, user_message: str = "", context: str = "") -> Tuple[bool, str, str]:
    """
    Validates a candidate memory fact against all quality rules:
    - Never store mood, mental-state, or health statements
    - Never store temporary states
    - Anything with a time reference is not a memory
    - Write every memory in third person with plain wording
    - Resolve pronouns from conversation; if cannot be resolved, reject
    - Do not store user message word-for-word
    Returns (is_valid, processed_fact, rejection_reason).
    """
    if not fact or len(fact.strip()) < 4:
        return False, "", "Empty or too short"

    clean = fact.strip()

    # Rule 1: Never store mood, mental-state, or health statements
    if is_mood_or_health_statement(clean):
        return False, "", "Mood, mental-state, or health statement"

    # Rule 2: Never store temporary states or fleeting conditions
    if is_temporary_state(clean):
        return False, "", "Temporary state or fleeting mood"

    # Rule 3: Anything with a time reference is not a memory
    if contains_time_reference(clean):
        return False, "", "Contains time reference"

    # Rule 4: Do not store user message word for word
    if is_verbatim_copy(clean, user_message):
        return False, "", "Verbatim copy of user message"

    # Rule 5: Format to third person
    third_person_fact = format_to_third_person(clean)

    # Rule 6: Resolve pronouns; if unresolvable, reject
    resolved_fact, is_resolved = resolve_pronouns_in_fact(third_person_fact, user_message=user_message, context=context)
    if not is_resolved:
        return False, "", "Contains unresolved pronoun"

    return True, resolved_fact, ""

