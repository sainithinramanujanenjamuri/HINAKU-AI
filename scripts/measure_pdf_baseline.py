"""
scripts/measure_pdf_baseline.py

Measurement script for Phase 2b (Requirement 1):
- Measures PDF page count, character count, token count, chunk count
- Indexes chunks in an isolated Chroma collection
- Retrieves chunks for "explain this to me" and "explain the pdf"
- Records raw output to data/measure/<timestamp>_phase2b_baseline.txt
"""

import datetime
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.attachments.extractor import extract_text_from_pdf
from backend.attachments.chunker import chunk_document_pages, estimate_tokens
from backend.attachments.storage import AttachmentStorage

def main():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    measure_dir = ROOT_DIR / "data" / "measure"
    measure_dir.mkdir(parents=True, exist_ok=True)
    out_file = measure_dir / f"{timestamp}_phase2b_baseline.txt"

    pdf_path = ROOT_DIR / "tests" / "real_samples" / "Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf"
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found.")
        sys.exit(1)

    pdf_bytes = pdf_path.read_bytes()
    pages = extract_text_from_pdf(pdf_bytes)
    total_chars = sum(len(p.text) for p in pages)
    total_tokens = sum(estimate_tokens(p.text) for p in pages)
    chunks = chunk_document_pages("sample_conv", "Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf", pages)

    # Use isolated Chroma collection with Ollama embedding
    import tempfile
    import chromadb
    from backend.config import get_settings
    from backend.models.ollama_shared import get_shared_embedding_settings

    cfg = get_settings()
    temp_dir = Path(tempfile.mkdtemp())
    chroma_client = chromadb.PersistentClient(path=str(temp_dir))
    collection = chroma_client.create_collection("baseline_measure")

    import httpx
    def embed_texts(texts):
        emb_settings = get_shared_embedding_settings()
        res = httpx.post(
            f"{cfg.local_host}/api/embed",
            json={"model": emb_settings["model"], "input": texts, "options": emb_settings["options"], "keep_alive": emb_settings["keep_alive"]},
            timeout=30.0
        )
        return res.json()["embeddings"]

    # Index chunks
    chunk_texts = [c.text for c in chunks]
    chunk_metas = [{"chunk_id": c.chunk_id, "page": c.page_number, "citation": c.citation()} for c in chunks]
    chunk_ids = [c.chunk_id for c in chunks]

    # Batch embed
    embeddings = embed_texts(chunk_texts)
    collection.add(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=chunk_texts,
        metadatas=chunk_metas
    )

    queries = ["explain this to me", "explain the pdf"]
    retrievals = {}

    for q in queries:
        q_emb = embed_texts([q])[0]
        res = collection.query(query_embeddings=[q_emb], n_results=5)
        retrievals[q] = {
            "ids": res["ids"][0],
            "metadatas": res["metadatas"][0],
            "documents": res["documents"][0]
        }

    # Format report
    lines = []
    lines.append("================================================================================")
    lines.append("HINAKU PHASE 2B: REAL SAMPLE PDF BASELINE MEASUREMENT")
    lines.append(f"Timestamp: {datetime.datetime.now().isoformat()}")
    lines.append(f"File: {pdf_path.name}")
    lines.append(f"File Size: {len(pdf_bytes)} bytes ({len(pdf_bytes)/1024:.1f} KB)")
    lines.append("================================================================================")
    lines.append("")
    lines.append(f"PAGE COUNT: {len(pages)}")
    lines.append(f"CHARACTER COUNT: {total_chars}")
    lines.append(f"TOKEN COUNT (ESTIMATED): {total_tokens}")
    lines.append(f"CHUNKS GENERATED: {len(chunks)} (chunk_size=500 tokens, overlap=50 tokens)")
    lines.append("")
    lines.append("PER-PAGE BREAKDOWN:")
    for p in pages:
        lines.append(f"  Page {p.page_number:2d}: {len(p.text):5d} chars | {repr(p.text[:60])}...")
    lines.append("")
    lines.append("================================================================================")
    lines.append("RETRIEVAL FOR QUERY: 'explain this to me'")
    lines.append("================================================================================")
    for rank, (cid, meta, doc) in enumerate(zip(retrievals["explain this to me"]["ids"], retrievals["explain this to me"]["metadatas"], retrievals["explain this to me"]["documents"]), 1):
        lines.append(f"[Rank {rank}] Chunk ID: {cid} | Page: {meta.get('page')} | Citation: {meta.get('citation')}")
        lines.append(f"Excerpt: {repr(doc[:180])}...")
        lines.append("")

    lines.append("================================================================================")
    lines.append("RETRIEVAL FOR QUERY: 'explain the pdf'")
    lines.append("================================================================================")
    for rank, (cid, meta, doc) in enumerate(zip(retrievals["explain the pdf"]["ids"], retrievals["explain the pdf"]["metadatas"], retrievals["explain the pdf"]["documents"]), 1):
        lines.append(f"[Rank {rank}] Chunk ID: {cid} | Page: {meta.get('page')} | Citation: {meta.get('citation')}")
        lines.append(f"Excerpt: {repr(doc[:180])}...")
        lines.append("")

    content_str = "\n".join(lines) + "\n"
    out_file.write_text(content_str, encoding="utf-8")
    print(f"Report written to: {out_file}")
    print(content_str)

if __name__ == "__main__":
    main()
