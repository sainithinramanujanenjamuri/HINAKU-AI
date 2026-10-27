"""
backend/attachments/outline.py

Document outline extraction and sectioning:
- Extracts title, units, topics, sessions, page ranges, and section text
- Correctly isolates reference materials / study aids (Glossary, Attack Comparison, Likely Exam Themes, Cheat Sheet)
- Excludes header metadata lines (e.g. 'Units 1-2 | 23CS201PE408') from becoming units or topics
- Assigns real page ranges to sections and supports citations
- Fallback to ~1,500 token windows if no hierarchical outline detected
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from .chunker import estimate_tokens
from .extractor import DocumentPage

@dataclass
class DocumentSection:
    section_order: int
    unit_name: str
    topic_number: Optional[int]
    title: str
    start_page: int
    end_page: int
    text: str
    token_count: int
    section_type: str = "topic"  # "topic", "session", "study_aid"
    is_study_aid: bool = False

def clean_heading_text(h: str) -> str:
    h = re.sub(r"<[^>]+>", "", h)
    h = re.sub(r"&amp;", "&", h)
    h = re.sub(r"&lt;", "<", h)
    h = re.sub(r"&gt;", ">", h)
    h = re.sub(r"&quot;", '"', h)
    h = re.sub(r"\s+", " ", h)
    return h.strip()

def is_header_metadata_line(text: str) -> bool:
    """Detects document header metadata such as 'Units 1–2 | 23CS201PE408'."""
    if re.search(r"Units?\s+\d+[\s–-]+.*\|", text, re.IGNORECASE):
        return True
    if re.search(r"\b23CS201[A-Z0-9]+\b", text, re.IGNORECASE):
        return True
    return False

def is_study_aid_title(title: str) -> bool:
    """Checks if a heading is a reference section / study aid."""
    pattern = r"\b(glossary|attack comparison|likely exam|cheat sheet|quick-recall|study aid|attack landscape comparison)\b"
    return bool(re.search(pattern, title, re.IGNORECASE))

def extract_outline_from_html(html_text: str) -> Tuple[str, List[DocumentSection]]:
    """Extracts structured outline from HTML using h1, h2, h3 tags."""
    # Find title from h1 or first heading
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL | re.IGNORECASE)
    doc_title = clean_heading_text(title_m.group(1)) if title_m else "Document"
    if is_header_metadata_line(doc_title):
        doc_title = "Study Notes"

    # Match all h2 and h3
    pattern = re.compile(r"<(h[23])[^>]*>(.*?)</\1>(.*?)(?=(?:<h[23][^>]*>|$))", re.DOTALL | re.IGNORECASE)
    
    sections: List[DocumentSection] = []
    current_unit = "Unit 1"
    order = 0

    # Total characters for estimating relative page locations in HTML uploads (~2500 chars/page)
    total_len = max(1, len(html_text))

    for m in pattern.finditer(html_text):
        tag = m.group(1).lower()
        htext = clean_heading_text(m.group(2))
        body_html = m.group(3)
        body_text = clean_heading_text(body_html)

        # Skip header metadata lines
        if is_header_metadata_line(htext):
            continue

        # Approximate page mapping for HTML uploads
        est_page = max(1, min(14, int((m.start() / total_len) * 14) + 1))
        est_end_page = max(est_page, min(14, int((m.end() / total_len) * 14) + 1))

        if tag == "h2":
            if re.search(r"UNIT\s+(\d+|[IVXLCDM]+)", htext, re.IGNORECASE):
                current_unit = htext
            else:
                # Reference section / study aid (e.g. Quick-Reference Glossary, Likely Exam Themes)
                order += 1
                is_aid = is_study_aid_title(htext)
                sections.append(DocumentSection(
                    section_order=order,
                    unit_name=current_unit,
                    topic_number=None,
                    title=htext,
                    start_page=est_page,
                    end_page=est_end_page,
                    text=body_text,
                    token_count=estimate_tokens(body_text),
                    section_type="study_aid" if is_aid else "topic",
                    is_study_aid=is_aid
                ))
        elif tag == "h3":
            if is_header_metadata_line(htext):
                continue

            order += 1
            is_aid = is_study_aid_title(htext)
            
            # Detect topic or session number
            topic_num = None
            sec_type = "topic"
            sm = re.search(r"Session\s+(\d+)", htext, re.I)
            tm = re.search(r"(?:Topic|\b)\s*(\d{1,2})\b", htext, re.I)
            
            if sm:
                topic_num = int(sm.group(1))
                sec_type = "session"
            elif tm and not is_aid:
                topic_num = int(tm.group(1))
                sec_type = "topic"

            sections.append(DocumentSection(
                section_order=order,
                unit_name=current_unit,
                topic_number=topic_num,
                title=htext,
                start_page=est_page,
                end_page=est_end_page,
                text=body_text,
                token_count=estimate_tokens(body_text),
                section_type="study_aid" if is_aid else sec_type,
                is_study_aid=is_aid
            ))

    return doc_title, sections

def extract_outline_from_pages(pages: List[DocumentPage], filename: str) -> Tuple[str, List[DocumentSection]]:
    """
    Extracts outline from multi-page documents (PDF, DOCX, TXT)
    using pattern detection:
    - Unit N headers
    - Topic N / Session N / Numbered topics (e.g. '1. Defining Games & Play')
    - Study aids (Glossary, Attack Comparison, Likely Exam Themes, Cheat Sheet)
    - Fallback to 1500-token windows if no outline found.
    """
    first_page_text = pages[0].text if pages else ""
    first_lines = [l.strip() for l in first_page_text.splitlines() if len(l.strip()) > 3]
    doc_title = first_lines[0] if first_lines else filename
    # Remove metadata lines like "Units 1-2 | 23CS201PE408" from title
    if is_header_metadata_line(doc_title):
        doc_title = first_lines[1] if len(first_lines) > 1 else filename
    doc_title = re.sub(r"^[^\w]+", "", doc_title)
    doc_title = re.sub(r"\s+", " ", doc_title).strip()

    full_text = "\n\n".join(f"[Page {p.page_number}]\n{p.text}" for p in pages)
    
    # Check if document uses Topic / Session keywords
    is_topic_session_doc = bool(re.search(r"\bTopic\s+\d+\b", full_text, re.I) or re.search(r"\bSession\s+\d+\b", full_text, re.I))

    lines_with_pos = []
    curr_idx = 0
    for l in full_text.splitlines(keepends=True):
        lines_with_pos.append((curr_idx, curr_idx + len(l), l.strip()))
        curr_idx += len(l)

    heading_candidates = []
    expected_gm_topic = 1

    for start_pos, end_pos, line in lines_with_pos:
        if not line or len(line) < 3:
            continue
        if is_header_metadata_line(line):
            continue

        # Check Unit header
        if re.match(r"^UNIT\s+(?:\d+|[IVXLCDM]+)[\s:—–-]+", line, re.I):
            heading_candidates.append((start_pos, end_pos, line, "unit", None))
            continue

        # Check Study Aids
        if re.match(r"^(Likely Exam Themes|Attack Comparison|Glossary|Quick-Recall Cheat Sheet|Attack Landscape Comparison|Quick-Reference)", line, re.I):
            heading_candidates.append((start_pos, end_pos, line, "study_aid", None))
            continue

        if is_topic_session_doc:
            tm = re.match(r"^Topic\s+(\d+)\s*[—–:-]\s*(.*)", line, re.I)
            if tm:
                heading_candidates.append((start_pos, end_pos, line, "topic", int(tm.group(1))))
                continue
            sm = re.match(r"^Sessions?\s+(\d+(?:[–-]\d+)?)\s*[—–:-]\s*(.*)", line, re.I)
            if sm:
                raw_num = sm.group(1)
                num = int(raw_num.split("–")[0].split("-")[0]) if any(c.isdigit() for c in raw_num) else None
                heading_candidates.append((start_pos, end_pos, line, "session", num))
                continue
        else:
            # Sequential numbered topics 1..28 in Game Mechanics notes
            gm = re.match(r"^(\d{1,2})\.\s+([A-Z][^\n]+)", line)
            if gm:
                num = int(gm.group(1))
                if num == expected_gm_topic:
                    heading_candidates.append((start_pos, end_pos, line, "topic", num))
                    expected_gm_topic += 1
                    continue

    sections: List[DocumentSection] = []
    current_unit = "Unit 1"
    order = 0

    if len(heading_candidates) >= 3:
        for i, (start_pos, end_pos, htext, htype, hnum) in enumerate(heading_candidates):
            next_start = heading_candidates[i + 1][0] if i + 1 < len(heading_candidates) else len(full_text)
            section_raw = full_text[start_pos:next_start]
            body_text = full_text[end_pos:next_start].strip()

            # Find real page numbers
            pages_before = re.findall(r"\[Page\s+(\d+)\]", full_text[:start_pos])
            start_page = int(pages_before[-1]) if pages_before else 1
            
            pages_inside = re.findall(r"\[Page\s+(\d+)\]", section_raw)
            end_page = int(pages_inside[-1]) if pages_inside else start_page

            clean_body = re.sub(r"\[Page\s+\d+\]\n?", "", body_text).strip()

            if htype == "unit":
                current_unit = htext
                continue

            order += 1
            is_aid = (htype == "study_aid")
            sections.append(DocumentSection(
                section_order=order,
                unit_name=current_unit,
                topic_number=hnum,
                title=htext,
                start_page=start_page,
                end_page=end_page,
                text=clean_body,
                token_count=estimate_tokens(clean_body),
                section_type=htype,
                is_study_aid=is_aid
            ))

    # Fallback to ~1500 token windows if fewer than 2 sections detected
    if len(sections) < 2:
        sections = []
        window_size = 1500
        cur_text_parts = []
        cur_tokens = 0
        cur_start_page = 1
        order = 0

        for p in pages:
            p_tokens = estimate_tokens(p.text)
            if cur_tokens + p_tokens > window_size and cur_text_parts:
                order += 1
                combined = "\n\n".join(cur_text_parts)
                sections.append(DocumentSection(
                    section_order=order,
                    unit_name=f"Part {order}",
                    topic_number=order,
                    title=f"Section {order} (pp. {cur_start_page}-{p.page_number-1 if p.page_number > cur_start_page else cur_start_page})",
                    start_page=cur_start_page,
                    end_page=max(cur_start_page, p.page_number - 1),
                    text=combined,
                    token_count=cur_tokens,
                    section_type="topic",
                    is_study_aid=False
                ))
                cur_text_parts = [p.text]
                cur_tokens = p_tokens
                cur_start_page = p.page_number
            else:
                cur_text_parts.append(p.text)
                cur_tokens += p_tokens

        if cur_text_parts:
            order += 1
            combined = "\n\n".join(cur_text_parts)
            last_page = pages[-1].page_number if pages else cur_start_page
            sections.append(DocumentSection(
                section_order=order,
                unit_name=f"Part {order}",
                topic_number=order,
                title=f"Section {order} (pp. {cur_start_page}-{last_page})",
                start_page=cur_start_page,
                end_page=last_page,
                text=combined,
                token_count=cur_tokens,
                section_type="topic",
                is_study_aid=False
            ))

    return doc_title, sections
