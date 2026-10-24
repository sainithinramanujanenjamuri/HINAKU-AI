"""
Quality Mode Verification Pass for HINAKU.

After a local draft is produced, runs a second local verification call that receives:
  - System Clock Context
  - Stored Owner Memories Context
  - Persona Rules
  - Draft Reply

Verifier Output:
  - Responds with the exact word "OK" if the draft is compliant.
  - Or responds with a corrected reply if and only if:
      1. Facts conflict with the clock or memory block.
      2. Claims of abilities HINAKU lacks (timers, system monitoring, running programs, acting outside chat).
      3. Rule violations (>4 sentences or >1 question mark).

Rules:
  - Must NOT add new facts.
  - Parse strictly; if the output is malformed, use the draft.
  - At most one revision (no recursion).
  - Return (final_reply, was_verified, verify_latency_ms).
"""

import time
import logging
from typing import Tuple, Optional, Any, Dict, NamedTuple

class VerificationResult(NamedTuple):
    final_reply: str
    was_verified: bool
    elapsed_ms: int
    status: str = "not_verified"
    reason: Optional[str] = None

    def __iter__(self):
        # Support legacy unpacking of (final_reply, was_verified, elapsed_ms)
        # while also supporting full (final_reply, was_verified, elapsed_ms, status, reason)
        return iter((self.final_reply, self.was_verified, self.elapsed_ms, self.status, self.reason))


logger = logging.getLogger("hinaku.quality")

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
2. Claims of abilities HINAKU lacks (e.g. playing music or sounds, setting reminders, alarms, or notifications, scheduling calendar events, sending messages, opening apps, watching or tracking anything, setting timers, monitoring systems, running programs, or acting outside chat).
{rule_3}

CRITICAL RULES:
- You must NOT add new facts or extra information.
- If the draft reply has no violations, respond with ONLY the exact single word:
OK
- If any of the 3 issues are present, rewrite the reply to fix the issue and respond with ONLY the rewritten reply directly to the owner.
- For rule 3 (more than 4 sentences outside detail mode): rewrite the answer concisely into 4 sentences or fewer, preserving the meaning and adding no facts.
- Never output explanations, warnings, instructions, prefixes like 'Corrected reply:', or meta-commentary (e.g. do not say 'Reduce it to four sentences').
"""

def count_sentences(text: str) -> int:
    clean_text = text.replace("vs.", "").replace("e.g.", "").replace("i.e.", "")
    import re
    sentences = [p.strip() for p in re.split(r"[.!?]+", clean_text) if p.strip()]
    return len(sentences)

def trim_to_four_sentences(text: str) -> str:
    import re
    matches = list(re.finditer(r'[^.!?]+[.!?]+', text))
    if len(matches) <= 4:
        return text.strip()
    end_idx = matches[3].end()
    return text[:end_idx].strip()

def is_malformed_verification(raw_output: str, is_detail: bool = False) -> bool:
    """Strictly validate whether verifier response is usable or malformed."""
    text = raw_output.strip()
    if not text:
        return True
    if text.upper() == "OK":
        return False
    # If the verifier leaked instructions or gave meta commentary
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
    # If output contains more than 4 sentences (unless in detail mode) or more than 1 question mark
    if not is_detail:
        if count_sentences(text) > 4:
            return True
    if text.count("?") > 1:
        return True
    return False

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
    Runs one verification pass.
    Returns: (final_reply, was_verified, elapsed_ms)
    """
    clean_draft = draft.strip()
    if not clean_draft:
        return VerificationResult(draft, False, 0, "not_verified", "empty_draft")

    rule_3 = (
        "3. Rule violations: more than 1 question mark. "
        "(Detail mode is active: do NOT enforce any sentence limit, but ensure it stays under about 350 words)."
        if is_detail else
        "3. Rule violations: more than 4 sentences, or more than 1 question mark."
    )

    system_prompt = QUALITY_VERIFIER_SYSTEM_PROMPT.format(
        persona_rules=persona_rules,
        clock_ctx=clock_ctx,
        memory_ctx=memory_ctx if memory_ctx else "(no memory stored)",
        rule_3=rule_3
    )

    verify_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"DRAFT REPLY TO VERIFY:\n{clean_draft}"}
    ]

    # Limit tokens for verification call (just OK or short correction)
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
                return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Exceeded 4 sentences outside detail mode (trimmed to 4)")
            return VerificationResult(draft, False, elapsed_ms, "not_verified", "empty_response")

        if raw_output.upper() == "OK":
            # If the draft itself had >4 sentences outside detail mode, the verifier hallucinated OK!
            if not is_detail and count_sentences(clean_draft) > 4:
                logger.warning("Verifier returned OK for >4 sentence draft; trimming to 4 sentences.")
                trimmed = trim_to_four_sentences(clean_draft)
                return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Exceeded 4 sentences outside detail mode (trimmed to 4)")
            return VerificationResult(draft, True, elapsed_ms, "verified", None)

        if is_malformed_verification(raw_output, is_detail=is_detail):
            logger.warning(f"Quality verifier output malformed ('{raw_output[:60]}...'); checking fallback")
            if not is_detail and count_sentences(clean_draft) > 4:
                trimmed = trim_to_four_sentences(clean_draft)
                return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Exceeded 4 sentences outside detail mode (trimmed to 4)")
            return VerificationResult(draft, False, elapsed_ms, "not_verified", "malformed_output")

        # Accepted corrected reply
        return VerificationResult(raw_output, True, elapsed_ms, "corrected", "Violated persona rules or factual context (rewritten)") 

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(f"Quality verifier exception: {e}; using draft")
        if not is_detail and count_sentences(clean_draft) > 4:
            trimmed = trim_to_four_sentences(clean_draft)
            return VerificationResult(trimmed, True, elapsed_ms, "corrected", "Exceeded 4 sentences outside detail mode (trimmed to 4)")
        return VerificationResult(draft, False, elapsed_ms, "not_verified", f"error: {str(e)}")
