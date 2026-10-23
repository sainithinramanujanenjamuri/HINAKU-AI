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
from typing import Tuple, Optional, Any, Dict

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
2. Claims of abilities HINAKU lacks (e.g. setting timers, monitoring systems, running programs, or acting outside chat).
3. Rule violations: more than 4 sentences, or more than 1 question mark.

CRITICAL RULES:
- You must NOT add new facts or extra information.
- If the draft reply has no violations, respond with ONLY the exact single word:
OK
- If any of the 3 issues are present, respond with ONLY the corrected reply directly to the owner.
- Never output prefixes like 'Corrected reply:' or meta-commentary.
"""

def is_malformed_verification(raw_output: str) -> bool:
    """Strictly validate whether verifier response is usable or malformed."""
    text = raw_output.strip()
    if not text:
        return True
    if text.upper() == "OK":
        return False
    # If the verifier leaked instructions or gave meta commentary
    lower = text.lower()
    if any(m in lower for m in [
        "verification criteria", "system clock", "stored owner memories",
        "here is the corrected", "as a verification guard", "draft reply:"
    ]):
        return True
    # If output contains more than 4 sentences or more than 1 question mark
    clean_text = text.replace("vs.", "").replace("e.g.", "").replace("i.e.", "")
    import re
    sentences = [p.strip() for p in re.split(r"[.!?]+", clean_text) if p.strip()]
    if len(sentences) > 4:
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
    timeout_seconds: float = 30.0
) -> Tuple[str, bool, int]:
    """
    Runs one verification pass.
    Returns: (final_reply, was_verified, elapsed_ms)
    """
    clean_draft = draft.strip()
    if not clean_draft:
        return draft, False, 0

    system_prompt = QUALITY_VERIFIER_SYSTEM_PROMPT.format(
        persona_rules=persona_rules,
        clock_ctx=clock_ctx,
        memory_ctx=memory_ctx if memory_ctx else "(no memory stored)"
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
            return draft, False, elapsed_ms

        if raw_output.upper() == "OK":
            # Draft passed verification without changes
            return draft, True, elapsed_ms

        if is_malformed_verification(raw_output):
            logger.warning(f"Quality verifier output malformed ('{raw_output[:60]}...'); using draft")
            return draft, False, elapsed_ms

        # Accepted corrected reply
        return raw_output, True, elapsed_ms

    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(f"Quality verifier exception: {e}; using draft")
        return draft, False, elapsed_ms
