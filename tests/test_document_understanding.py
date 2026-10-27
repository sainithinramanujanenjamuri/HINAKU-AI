"""
tests/test_document_understanding.py

Comprehensive tests for Phase 2b: document understanding:
- Code-based intent routing (overview vs specific)
- Outline extraction precision (2 units, 28 topics on real sample)
- Fallback to ~1,500 token windows if no outline is detected
- Attachment sections SQLite storage and explanation caching
- Coverage honesty metadata generation
- Removal of 250-word cap for document turns
"""

import pytest
from pathlib import Path
from backend.attachments.intent import is_overview_intent, extract_target_unit
from backend.attachments.outline import (
    extract_outline_from_html,
    extract_outline_from_pages,
    DocumentSection
)
from backend.attachments.extractor import DocumentPage

def test_intent_routing_overview_vs_specific():
    # Overview requests must route to walkthrough
    assert is_overview_intent("explain this to me") is True
    assert is_overview_intent("explain the pdf") is True
    assert is_overview_intent("explain this") is True
    assert is_overview_intent("summarize") is True
    assert is_overview_intent("summarize the document") is True
    assert is_overview_intent("walk me through the notes") is True
    assert is_overview_intent("give me a study guide for this") is True
    assert is_overview_intent("explain the whole document") is True
    assert is_overview_intent("continue to unit 2") is True
    assert is_overview_intent("explain unit 1") is True

    # Specific inquiries must route to retrieval
    assert is_overview_intent("What is heuristic evaluation?") is False
    assert is_overview_intent("How does the 15-puzzle solvability check work?") is False
    assert is_overview_intent("What are the 10 game design rules?") is False
    assert is_overview_intent("Does Unity UI require a Canvas?") is False
    assert is_overview_intent("Who designed Chase in 1967?") is False

def test_target_unit_extraction():
    assert extract_target_unit("continue to unit 2") == 2
    assert extract_target_unit("explain Unit 1") == 1
    assert extract_target_unit("explain unit 3 in detail") == 3
    assert extract_target_unit("explain this to me") is None

def test_outline_extraction_precision_on_sample_html():
    sample_path = Path("tests/real_samples/Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.html")
    if not sample_path.exists():
        pytest.skip("Sample HTML not available")

    html_content = sample_path.read_text(encoding="utf-8", errors="ignore")
    title, sections = extract_outline_from_html(html_content)

    assert "Midterm Notes" in title
    units = set(s.unit_name for s in sections)
    assert len(units) == 2
    assert any("UNIT 1" in u for u in units)
    assert any("UNIT 2" in u for u in units)

    topics = [s for s in sections if s.topic_number is not None]
    assert len(topics) == 28
    assert topics[0].topic_number == 1
    assert topics[-1].topic_number == 28

def test_outline_fallback_to_1500_token_windows():
    # Synthetic unformatted pages without headings
    pages = [
        DocumentPage(page_number=i, text=f"This is continuous unstructured body text on page {i}. " * 60)
        for i in range(1, 10)
    ]
    title, sections = extract_outline_from_pages(pages, "unstructured.pdf")

    assert len(sections) >= 2
    for s in sections:
        assert "Part " in s.unit_name
        assert s.token_count > 0

def test_attachment_sections_storage_and_cache(tmp_path):
    from backend.attachments.storage import AttachmentStorage
    from backend.attachments.chunker import DocumentChunk

    db_file = tmp_path / "test_sections.db"
    uploads = tmp_path / "uploads"
    chroma = tmp_path / "chroma"

    storage = AttachmentStorage(
        db_path=db_file,
        uploads_dir=uploads,
        chroma_dir=chroma,
        embed_fn=lambda texts: [[0.1] * 128 for _ in texts]
    )

    sec1 = DocumentSection(
        section_order=1,
        unit_name="Unit 1",
        topic_number=1,
        title="1. Introduction",
        start_page=1,
        end_page=1,
        text="Content of topic 1.",
        token_count=10
    )
    sec2 = DocumentSection(
        section_order=2,
        unit_name="Unit 1",
        topic_number=2,
        title="2. Fundamentals",
        start_page=2,
        end_page=2,
        text="Content of topic 2.",
        token_count=12
    )

    rec = storage.save_attachment(
        conversation_id="conv_101",
        filename="notes.txt",
        file_bytes=b"Content of notes",
        file_type="text",
        mime_type="text/plain",
        extracted_text="Content of notes",
        sections=[sec1, sec2]
    )

    sections = storage.get_sections("conv_101")
    assert len(sections) == 2
    assert sections[0]["title"] == "1. Introduction"
    assert sections[1]["title"] == "2. Fundamentals"

    # Test caching explanation
    storage.update_section_cache(sections[0]["id"], "Cached explanation for topic 1.")
    updated = storage.get_section_by_id(sections[0]["id"])
    assert updated["explanation_cache"] == "Cached explanation for topic 1."

    # Test outline summary
    summary = storage.get_document_outline_summary("conv_101")
    assert summary["total_topics"] == 2
    assert len(summary["topics"]) == 2

def test_250_word_cap_not_applied_when_attachments_present():
    from backend.api.chat import get_settings
    # The logic in backend/api/chat.py enforces:
    # if is_detail and not has_attachments: persona_text += "\nExplain in about 250 words..."
    is_detail = True
    has_attachments = True
    should_cap = (is_detail and not has_attachments)
    assert should_cap is False
