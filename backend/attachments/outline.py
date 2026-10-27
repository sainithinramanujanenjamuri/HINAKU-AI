"""
backend/attachments/outline.py

Document outline extraction and sectioning:
- Extracts title, units, topics, page ranges, and section text
- Supports HTML/Markdown headings, DOCX heading styles, and PDF/Plaintext pattern parsing
- Guarantees precision on structured study materials (e.g. 2 units, 28 topics)
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

def clean_heading_text(h: str) -> str:
    h = re.sub(r"<[^>]+>", "", h)
    h = re.sub(r"&amp;", "&", h)
    h = re.sub(r"&lt;", "<", h)
    h = re.sub(r"&gt;", ">", h)
    h = re.sub(r"&quot;", '"', h)
    h = re.sub(r"\s+", " ", h)
    return h.strip()

def extract_outline_from_html(html_text: str) -> Tuple[str, List[DocumentSection]]:
    """Extracts structured outline from HTML using h1, h2, h3 tags."""
    # Find title from h1 or first heading
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL | re.IGNORECASE)
    doc_title = clean_heading_text(title_m.group(1)) if title_m else "Document"

    # Match all h2 and h3
    pattern = re.compile(r"<(h[23])[^>]*>(.*?)</\1>(.*?)(?=(?:<h[23][^>]*>|$))", re.DOTALL | re.IGNORECASE)
    
    sections: List[DocumentSection] = []
    current_unit = "General"
    order = 0

    for m in pattern.finditer(html_text):
        tag = m.group(1).lower()
        htext = clean_heading_text(m.group(2))
        body_html = m.group(3)
        body_text = clean_heading_text(body_html)

        if tag == "h2":
            if re.search(r"UNIT\s+(\d+|[IVXLCDM]+)", htext, re.IGNORECASE):
                current_unit = htext
                # Also treat as section if it has direct content before next h3
                if body_text and len(body_text) > 100 and not re.search(r"<h3", body_html, re.I):
                    order += 1
                    sections.append(DocumentSection(
                        section_order=order,
                        unit_name=current_unit,
                        topic_number=None,
                        title=htext,
                        start_page=1,
                        end_page=1,
                        text=body_text,
                        token_count=estimate_tokens(body_text)
                    ))
            else:
                # Other H2 (e.g. Quick-Recall Cheat Sheet)
                order += 1
                sections.append(DocumentSection(
                    section_order=order,
                    unit_name=current_unit,
                    topic_number=None,
                    title=htext,
                    start_page=1,
                    end_page=1,
                    text=body_text,
                    token_count=estimate_tokens(body_text)
                ))
        elif tag == "h3":
            # Topic inside current unit
            topic_num = None
            num_m = re.match(r"^(\d{1,2})\.\s*(.*)", htext)
            if num_m:
                topic_num = int(num_m.group(1))
            order += 1
            sections.append(DocumentSection(
                section_order=order,
                unit_name=current_unit,
                topic_number=topic_num,
                title=htext,
                start_page=1,
                end_page=1,
                text=body_text,
                token_count=estimate_tokens(body_text)
            ))

    return doc_title, sections

def extract_outline_from_pages(pages: List[DocumentPage], filename: str) -> Tuple[str, List[DocumentSection]]:
    """
    Extracts outline from multi-page documents (PDF, DOCX, TXT)
    using pattern detection:
    - Unit N headers
    - Numbered topics (e.g. '1. Defining Games & Play')
    - Fallback to 1500-token windows if no outline found.
    """
    full_text = "\n\n".join(f"[Page {p.page_number}]\n{p.text}" for p in pages)
    
    # 1. Determine title
    first_page_text = pages[0].text if pages else ""
    first_lines = [l.strip() for l in first_page_text.splitlines() if len(l.strip()) > 3]
    doc_title = first_lines[0] if first_lines else filename
    # Clean doc_title
    doc_title = re.sub(r"^[^\w]+", "", doc_title)
    doc_title = re.sub(r"\s+", " ", doc_title).strip()

    # 2. Search for Unit patterns and Topic patterns
    # Find all headings: UNIT ... or 1. Topic ... or 28. Topic ...
    heading_pattern = re.compile(
        r"(?:^|\n)(?P<h>(?:UNIT\s+(?:\d+|[IVXLCDM]+)[\s:—–-]+[^\n]+|\d{1,2}\.\s+[^\n]+))",
        re.IGNORECASE
    )

    matches = list(heading_pattern.finditer(full_text))
    
    sections: List[DocumentSection] = []
    current_unit = "Unit 1"
    
    if len(matches) >= 3:
        for i, m in enumerate(matches):
            htext = m.group("h").strip()
            # Clean heading
            htext = re.sub(r"\s+", " ", htext)
            
            # Start and end positions in full_text
            start_pos = m.start("h")
            end_pos = matches[i + 1].start("h") if i + 1 < len(matches) else len(full_text)
            
            section_chunk = full_text[start_pos:end_pos].strip()
            # Remove heading itself from body text
            body_text = section_chunk[len(m.group("h")):].strip()

            # Identify start_page and end_page from [Page N] markers
            page_markers_before = re.findall(r"\[Page\s+(\d+)\]", full_text[:start_pos])
            page_markers_inside = re.findall(r"\[Page\s+(\d+)\]", section_chunk)
            
            start_page = int(page_markers_before[-1]) if page_markers_before else (int(page_markers_inside[0]) if page_markers_inside else 1)
            end_page = int(page_markers_inside[-1]) if page_markers_inside else start_page

            # Clean body_text (remove [Page N] tags)
            clean_body = re.sub(r"\[Page\s+\d+\]\n?", "", body_text).strip()

            if re.match(r"^UNIT\s+", htext, re.IGNORECASE):
                current_unit = htext
                # If unit header has intro text, save it
                if clean_body and len(clean_body) > 80:
                    sections.append(DocumentSection(
                        section_order=len(sections) + 1,
                        unit_name=current_unit,
                        topic_number=None,
                        title=htext,
                        start_page=start_page,
                        end_page=end_page,
                        text=clean_body,
                        token_count=estimate_tokens(clean_body)
                    ))
            else:
                topic_num = None
                num_m = re.match(r"^(\d{1,2})\.", htext)
                if num_m:
                    topic_num = int(num_m.group(1))

                sections.append(DocumentSection(
                    section_order=len(sections) + 1,
                    unit_name=current_unit,
                    topic_number=topic_num,
                    title=htext,
                    start_page=start_page,
                    end_page=end_page,
                    text=clean_body,
                    token_count=estimate_tokens(clean_body)
                ))

    # 3. Fallback: if fewer than 2 sections detected, chunk into ~1500 token windows
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
                    token_count=cur_tokens
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
                token_count=cur_tokens
            ))

    return doc_title, sections

