"""
scripts/measure_faithfulness_recall.py

Evaluates faithfulness verification with both:
1. Positive-Control Test (Recall):
   Topic 7 (6D Framework) from Game Mechanics notes with reworded/hallucinated step names.
   Checks that the verifier successfully flags the ungrounded reworded terms.
2. Negative-Control Test (False-Positive Rate):
   Faithful extractions from both real samples (Game Mechanics notes & Security notes).
   Verifies that correctly grounded terms are not falsely flagged.
3. Outputs raw results to data/measure/<timestamp>_faithfulness_recall_report.txt.
"""

import datetime
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.attachments.extractor import extract_text_from_pdf
from backend.attachments.outline import extract_outline_from_pages
from backend.attachments.faithfulness import (
    verify_explanation_faithfulness,
    extract_named_items,
    check_term_in_source,
    normalize_text_for_search
)

def main():
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = ROOT / "data" / "measure" / f"{now_str}_faithfulness_recall_report.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("COMMAND: python scripts/measure_faithfulness_recall.py")
    lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
    lines.append("=" * 80)
    lines.append("FAITHFULNESS VERIFICATION: RECALL & FALSE-POSITIVE EVALUATION")
    lines.append("=" * 80)

    # Load Game Mechanics sample
    gm_path = ROOT / "tests/real_samples/Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf"
    sec_path = ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"

    gm_pages = extract_text_from_pdf(gm_path.read_bytes())
    gm_full_text = "\n\n".join(p.text for p in gm_pages)
    _, gm_sections = extract_outline_from_pages(gm_pages, gm_path.name)

    # 1. POSITIVE-CONTROL TEST (Topic 7: 6D Framework)
    lines.append("\n--- PART 1: POSITIVE-CONTROL TEST (REWORDED STEP NAMES) ---")
    lines.append("Source: Game Mechanics Notes - Topic 7 (The 6D Framework)")
    lines.append("Original Steps in Notes:")
    lines.append("  1. Establish business objectives")
    lines.append("  2. Outline targeted actions")
    lines.append("  3. Define personas")
    lines.append("  4. Refine activity sequences")
    lines.append("  5. Ensure a fun system")
    lines.append("  6. Select the right game elements")

    # Crafted version with 6 deliberately reworded step names
    reworded_steps = [
        "Formulate commercial goals",
        "Catalog user activities",
        "Build customer avatars",
        "Map workflow loops",
        "Maximize entertainment",
        "Choose gamification widgets"
    ]

    reworded_explanation = (
        "The 6D Framework is an iterative methodology for gamification design.\n\n"
        "It consists of six sequential steps:\n"
        "1. **Formulate commercial goals**: clarify why gamification is needed for revenue.\n"
        "2. **Catalog user activities**: list what users should do.\n"
        "3. **Build customer avatars**: profile user archetypes.\n"
        "4. **Map workflow loops**: structure progression cycles.\n"
        "5. **Maximize entertainment**: guarantee pleasure.\n"
        "6. **Choose gamification widgets**: select leaderboards and points.\n\n"
        "*Example (analogous)*: A fitness app rewarding runners with virtual trophies.\n\n"
        "**Exam-Oriented Key Takeaways**\n"
        "* 6D framework guides gamification implementation.\n"
        "* Business goals drive element selection."
    )

    t7_sec = next((s for s in gm_sections if "6D" in s.title or "7." in s.title), None)
    t7_sec_text = t7_sec.text if t7_sec else gm_full_text

    is_faithful, missing_terms, checked_text = verify_explanation_faithfulness(
        explanation_text=reworded_explanation,
        section_text=t7_sec_text,
        full_document_text=gm_full_text,
        sec_title="7. The 6D Framework"
    )

    lines.append(f"\nTested Reworded Steps ({len(reworded_steps)} terms):")
    for r in reworded_steps:
        flagged = any(r.lower() in m.lower() or m.lower() in r.lower() for m in missing_terms)
        lines.append(f"  - '{r}' -> Flagged as ungrounded: {flagged}")

    detected_count = sum(1 for r in reworded_steps if any(r.lower() in m.lower() or m.lower() in r.lower() for m in missing_terms))
    recall_pct = (detected_count / len(reworded_steps)) * 100.0

    lines.append(f"\nPositive-Control Results:")
    lines.append(f"  Total Injected Reworded Steps: {len(reworded_steps)}")
    lines.append(f"  Correctly Flagged as Ungrounded: {detected_count}")
    lines.append(f"  Recall: {recall_pct:.2f}%")
    lines.append(f"  Overall Faithful Verdict: {is_faithful} (Expected False)")

    # 2. NEGATIVE-CONTROL TEST (Grounded Faithful Content across both samples)
    lines.append("\n" + "=" * 80)
    lines.append("--- PART 2: NEGATIVE-CONTROL TEST (FALSE-POSITIVE RATE) ---")
    
    # Ground truth faithful concepts from Game Mechanics notes
    gm_grounded_terms = [
        "Mechanics", "Dynamics", "Aesthetics", "Killers", "Achievers",
        "Socializers", "Explorers", "MDA Framework",
        "Establish business objectives", "Outline targeted actions", "Define personas",
        "Refine activity sequences", "Ensure a fun system", "Select the right game elements"
    ]
    gm_fp = 0
    lines.append("\nGame Mechanics Ground Truth Terms:")
    for term in gm_grounded_terms:
        found = check_term_in_source(term, gm_full_text)
        if not found:
            gm_fp += 1
            lines.append(f"  - FALSE POSITIVE: '{term}' not found in source text")
        else:
            lines.append(f"  - Verified grounded: '{term}'")

    # Ground truth faithful concepts from Security notes
    sec_pages = extract_text_from_pdf(sec_path.read_bytes())
    sec_full_text = "\n\n".join(p.text for p in sec_pages)

    sec_grounded_terms = [
        "AI Triad", "Security", "Ethics", "Regulation", "Model Inversion",
        "Membership Inference", "Model Extraction", "Data Poisoning",
        "Adversarial Inputs", "ATLAS", "MITRE ATT&CK", "TTPs",
        "Tactics", "Techniques", "Procedures"
    ]
    sec_fp = 0
    lines.append("\nSecurity Ground Truth Terms:")
    for term in sec_grounded_terms:
        found = check_term_in_source(term, sec_full_text)
        if not found:
            sec_fp += 1
            lines.append(f"  - FALSE POSITIVE: '{term}' not found in source text")
        else:
            lines.append(f"  - Verified grounded: '{term}'")

    total_grounded = len(gm_grounded_terms) + len(sec_grounded_terms)
    total_fp = gm_fp + sec_fp
    fp_rate = (total_fp / total_grounded) * 100.0

    lines.append(f"\nNegative-Control Results:")
    lines.append(f"  Total Grounded Terms Tested: {total_grounded}")
    lines.append(f"  False Positives: {total_fp}")
    lines.append(f"  False-Positive Rate: {fp_rate:.2f}%")

    lines.append("\n" + "=" * 80)
    lines.append("SUMMARY VERDICT:")
    lines.append(f"  Recall (Positive Control): {recall_pct:.2f}% (Target: 100%)")
    lines.append(f"  False-Positive Rate (Negative Control): {fp_rate:.2f}% (Target: 0%)")
    lines.append("=" * 80)

    out_text = "\n".join(lines) + "\n"
    out_file.write_text(out_text, encoding="utf-8")
    print(f"Report written to: {out_file}")
    print(out_text)

if __name__ == "__main__":
    main()
