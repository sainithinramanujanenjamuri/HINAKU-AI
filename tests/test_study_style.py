"""
tests/test_study_style.py

Unit tests for:
- Study style verification (short explanation, example, takeaways)
- Addendum prompt generation for missing components
- Count consistency detection and correction (Topic 4, Topic 8 failures)
"""

import pytest
from backend.attachments.style_checker import (
    check_study_style,
    build_addendum_prompt,
    check_and_fix_count_consistency
)

def test_check_study_style_detects_complete_topic():
    complete_text = (
        "The AI Triad is composed of Security, Ethics, and Regulation.\n\n"
        "*Example (analogous)*: A high-security financial building with locks, guards, and compliance audits.\n\n"
        "**Exam-Oriented Key Takeaways**\n"
        "* Security focuses on confidentiality and integrity.\n"
        "* Ethics ensures fairness and transparency."
    )
    res = check_study_style(complete_text)
    assert res["is_complete"] is True
    assert res["has_example"] is True
    assert res["has_takeaways"] is True
    assert len(res["missing_parts"]) == 0

def test_check_study_style_detects_missing_example_and_takeaways():
    incomplete_text = (
        "The AI Triad is composed of Security, Ethics, and Regulation. "
        "It protects against data poisoning and model theft."
    )
    res = check_study_style(incomplete_text)
    assert res["is_complete"] is False
    assert res["has_example"] is False
    assert res["has_takeaways"] is False
    assert set(res["missing_parts"]) == {"example", "takeaways"}

def test_build_addendum_prompt():
    prompt = build_addendum_prompt(
        missing_parts=["example", "takeaways"],
        sec_title="Topic 1 — AI Triad",
        sec_text="Triad notes text...",
        existing_explanation="Explanation produced so far..."
    )
    assert "Generate ONLY the missing study components" in prompt
    assert "*Example (analogous)*:" in prompt
    assert "**Exam-Oriented Key Takeaways**" in prompt
    assert "Do NOT repeat, rewrite, or summarize" in prompt

def test_count_consistency_fixes_topic4_mismatch():
    # Real failure from Security run Topic 4: "three distinct phases" followed by six bullets
    topic4_text = (
        "Adversarial ML evolves through distinct operations.\n\n"
        "This moves through three distinct phases:\n"
        "* Reconnaissance of the model architecture\n"
        "* Weaponization and adversarial perturbation\n"
        "* Delivery via data stream\n"
        "* Exploitation of decision boundary\n"
        "* Installation of backdoor trigger\n"
        "* Command and exfiltration of weights\n\n"
        "*Example (analogous)*: A physical bank penetration test."
    )

    modified, fixed_text, fixes = check_and_fix_count_consistency(topic4_text)
    assert modified is True
    assert len(fixes) == 1
    assert fixes[0]["claimed"] == 3
    assert fixes[0]["actual"] == 6
    assert "six distinct phases" in fixed_text
    assert "three distinct phases" not in fixed_text

def test_count_consistency_fixes_topic8_mismatch():
    # Real failure from Security run Topic 8: "three stages" followed by two bullets
    topic8_text = (
        "RAG vulnerabilities arise across pipeline stages.\n\n"
        "The attack proceeds in three stages:\n"
        "1. Malicious document upload into retrieval corpus\n"
        "2. Vector DB indexing without taint validation\n\n"
        "**Exam-Oriented Key Takeaways**\n"
        "* RAG poisoning infects search context.\n"
        "* Access control prevents unauthorized retrieval."
    )

    modified, fixed_text, fixes = check_and_fix_count_consistency(topic8_text)
    assert modified is True
    assert len(fixes) == 1
    assert fixes[0]["claimed"] == 3
    assert fixes[0]["actual"] == 2
    assert "two stages" in fixed_text
    assert "three stages" not in fixed_text

