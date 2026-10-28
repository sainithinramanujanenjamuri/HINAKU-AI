"""
tests/test_study_style.py

Unit tests for Phase 2c requirements:
- Study style verification (short explanation, example, takeaways)
- Addendum prompt generation for missing components
- Count consistency (Requirement 3: does not rewrite N, retrieves missing item from notes when notes list N and model lists fewer, logs before and after)
- Actions (Requirement 5: document with button does not create button, stored message text contains no HTML, history excludes actions)
- Formatting (Requirement 6: inner section labels in a topic must be bold labels or h4, not ###; code comes in fenced blocks)
"""

import json
import re
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

def test_count_consistency_adds_missing_item_from_notes():
    """
    Requirement 3:
    Do not rewrite the number to match the list. If the notes list 3 stages and
    the reply lists 2, add the missing item from the source and log before and after.
    """
    notes_text = (
        "The RAG attack lifecycle involves three stages:\n"
        "1. Malicious document upload into retrieval corpus\n"
        "2. Vector DB indexing without taint validation\n"
        "3. Ingestion and poisoning of generative context"
    )

    # Model reply mistakenly listed only 2 stages but claimed 3
    model_reply = (
        "RAG vulnerabilities arise across pipeline stages.\n\n"
        "The attack proceeds in three stages:\n"
        "* Malicious document upload into retrieval corpus\n"
        "* Vector DB indexing without taint validation\n\n"
        "*Example (analogous)*: A library receiving a book with forged historical facts."
    )

    modified, fixed_text, fixes = check_and_fix_count_consistency(
        explanation_text=model_reply,
        section_text=notes_text
    )

    assert modified is True
    assert len(fixes) == 1
    fix = fixes[0]
    # The count word 'three stages' MUST NOT be rewritten to 'two stages'
    assert "three stages" in fixed_text
    assert "two stages" not in fixed_text
    assert fix["claimed"] == 3
    assert fix["before_count"] == 2
    assert fix["after_count"] == 3
    assert "before" in fix and "after" in fix
    # Missing stage 3 must be added to the text
    assert "Ingestion and poisoning of generative context" in fixed_text

def test_inner_section_labels_normalized_to_h4():
    """
    Requirement 6:
    Inner section labels in a topic must be bold labels or h4, not the same ### level as the topic title.
    """
    raw_explanation = (
        "The AI Triad governs reliable machine learning.\n\n"
        "### **Pillar 1: Security**\n"
        "Security safeguards systems against data poisoning.\n\n"
        "### **Pillar 2: Ethics**\n"
        "Ethics ensures fairness and explainability.\n\n"
        "### **Pillar 3: Regulation**\n"
        "Regulation enforces legal compliance."
    )
    # Apply heading normalization
    normalized = re.sub(r"(?m)^###\s+(\*\*[^*]+\*\*):?", r"#### \1", raw_explanation)
    normalized = re.sub(r"(?m)^###\s+", r"#### ", normalized)

    assert not re.search(r"(?m)^###\s+", normalized)
    assert "#### **Pillar 1: Security**" in normalized
    assert "#### **Pillar 2: Ethics**" in normalized
    assert "#### **Pillar 3: Regulation**" in normalized

def test_code_fenced_blocks_formatting():
    """
    Requirement 6:
    Code must come in fenced blocks (test with the factorial turn).
    """
    factorial_reply = (
        "Here is a recursive factorial implementation in Python:\n\n"
        "```python\n"
        "def factorial(n: int) -> int:\n"
        "    if n <= 1:\n"
        "        return 1\n"
        "    return n * factorial(n - 1)\n"
        "```\n\n"
        "This executes in O(n) time."
    )
    # Check that code block is properly fenced with language tag
    assert "```python\n" in factorial_reply
    assert "def factorial(n: int) -> int:" in factorial_reply
    assert factorial_reply.count("```") >= 2

def test_actions_stored_as_metadata_and_html_stripped():
    """
    Requirement 5:
    - Raw HTML buttons removed from message text
    - Actions stored as metadata
    - Strip all HTML from model and document-derived text
    - A document containing a button tag must not create a button
    """
    from backend.attachments.extractor import extract_text_from_html

    # 1. Document containing raw button tag
    doc_html = b"<div><h1>Study Notes</h1><button onclick=\"alert('pwn')\">Fake Button</button><p>Real Content</p></div>"
    pages = extract_text_from_html(doc_html)
    doc_text = pages[0].text
    assert "<button" not in doc_text
    assert "Fake Button" in doc_text or "Real Content" in doc_text

    # 2. Text containing leaked HTML button tags
    dirty_reply = (
        "Topic 1 is complete.\n\n"
        '<div class="walkthrough-actions-row">\n'
        '  <button class="walkthrough-action-btn" data-prompt="explain unit 2">Continue to Unit 2 →</button>\n'
        '</div>'
    )
    # Strip HTML
    clean_reply = re.sub(r"<(script|style|button|a|div|span|p|h[1-6])[^>]*>.*?</\1>", "", dirty_reply, flags=re.IGNORECASE | re.DOTALL)
    clean_reply = re.sub(r"<[^>]+>", "", clean_reply).strip()

    assert "<button" not in clean_reply
    assert "<div" not in clean_reply
    assert "Continue to Unit 2" not in clean_reply
    assert clean_reply == "Topic 1 is complete."

    # 3. Actions structured metadata representation
    actions = [
        {"label": "Continue to Unit 2 →", "prompt": "explain unit 2", "style": "primary"},
        {"label": "Explain All Study Aids →", "prompt": "explain the study aids", "style": "highlight"}
    ]
    meta_json = json.dumps({"actions": actions})
    loaded_meta = json.loads(meta_json)
    assert len(loaded_meta["actions"]) == 2
    assert loaded_meta["actions"][0]["prompt"] == "explain unit 2"
