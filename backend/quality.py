"""
Quality Mode and Deterministic Verification Passes for HINAKU.

Deterministic checks in code:
  1. More than four sentences outside detail mode: trim at a sentence boundary.
  2. Forbidden offers (music, reminders, alarms, timers, calendar, sending messages, opening apps, tracking):
     detected for single-pass regeneration with extra instruction line; never LLM-rewritten.
  3. Clock errors (wrong weekday or date): fixed directly in code.
  4. Stated VRAM amount or GPU that conflicts with stored owner memory:
     detected for single-pass regeneration.
  5. LLM verifier (off by default): if enabled, may only answer OK or minimal edit.
     Output is strictly rejected if:
       - shorter than 60% of draft
       - turns a statement into a question
       - contains reviewer words ("the response", "accurately", "incorrect", etc.)
       - contains a persona example line
     Never show persona example lines to any verifier or checker prompt.
"""

import re
import time
import logging
from datetime import datetime
from typing import Tuple, Optional, Any, Dict, List, NamedTuple

logger = logging.getLogger("hinaku.quality")


class VerificationResult(NamedTuple):
    final_reply: str
    was_verified: bool
    elapsed_ms: int
    status: str = "not_verified"
    reason: Optional[str] = None

    def __iter__(self):
        return iter((self.final_reply, self.was_verified, self.elapsed_ms, self.status, self.reason))


# Reviewer vocabulary that indicates an LLM acted as a grader rather than an assistant
REVIEWER_WORDS = [
    "the response", "the draft", "the candidate", "the assistant",
    "accurately", "incorrect", "correctly", "as requested", "reviewer",
    "the answer", "this response", "this answer", "it accurately describes",
    "it includes a helpful", "the reply",
    "verification criteria", "system clock", "stored owner memories",
    "here is the corrected", "as a verification guard", "draft reply:",
    "exceeds the four-sentence limit", "reduce it to", "four-sentence limit",
    "four sentences or fewer", "please rewrite", "the draft violates",
    "that exceeds the"
]

KNOWN_PERSONA_EXAMPLES = [
    "i'm here. what are we working on?",
    "anytime. let me know when the next piece is ready.",
    "100 degrees celsius.",
    "step away from the screen for five minutes. we look at the stack trace fresh when you get back.",
    "no. a rewrite brings new bugs and burns momentum. isolate the bottleneck and fix that first.",
    "i am your personal ai assistant. calm, observant, and built for your work alone.",
    "that sounds heavy. pick the smallest broken thing and we fix only that. which one is it?",
    "no. rushing a release without tests creates bigger fires tomorrow. run the critical tests first."
]

OFFER_PREFIX = r"(?:i\s*'ll|i\s+(?:can|will|am\s+able\s+to|could)|let\s+me|do\s+you\s+want\s+(?:me\s+)?to|want\s+me\s+to|shall\s+i|should\s+i|can\s+i|may\s+i|would\s+you\s+like\s+(?:me\s+)?to)"

CONVERSATIONAL_VERB_PAT = r"(?i)\b(?:explain|walk\s+through|outline|list|draft|write|summarize|help(?:\s+me|\s+you)?\s+think)\b"

FORBIDDEN_CAPABILITY_PATTERNS = [
    # 1. Timers & Alarms (first-person only)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:set|start|create|run)\s+(?:\w+\s+){{0,2}}(?:timer|alarm)\b", "Offers to set timer/alarm"),
    (rf"(?i)\b{OFFER_PREFIX}\s+set\s+(?:\w+\s+){{0,2}}timer\s+for\s+\d+\b", "Offers to set a timer"),
    # 2. Reminders & Notifications (first-person only)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:(?:set|send|create)\s+(?:\w+\s+){{0,2}}(?:reminder|notification)|remind\s+you|notify\s+you|alert\s+you|remind\b)", "Offers to set reminder/notification"),
    # 3. Music & Sounds (first-person only)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:play|stream|put\s+on)\s+(?:\w+\s+){{0,2}}(?:music|sounds?|lofi|audio|track)\b", "Offers to play music or sounds"),
    # 4. Sending Messages / Emails / Texts (first-person only, not advice to user)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:send|dispatch|draft\s+and\s+send)\s+(?:\w+\s+){{0,2}}(?:message|email|text|notification|dm)\b", "Offers to send message"),
    # 5. Calendar Scheduling (first-person only, e.g. "Do you want to schedule it now?")
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:schedule|book|create\s+a\s+calendar|add\s+to\s+calendar)\b", "Offers to schedule"),
    # 6. Opening Apps / Programs (first-person only)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:open|launch|run|execute)\s+(?:\w+\s+){{0,2}}(?:vs\s*code|vscode|app|application|editor|browser|window|program|files?)\b", "Offers to open app"),
    # 7. Tracking / System Monitoring (first-person only)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:keep\s+)?(?:watching|tracking|monitoring)\s+(?:\w+\s+){{0,2}}(?:system|laptop|temp|temperature|gpu|cpu|usage|process|battery|schedule|anything)\b", "Offers to track/monitor"),
    # 8. External search / find / look up / check (first-person only)
    (rf"(?i)\b{OFFER_PREFIX}\s+(?:find|look\s+up|search(?:\s+for)?|check)\b", "Offers to find/search/check"),
]


def strip_persona_examples(persona_text: str) -> str:
    """
    Strips persona example dialogues or style reference sections before
    passing rules to any verifier or checker prompt.
    """
    if not persona_text:
        return ""
    # Cut off at Style reference:, ## Examples, Examples:
    markers = [
        "\nstyle reference:", "\n## style reference",
        "\nexamples:", "\n## examples", "\nstyle examples:"
    ]
    lower = persona_text.lower()
    cut_idx = len(persona_text)
    for m in markers:
        idx = lower.find(m)
        if idx != -1 and idx < cut_idx:
            cut_idx = idx
    return persona_text[:cut_idx].strip()


def count_sentences(text: str) -> int:
    clean_text = text.replace("vs.", "").replace("e.g.", "").replace("i.e.", "").replace("etc.", "")
    sentences = [p.strip() for p in re.split(r"[.!?]+", clean_text) if p.strip()]
    return len(sentences)


def trim_to_four_sentences(text: str) -> str:
    matches = list(re.finditer(r'[^.!?]+[.!?]+', text))
    if len(matches) <= 4:
        return text.strip()
    end_idx = matches[3].end()
    return text[:end_idx].strip()


def detect_forbidden_offers(text: str) -> Optional[str]:
    """
    Checks if reply contains first-person offers or claims of forbidden capabilities.
    Flags:
      - "Do you want me to find/look up/search/open/remind..."
      - "Do you want to schedule it now?"
      - "Shall I check..."
      - Timers, alarms, reminders, music, sending messages, tracking, opening apps.
    Allows conversational verbs:
      - explain, walk through, outline, list, draft, write, summarize, help me think.
    Does NOT flag second-person advice or instructions to the user
      (e.g. "Draft a message stating you are running late...").
    """
    for pat, desc in FORBIDDEN_CAPABILITY_PATTERNS:
        for m in re.finditer(pat, text):
            matched_prefix = text[:m.start()].lower()
            if any(neg in matched_prefix[-30:] for neg in ["cannot", "can't", "unable", "won't", "will not", "never", "don't", "do not", "not able to"]):
                continue
            following_text = text[m.start():m.end() + 30]
            if re.search(CONVERSATIONAL_VERB_PAT, following_text):
                continue
            return desc
    return None


def get_today_weekday_patterns(day: str) -> List[str]:
    d = re.escape(day)
    return [
        # 1. "Today is [a/an/a typical] X", "Today's X"
        rf"\b(?:today\s+(?:is|was)|today's)\s+(?:a\s+|an\s+|a\s+typical\s+|a\s+quiet\s+)?(?P<day>{d})\b",
        # 2. "It is / It's [a/an/a typical] X today"
        rf"\b(?:it\s+(?:is|was)|it's)\s+(?:a\s+|an\s+|a\s+typical\s+|a\s+quiet\s+)?(?P<day>{d})\s+today\b",
        # 3. Start of sentence or clause: "X today"
        rf"(?:^|[.!?;\n])\s*(?:a\s+|an\s+|a\s+typical\s+|a\s+quiet\s+)?(?P<day>{d})\s+today\b",
        # 4. Start of sentence or clause: "It is / It's [a/an/a typical] X"
        rf"(?:^|[.!?;\n])\s*(?:it\s+(?:is|was)|it's)\s+(?:a\s+|an\s+|a\s+typical\s+|a\s+quiet\s+)?(?P<day>{d})\b(?!\s+(?:morning|afternoon|evening|night)?\s*(?:next|last|following))"
    ]


def fix_clock_error_in_code(text: str, clock_dt: Optional[datetime] = None) -> Tuple[str, bool, Optional[str]]:
    """
    Checks for wrong weekday contradictions in code and replaces only statements
    that say what TODAY is ("Today is X", "It's X today", "X today") with the true
    clock value without calling any LLM. Never changes weekday words that refer to
    other days (tomorrow, next Monday, "on Monday").
    """
    now_dt = clock_dt or datetime.now()
    curr_weekday = now_dt.strftime("%A")  # e.g. "Saturday"
    curr_weekday_lower = curr_weekday.lower()

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    other_weekdays = [w for w in weekdays if w.lower() != curr_weekday_lower]

    fixed_text = text
    was_fixed = False
    reasons = []

    for wrong_day in other_weekdays:
        patterns = get_today_weekday_patterns(wrong_day)
        for pattern in patterns:
            if re.search(pattern, fixed_text, flags=re.IGNORECASE):
                def replacer(match):
                    full = match.group(0)
                    day_str = match.group("day")
                    if day_str.isupper():
                        rep = curr_weekday.upper()
                    elif day_str.islower():
                        rep = curr_weekday.lower()
                    else:
                        rep = curr_weekday
                    s, e = match.span("day")
                    rel_s = s - match.start()
                    rel_e = e - match.start()
                    return full[:rel_s] + rep + full[rel_e:]

                fixed_text = re.sub(pattern, replacer, fixed_text, flags=re.IGNORECASE)
                was_fixed = True
                reasons.append(f"Fixed weekday '{wrong_day}' to '{curr_weekday}'")

    if was_fixed:
        return fixed_text, True, "; ".join(reasons)
    return text, False, None


def detect_hardware_conflict(text: str) -> Optional[str]:
    """
    Detects if the reply attributes:
      - a VRAM size other than 6 GB to the RTX 4050 or owner's laptop
      - a second card or multiple cards to the RTX 4050 or owner's laptop
      - NVLink to the RTX 4050 or owner's laptop
      - a different GPU model to the owner's laptop
    Does NOT flag general advice about other GPUs (e.g. A100, RTX 3090, 4090).
    """
    # 1. Stated different GPU model for owner's machine
    owner_gpu_claims = re.findall(
        r"(?i)\b(?:your\s+(?:laptop|gpu|machine|card)|you\s+have|laptop\s+has|gpu\s+has|around\s+your)\b[^.!?\n]*?\b(rtx\s*(?!4050\b)\d{4}|gtx\s*\d{3,4}|radeon|rx\s*\d{4}|apple\s+m\d)\b",
        text
    )
    if owner_gpu_claims:
        return f"Stated different GPU model than owner's RTX 4050 ({owner_gpu_claims[0]})"

    # 2. VRAM size other than 6 GB attributed to RTX 4050 or owner's laptop/GPU/machine
    matches_after = re.findall(
        r"(?i)\b(?:rtx\s*4050|your\s+(?:laptop|gpu|machine|card)|laptop\s+has|gpu\s+has)\b[^.!?\n]*?\b(\d+)\s*(?:gb|gigabytes)\b",
        text
    )
    for claimed in matches_after:
        if int(claimed) != 6:
            return f"Stated wrong VRAM amount for owner's hardware ({claimed} GB instead of 6 GB)"

    matches_before = re.findall(
        r"(?i)\b(\d+)\s*(?:gb|gigabytes)\b[^.!?\n]*?\b(?:rtx\s*4050|your\s+(?:laptop|gpu|machine|card))\b",
        text
    )
    for claimed in matches_before:
        if int(claimed) != 6:
            return f"Stated wrong VRAM amount for owner's hardware ({claimed} GB instead of 6 GB)"

    # 3. Second card or multiple cards attributed to RTX 4050 / owner's laptop
    if re.search(r"(?i)\bper\s+card\b", text):
        return "Attributed multiple cards ('per card') to owner's hardware"

    multi_card_patterns = [
        r"(?i)\b(?:two|multiple|second|dual|another)\s+(?:or\s+more\s+)?(?:such\s+)?cards?\b",
        r"(?i)\b(?:two|multiple|second|dual)\s+rtx\s*4050\b",
        r"(?i)\brtx\s*4050\b[^.!?\n]*?\b(?:two|multiple|second|dual)\s+cards?\b",
        r"(?i)\b(?:your\s+laptop|the\s+laptop)\b[^.!?\n]*?\b(?:second|two|multiple)\s+cards?\b",
    ]
    for pat in multi_card_patterns:
        if re.search(pat, text):
            return "Attributed second card or multiple cards to owner's hardware"

    # 4. NVLink attributed to RTX 4050, owner's laptop, or 'such cards'
    nvlink_patterns = [
        r"(?i)\b(?:rtx\s*4050|your\s+(?:laptop|gpu|machine|card)|laptop|such\s+cards?)\b[^.!?\n]*?\bnvlink\b",
        r"(?i)\bnvlink\b[^.!?\n]*?\b(?:rtx\s*4050|your\s+(?:laptop|gpu|machine|card)|laptop|such\s+cards?)\b",
    ]
    for pat in nvlink_patterns:
        if re.search(pat, text):
            return "Attributed NVLink to owner's hardware"

    return None


def is_llm_verifier_output_valid(
    draft: str,
    raw_output: str,
    persona_examples: Optional[List[str]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validates LLM verifier output strictly against user rules:
      - May only answer OK or make a minimal edit.
      - Rejected if shorter than 60% of draft.
      - Rejected if turns a statement into a question.
      - Rejected if contains reviewer commentary words.
      - Rejected if contains a persona example verbatim.
    """
    clean_output = raw_output.strip()
    clean_draft = draft.strip()

    if not clean_output:
        return False, "empty_output"

    if clean_output.upper() == "OK":
        return True, None

    lower_out = clean_output.lower()

    # Rule A: Contains a persona example line
    examples_to_check = persona_examples or KNOWN_PERSONA_EXAMPLES
    clean_out_compare = re.sub(r"[^\w\s]", "", lower_out).strip()
    for ex in examples_to_check:
        ex_clean = re.sub(r"[^\w\s]", "", ex.lower()).strip()
        if ex_clean and (ex_clean == clean_out_compare or ex_clean in lower_out):
            return False, "rejected: contains persona example line"

    # Rule B: Contains reviewer words
    for word in REVIEWER_WORDS:
        if word in lower_out:
            return False, f"rejected: contains reviewer commentary ('{word}')"

    # Rule C: Turns a statement into a question
    draft_is_question = clean_draft.endswith("?")
    output_is_question = clean_output.endswith("?")
    if not draft_is_question and output_is_question:
        return False, "rejected: turned statement into a question"

    # Rule D: Length check (rejected if shorter than 60% of draft)
    if len(clean_draft) > 20 and len(clean_output) < (0.6 * len(clean_draft)):
        return False, "rejected: output shorter than 60% of draft"

    return True, None


def is_malformed_verification(raw_output: str, is_detail: bool = False) -> bool:
    """Strictly validate whether verifier response is usable or malformed."""
    text = raw_output.strip()
    if not text:
        return True
    if text.upper() == "OK":
        return False
    # If the verifier leaked instructions or gave meta commentary or reviewer words
    lower = text.lower()
    meta_phrases = [
        "verification criteria", "system clock", "stored owner memories",
        "here is the corrected", "as a verification guard", "draft reply:",
        "exceeds the four-sentence limit", "reduce it to", "four-sentence limit",
        "four sentences or fewer", "please rewrite", "the draft violates",
        "that exceeds the"
    ]
    if any(m in lower for m in meta_phrases):
        return True
    if any(rw in lower for rw in REVIEWER_WORDS):
        return True
    if any(re.sub(r"[^\w\s]", "", ex.lower()).strip() in lower for ex in KNOWN_PERSONA_EXAMPLES):
        return True
    if not is_detail and count_sentences(text) > 4:
        return True
    if text.count("?") > 1:
        return True
    return False


QUALITY_VERIFIER_SYSTEM_PROMPT = """You are the verification guard for HINAKU, a personal AI assistant.
Review the candidate assistant response against the clock, memory, and persona rules.

--- PERSONA RULES ---
{persona_rules}

--- SYSTEM CLOCK ---
{clock_ctx}

--- STORED OWNER MEMORIES ---
{memory_ctx}

--- VERIFICATION CRITERIA ---
You may fix ONLY:
1. Facts that conflict with the system clock or stored owner memories.
2. Claims of abilities HINAKU lacks (e.g. playing music or sounds, setting reminders, alarms, timers, calendar, sending messages, opening apps, tracking).
{rule_3}

CRITICAL RULES:
- You must NOT add new facts or extra information.
- If the draft reply has no violations, respond with ONLY the exact single word:
OK
- If any violations are present, make a minimal edit to fix the violation and respond with ONLY the corrected text directly to the owner.
- Never output explanations, reviewer commentary (do not say 'the response', 'accurately', 'incorrect'), prefixes, or questions unless asked.
- Never quote persona examples.
"""


async def verify_reply(
    draft: str,
    persona_rules: str,
    clock_ctx: str,
    memory_ctx: str,
    local_adapter: Any,
    model: str,
    options: Dict[str, Any],
    keep_alive: str,
    timeout_seconds: float = 30.0,
    is_detail: bool = False
) -> VerificationResult:
    """
    Runs an LLM verification pass if quality_mode is explicitly turned ON.
    Enforces strict user rejection rules.
    """
    clean_draft = draft.strip()
    if not clean_draft:
        return VerificationResult(draft, False, 0, "not_verified", "empty_draft")

    # Never show persona examples to verifier prompt
    stripped_persona = strip_persona_examples(persona_rules)

    rule_3 = (
        "3. Detail mode is active: do not enforce sentence limit, but ensure explanation is about 250 words ending with a one-sentence conclusion (cap at 350 words)."
        if is_detail else
        "3. Outside detail mode: ensure reply is four sentences or fewer."
    )

    system_prompt = QUALITY_VERIFIER_SYSTEM_PROMPT.format(
        persona_rules=stripped_persona,
        clock_ctx=clock_ctx,
        memory_ctx=memory_ctx if memory_ctx else "(no memory stored)",
        rule_3=rule_3
    )

    verify_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"DRAFT REPLY TO VERIFY:\n{clean_draft}"}
    ]

    verify_opts = dict(options)
    verify_opts["num_predict"] = min(options.get("num_predict", 300), 300)

    t0 = time.perf_counter()
    chunks = []
    try:
        async for chunk in local_adapter.stream_chat(
            messages=verify_messages,
            model=model,
            options=verify_opts,
            think=False,
            keep_alive=keep_alive,
            call_type="quality_verify"
        ):
            chunks.append(chunk)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        raw_output = "".join(chunks).strip()

        if not raw_output:
            logger.warning("Quality verifier returned empty response; using draft")
            if not is_detail and count_sentences(clean_draft) > 4:
                trimmed = trim_to_four_sentences(clean_draft)
                return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Trimmed to four sentences outside detail mode")
            return VerificationResult(draft, False, elapsed_ms, "not_verified", "empty_response")

        if raw_output.upper() == "OK":
            if not is_detail and count_sentences(clean_draft) > 4:
                trimmed = trim_to_four_sentences(clean_draft)
                return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Trimmed to four sentences outside detail mode")
            return VerificationResult(draft, True, elapsed_ms, "verified", None)

        is_valid, reject_reason = is_llm_verifier_output_valid(clean_draft, raw_output)
        if not is_valid:
            logger.warning(f"LLM verifier output rejected ({reject_reason}): '{raw_output[:60]}...'; preserving draft")
            if not is_detail and count_sentences(clean_draft) > 4:
                trimmed = trim_to_four_sentences(clean_draft)
                return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Trimmed to four sentences outside detail mode")
            return VerificationResult(draft, False, elapsed_ms, "not_verified", reject_reason)

        # Accepted minimal edit from verifier
        return VerificationResult(raw_output, True, elapsed_ms, "corrected", "Minimal edit accepted by verifier")

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(f"Quality verifier exception: {e}; using draft")
        if not is_detail and count_sentences(clean_draft) > 4:
            trimmed = trim_to_four_sentences(clean_draft)
            return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Trimmed to four sentences outside detail mode")
        return VerificationResult(draft, False, elapsed_ms, "not_verified", f"error: {str(e)}")


async def perform_reply_verification(
    draft_reply: str,
    used_backend: str,
    used_model: str,
    target_opts: Dict[str, Any],
    persona_state: Any,
    clock_context: str,
    memory_context: str,
    is_detail: bool,
    local_adapter: Any,
    settings: Any,
    messages_for_regen: Optional[List[Dict[str, str]]] = None,
    clock_dt: Optional[datetime] = None,
    has_attachments: bool = False
) -> Tuple[str, bool, int, str, Optional[str]]:
    """
    Executes deterministic checks and optional single-pass regenerations.
    Returns: (final_reply, was_verified, verify_ms, verify_status, verify_reason)
    """
    if not draft_reply.strip():
        fallback = "I couldn't put an answer together that time. Ask again, or turn off Think harder."
        return fallback, False, 0, "not_verified", "empty_reply"

    if used_backend != "local":
        return draft_reply, False, 0, "not_verified", "api_backend"

    curr_text = draft_reply
    verify_ms = 0
    correction_reasons = []

    # 1. Deterministic check: Clock errors (wrong weekday/date) fixed directly in code
    fixed_clock_text, did_fix_clock, clock_reason = fix_clock_error_in_code(curr_text, clock_dt=clock_dt)
    if did_fix_clock:
        curr_text = fixed_clock_text
        correction_reasons.append(clock_reason)

    # 2. Deterministic check: Forbidden capability offers
    offer_desc = detect_forbidden_offers(curr_text)
    if offer_desc and messages_for_regen and local_adapter:
        extra_instruction = "HINAKU cannot play music or sounds, set reminders, alarms, timers, notifications, schedule calendar events, send messages, open apps, find or search online, check external data, or track anything. Do not offer or claim to do any of these."
        regen_msgs = list(messages_for_regen) + [{"role": "system", "content": extra_instruction}]
        t0 = time.perf_counter()
        try:
            chunks = []
            async for c in local_adapter.stream_chat(
                messages=regen_msgs,
                model=used_model,
                options=target_opts,
                think=False,
                keep_alive=getattr(settings, "local_keep_alive", "30m"),
                call_type="deterministic_regen"
            ):
                chunks.append(c)
            verify_ms += int((time.perf_counter() - t0) * 1000)
            candidate = "".join(chunks).strip()
            if candidate and not detect_forbidden_offers(candidate):
                curr_text = candidate
                correction_reasons.append("Forbidden capability offer removed (regenerated)")
        except Exception as e:
            logger.warning(f"Error regenerating forbidden offer: {e}")

    # 3. Deterministic check: Stated hardware conflict with owner memory
    hw_conflict = detect_hardware_conflict(curr_text)
    if hw_conflict and messages_for_regen and local_adapter:
        extra_instruction = (
            "The owner's laptop has a single NVIDIA RTX 4050 with 6 GB VRAM. "
            "It has only one card, 6 GB VRAM total, and no NVLink. "
            "Do not state any other GPU model, VRAM amount, second card, or NVLink for their machine."
        )
        regen_msgs = list(messages_for_regen) + [{"role": "system", "content": extra_instruction}]
        t0 = time.perf_counter()
        try:
            chunks = []
            async for c in local_adapter.stream_chat(
                messages=regen_msgs,
                model=used_model,
                options=target_opts,
                think=False,
                keep_alive=getattr(settings, "local_keep_alive", "30m"),
                call_type="deterministic_regen"
            ):
                chunks.append(c)
            verify_ms += int((time.perf_counter() - t0) * 1000)
            candidate = "".join(chunks).strip()
            if candidate and not detect_hardware_conflict(candidate):
                curr_text = candidate
                correction_reasons.append("Corrected hardware conflict with owner memory (regenerated)")
        except Exception as e:
            logger.warning(f"Error regenerating hardware conflict: {e}")

    # 4. Deterministic check: More than 4 sentences outside detail mode, or word cap in detail mode
    # For documents (has_attachments=True), responses are comprehensive study guides/analyses and are never capped.
    if not has_attachments and not is_detail:
        num_s = count_sentences(curr_text)
        if num_s > 4:
            curr_text = trim_to_four_sentences(curr_text)
            correction_reasons.append("Trimmed to four sentences outside detail mode")
    elif not has_attachments and is_detail:
        words = re.findall(r"\b\w+\b", curr_text)
        if len(words) > 350:
            # If reply is over 350, regenerate once with a shorter target
            if messages_for_regen and local_adapter:
                extra_instruction = (
                    "The previous explanation was over 350 words. Rewrite it concisely, "
                    "keeping it around 200 words and ending with a one-sentence conclusion. "
                    "Begin directly with the explanation and do not use filler."
                )
                regen_msgs = list(messages_for_regen) + [{"role": "system", "content": extra_instruction}]
                t0 = time.perf_counter()
                try:
                    chunks = []
                    async for c in local_adapter.stream_chat(
                        messages=regen_msgs,
                        model=used_model,
                        options=target_opts,
                        think=False,
                        keep_alive=getattr(settings, "local_keep_alive", "30m"),
                        call_type="deterministic_regen"
                    ):
                        chunks.append(c)
                    verify_ms += int((time.perf_counter() - t0) * 1000)
                    candidate = "".join(chunks).strip()
                    cand_words = re.findall(r"\b\w+\b", candidate)
                    if candidate and len(cand_words) <= 350:
                        curr_text = candidate
                        correction_reasons.append("Regenerated detail reply to target under 350 words")
                    elif candidate:
                        curr_text = candidate
                except Exception as e:
                    logger.warning(f"Error regenerating detail reply: {e}")

            # Trim at a sentence boundary only as a last resort
            from backend.guards import trim_to_word_cap
            capped_detail, was_capped = trim_to_word_cap(curr_text, max_words=350)
            if was_capped:
                curr_text = capped_detail
                correction_reasons.append("Trimmed to sentence boundary at about 350 words (last resort)")

    # 5. Optional LLM verifier (off by default)
    if getattr(settings, "quality_mode", False):
        persona_content = persona_state.content if hasattr(persona_state, "content") else str(persona_state)
        llm_reply, llm_verified, llm_ms, llm_status, llm_reason = await verify_reply(
            draft=curr_text,
            persona_rules=persona_content,
            clock_ctx=clock_context,
            memory_ctx=memory_context or "",
            local_adapter=local_adapter,
            model=used_model,
            options=target_opts,
            keep_alive=getattr(settings, "local_keep_alive", "30m"),
            is_detail=is_detail
        )
        verify_ms += llm_ms
        if llm_status == "corrected" and llm_reply != curr_text:
            curr_text = llm_reply
            correction_reasons.append(llm_reason or "Minimal edit accepted by verifier")

    # 6. General safeguard: no post-processing step may replace a streamed reply
    # with one shorter than 60% of it, except guard replies.
    if used_backend != "guard" and len(draft_reply) > 0:
        if len(curr_text) < 0.60 * len(draft_reply):
            # Allow intentional word-cap reduction in detail mode if draft exceeded 350 words
            is_detail_cap_reduction = is_detail and len(re.findall(r"\b\w+\b", draft_reply)) > 350
            if not is_detail_cap_reduction:
                logger.warning(
                    f"Post-processing safeguard rejected replacement: proposed length {len(curr_text)} "
                    f"is shorter than 60% of original streamed draft ({len(draft_reply)}). Keeping original."
                )
                return draft_reply, True, verify_ms, "safeguard_kept_draft", "Shrinkage below 60% rejected"

    if correction_reasons:
        return curr_text, True, verify_ms, "corrected", "; ".join(correction_reasons)
    return curr_text, True, verify_ms, "verified", None
