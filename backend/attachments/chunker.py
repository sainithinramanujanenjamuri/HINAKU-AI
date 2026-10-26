"""
backend/attachments/chunker.py

Chunking, token estimation, and citation formatting for document attachments:
- Chunks text into ~500 token segments with ~50 token overlap
- Tracks file name, page number, chunk index
- Formats citation chips: [File: {filename}, Page: {page_number}]
- Estimates tokens (~4 chars per token or 0.75 words per token)
"""

import math
import re
from typing import Dict, List, Optional
from .extractor import DocumentPage

CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
MAX_WHOLE_FILE_TOKENS = 2500

def estimate_tokens(text: str) -> int:
    """
    Estimates token count from text using standard heuristics.
    """
    if not text:
        return 0
    # Average ~4 chars per token, with whitespace boundary weighting
    words = len(text.split())
    chars = len(text)
    return max(words, math.ceil(chars / 4.0))

class DocumentChunk:
    def __init__(
        self,
        chunk_id: str,
        attachment_id: str,
        filename: str,
        page_number: int,
        chunk_index: int,
        text: str,
        token_count: int
    ):
        self.chunk_id = chunk_id
        self.attachment_id = attachment_id
        self.filename = filename
        self.page_number = page_number
        self.chunk_index = chunk_index
        self.text = text
        self.token_count = token_count

    def citation(self) -> str:
        return f"[File: {self.filename}, Page: {self.page_number}]"

    def to_dict(self) -> Dict:
        return {
            "chunk_id": self.chunk_id,
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "token_count": self.token_count,
            "citation": self.citation()
        }

def chunk_document_pages(
    attachment_id: str,
    filename: str,
    pages: List[DocumentPage]
) -> List[DocumentChunk]:
    """
    Splits document pages into chunks of approximately ~500 tokens with 50-token overlap.
    """
    chunks: List[DocumentChunk] = []
    chunk_counter = 0

    for page in pages:
        text = page.text.strip()
        if not text:
            continue

        words = text.split()
        if not words:
            continue

        page_tokens = estimate_tokens(text)
        if page_tokens <= CHUNK_SIZE_TOKENS:
            chunk_counter += 1
            chunks.append(DocumentChunk(
                chunk_id=f"{attachment_id}_p{page.page_number}_c{chunk_counter}",
                attachment_id=attachment_id,
                filename=filename,
                page_number=page.page_number,
                chunk_index=chunk_counter,
                text=text,
                token_count=page_tokens
            ))
            continue

        # Split page text into overlapping windows
        words_per_chunk = int(CHUNK_SIZE_TOKENS * 0.75)
        overlap_words = int(CHUNK_OVERLAP_TOKENS * 0.75)
        step = max(1, words_per_chunk - overlap_words)

        for i in range(0, len(words), step):
            window_words = words[i : i + words_per_chunk]
            if not window_words:
                break
            chunk_text = " ".join(window_words)
            chunk_counter += 1
            chunks.append(DocumentChunk(
                chunk_id=f"{attachment_id}_p{page.page_number}_c{chunk_counter}",
                attachment_id=attachment_id,
                filename=filename,
                page_number=page.page_number,
                chunk_index=chunk_counter,
                text=chunk_text,
                token_count=estimate_tokens(chunk_text)
            ))

    return chunks

