import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout.reconfigure(encoding="utf-8")

import datetime
import json
import time
import urllib.request
from backend.attachments.extractor import extract_text_from_pdf
from backend.attachments.outline import extract_outline_from_pages
from backend.attachments.faithfulness import verify_explanation_faithfulness

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = Path("data/measure") / f"{now_str}_security_notes_walkthrough.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

pdf_path = Path("tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf")
pages = extract_text_from_pdf(pdf_path.read_bytes())
title, sections = extract_outline_from_pages(pages, pdf_path.name)

topics = [s for s in sections if not s.is_study_aid]
study_aids = [s for s in sections if s.is_study_aid]
unit1_sections = [s for s in topics if "UNIT 1" in s.unit_name.upper()]
unit2_sections = [s for s in topics if "UNIT 2" in s.unit_name.upper()]

lines = []
lines.append("COMMAND: python scripts/run_security_notes_walkthrough.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("SECURITY NOTES WALKTHROUGH EXECUTION & REPORT")
lines.append("=" * 80)

lines.append("\n--- DOCUMENT STRUCTURE & OUTLINE SUMMARY ---")
lines.append(f"Document Title: {title}")
lines.append(f"Total Pages: {len(pages)}")
lines.append(f"Unit 1: {unit1_sections[0].unit_name} ({len(unit1_sections)} topics)")
lines.append(f"Unit 2: {unit2_sections[0].unit_name} ({len(unit2_sections)} sessions)")
lines.append(f"Study Aids ({len(study_aids)}): {', '.join(s.title for s in study_aids)}")

# Preamble text
intro_desc = f"2 units, {len(unit1_sections)} topics in Unit 1, {len(unit2_sections)} sessions in Unit 2, plus {len(study_aids)} study aids"
rolling_sec_per_topic = 10.6
initial_est_seconds = round(rolling_sec_per_topic * len(unit1_sections))

preamble_markdown = (
    f"**{title}**\n\n"
    f"Your notes contain **{intro_desc}**. "
    f"We'll learn them step by step starting with **{unit1_sections[0].unit_name}** (~{initial_est_seconds}s estimated).\n\n"
    "---\n"
)

lines.append("\n--- WALKTHROUGH STREAMED INTRO ---")
lines.append(preamble_markdown)

prompt_file = Path("config/prompts/study_explainer.md")
explainer_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "Explain from basics with examples."

lines.append("--- STEP-BY-STEP TOPIC GENERATION & TIMINGS ---")

reply_blocks = [preamble_markdown]

for idx, sec in enumerate(unit1_sections, 1):
    rem_topics = len(unit1_sections) - (idx - 1)
    current_topic_estimate = round(rolling_sec_per_topic * rem_topics)

    header_block = f"\n### {sec.title}\n\n"
    reply_blocks.append(header_block)

    sec_user_prompt = f"Topic to explain:\nTitle: {sec.title}\n\nNotes Text:\n{sec.text}"
    topic_messages = [
        {"role": "system", "content": explainer_prompt},
        {"role": "user", "content": sec_user_prompt}
    ]

    payload = {
        "model": "bonsai-2:9b",
        "messages": topic_messages,
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {
            "num_ctx": 8192,
            "temperature": 0.6,
            "top_p": 0.9,
            "num_predict": 300
        }
    }

    t0 = time.perf_counter()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    actual_s = time.perf_counter() - t0
    rolling_sec_per_topic = (rolling_sec_per_topic * (idx - 1) + actual_s) / idx

    topic_reply = data.get("message", {}).get("content", "").strip()

    # Faithfulness verification
    is_faithful, missing_terms, checked_text = verify_explanation_faithfulness(topic_reply, sec.text + " " + sec.title)
    if not is_faithful:
        # Single-pass regeneration
        regen_prompt = (
            f"{sec_user_prompt}\n\n"
            f"Important requirement: Use the exact terms and step names from the notes. "
            f"Do not substitute, invent, or generalize step names."
        )
        regen_payload = dict(payload)
        regen_payload["messages"] = [
            {"role": "system", "content": explainer_prompt},
            {"role": "user", "content": regen_prompt}
        ]
        t_reg = time.perf_counter()
        req_reg = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(regen_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req_reg, timeout=90) as resp_reg:
            data_reg = json.loads(resp_reg.read().decode("utf-8"))
        actual_reg_s = time.perf_counter() - t_reg
        regen_reply = data_reg.get("message", {}).get("content", "").strip()
        is_rf, missing_rf, final_ann = verify_explanation_faithfulness(regen_reply, sec.text + " " + sec.title)
        topic_reply = regen_reply if is_rf else final_ann
        faith_status = f"REGENERATED ({'PASSED' if is_rf else 'FALLBACK_ANNOTATED'})"
    else:
        faith_status = "PASSED (DIRECT)"

    lines.append(
        f"[Topic {sec.topic_number}/9] {sec.title[:45]:<45} | "
        f"Est: {current_topic_estimate:>2d}s | Act: {actual_s:>5.2f}s | "
        f"Rolling: {rolling_sec_per_topic:>5.2f}s | Faithfulness: {faith_status}"
    )

    reply_blocks.append(topic_reply + "\n")

# Unit completion and study aids offer
completion_block = (
    "\n---\n\n"
    "**Unit 1 Complete.**\n\n"
    "👉 [Continue to Unit 2](#continue-unit-2)\n\n"
    "---\n\n"
    "### 📚 Available Study Aids\n\n"
    f"Your notes include **{len(study_aids)} study aids** (reference materials):\n"
    + "\n".join(f"- **{s.title}**" for s in study_aids)
    + "\n\n*Would you like me to walk through the study aids? Type **explain the study aids** or ask about any specific reference.*\n"
)
reply_blocks.append(completion_block)

full_reply_text = "".join(reply_blocks)

lines.append("\n" + "=" * 80)
lines.append("FULL WALKTHROUGH ASSISTANT REPLY TEXT")
lines.append("=" * 80)
lines.append(full_reply_text)

output_text = "\n".join(lines) + "\n"
output_path.write_text(output_text, encoding="utf-8")
print(f"Report written to: {output_path}")
print(output_text[:1200] + "\n...[truncated for console]...")
