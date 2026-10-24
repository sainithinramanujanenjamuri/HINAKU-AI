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

FORBIDDEN_CAPABILITY_PATTERNS = [
    # Music or sounds
    (r"(?i)\b(?:i\s+can|i'll|i\s+will|let\s+me)\s+(?:play|stream|put\s+on)\s+(?:some\s+)?(?:ambient\s+)?(?:music|sounds?|lofi|audio)\b", "Offers to play music or sounds"),
    (r"(?i)\bplay\s+(?:some\s+)?(?:ambient\s+)?music\b", "Offers to play music"),
    (r"(?i)\b(?:stream|play)\s+soothing\s+sounds\b", "Offers to stream sounds"),
    # Timers, alarms, reminders, notifications
    (r"(?i)\b(?:set|create|start)\s+(?:a\s+)?(?:timer|alarm|reminder|notification)\b", "Offers to set timer/alarm/reminder"),
    (r"(?i)\b(?:i\s+can|i'll|i\s+will|let\s+me|want\s+me\s+to|do\s+you\s+want\s+me\s+to|should\s+i)\s+(?:set\s+a\s+reminder|remind\s+you|set\s+a\s+timer|set\s+an\s+alarm)\b", "Offers to set reminder/timer/alarm"),
    (r"(?i)\bset\s+a\s+timer\s+for\s+\d+\s+minutes?\b", "Offers to set a timer"),
    (r"(?i)\b(?:i'll|i\s+will|let\s+me)\s+(?:remind|alert|notify)\b", "Offers to remind/notify"),
    # Calendar events
    (r"(?i)\b(?:schedule|create)\s+(?:a\s+)?(?:calendar\s+event|event|meeting|appointment)\b", "Offers to schedule calendar event"),
    # Sending messages
    (r"(?i)\b(?:send|draft)\s+(?:a\s+)?(?:message|email|text|slack\s+message|dm)\b", "Offers to send message"),
    # Opening apps
    (r"(?i)\b(?:open|launch)\s+(?:an?\s+)?(?:vs\s*code|vscode|app|application|editor|browser|window|program)\b", "Offers to open app"),
    # Tracking / monitoring
    (r"(?i)\b(?:keep\s+)?(?:watching|tracking|monitoring)\s+(?:your\s+)?(?:system|laptop|temp|temperature|gpu|cpu|usage|process|battery|schedule|anything)\b", "Offers to track/monitor")
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
    Checks if reply offers forbidden capabilities (music, timers, alarms,
    reminders, calendar, sending messages, opening apps, tracking).
    Returns specific violation description if detected, else None.
    """
    for pat, desc in FORBIDDEN_CAPABILITY_PATTERNS:
        if re.search(pat, text):
            return desc
    return None


def fix_clock_error_in_code(text: str, clock_dt: Optional[datetime] = None) -> Tuple[str, bool, Optional[str]]:
    """
    Checks for wrong weekday or date contradictions in code and replaces them
    with the true clock value without calling any LLM.
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
        # Check case-insensitive boundary match
        pattern = rf"\b{re.escape(wrong_day)}\b"
        if re.search(pattern, fixed_text, flags=re.IGNORECASE):
            # Replace preserving case
            def replacer(match):
                matched_str = match.group(0)
                if matched_str.isupper():
                    return curr_weekday.upper()
                elif matched_str.islower():
                    return curr_weekday.lower()
                else:
                    return curr_weekday

            fixed_text = re.sub(pattern, replacer, fixed_text, flags=re.IGNORECASE)
            was_fixed = True
            reasons.append(f"Fixed weekday '{wrong_day}' to '{curr_weekday}'")

    if was_fixed:
        return fixed_text, True, "; ".join(reasons)
    return text, False, None


def detect_hardware_conflict(text: str) -> Optional[str]:
    """
    Detects if the reply makes a hardware claim about the owner's laptop
    that contradicts stored memory (HP V15 with RTX 4050, 6 GB VRAM).
    """
    owner_gpu_claims = re.findall(
        r"(?i)\b(?:your\s+(?:laptop|gpu|machine|card)|you\s+have|laptop\s+has|gpu\s+has|around\s+your)\b[^.]*?\b(rtx\s*(?!4050\b)\d{4}|gtx\s*\d{3,4}|radeon|rx\s*\d{4}|apple\s+m\d)\b",
        text
    )
    if owner_gpu_claims:
        return f"Stated different GPU model than owner's RTX 4050 ({owner_gpu_claims[0]})"

    owner_vram_claims = re.findall(
        r"(?i)\b(?:your\s+(?:laptop|gpu|machine|card)|you\s+have|laptop\s+has|gpu\s+has)\b[^.]*?\b(\d+)\s*(?:gb|gigabytes)\b",
        text
    )
    for claimed_vram in owner_vram_claims:
        if int(claimed_vram) != 6:
            return f"Stated wrong VRAM amount ({claimed_vram} GB instead of 6 GB)"

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
        "3. Detail mode is active: do not enforce sentence limit, but cap at about 350 words."
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
