"""
scripts/audit_chroma_vectors.py

Inspects Chroma document vector collection:
- Collection name
- Chunk count per document (Security Notes vs Game Mechanics Notes)
- Embedding dimension
- Vector similarity and retrieved chunk text for Q8 ("What are Bartle's four player types?")
Outputs raw result to data/measure/<timestamp>_chroma_vector_audit.txt
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["HINAKU_PROFILE_OLLAMA"] = "1"
os.environ["HINAKU_USE_REAL_DATA"] = "0"

import datetime
import base64
import chromadb
from fastapi.testclient import TestClient
from backend.main import app
from backend.api.attachments import attachment_manager
from backend.config import get_settings

now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
output_path = ROOT / "data" / "measure" / f"{now_str}_chroma_vector_audit.txt"
output_path.parent.mkdir(parents=True, exist_ok=True)

client = TestClient(app)
lines = []
lines.append("COMMAND: python scripts/audit_chroma_vectors.py")
lines.append(f"TIMESTAMP: {datetime.datetime.now().isoformat()}")
lines.append("=" * 80)
lines.append("CHROMA VECTOR & EMBEDDINGS AUDIT")
lines.append("=" * 80)

# Setup conversations and upload both documents
sec_pdf = ROOT / "tests/real_samples/Security, Ethics & Regulations in AI - Midterm Notes.pdf"
gm_pdf = ROOT / "tests/real_samples/Game Mechanics, Design & Development - Midterm Notes for Units 1 and 2.pdf"

conv1_res = client.post("/api/conversations", json={"title": "Audit Conv - Security Notes"})
conv1_id = conv1_res.json()["id"]
with open(sec_pdf, "rb") as f:
    sec_b64 = base64.b64encode(f.read()).decode("utf-8")
client.post(
    f"/api/conversations/{conv1_id}/attachments",
    json={"files": [{"filename": sec_pdf.name, "content_base64": sec_b64, "mime_type": "application/pdf"}]}
)

conv2_res = client.post("/api/conversations", json={"title": "Audit Conv - Game Mechanics"})
conv2_id = conv2_res.json()["id"]
with open(gm_pdf, "rb") as f:
    gm_b64 = base64.b64encode(f.read()).decode("utf-8")
client.post(
    f"/api/conversations/{conv2_id}/attachments",
    json={"files": [{"filename": gm_pdf.name, "content_base64": gm_b64, "mime_type": "application/pdf"}]}
)

# Inspect Chroma collection directly
storage = attachment_manager.storage
collection_name = storage.doc_collection.name
total_chroma_chunks = storage.doc_collection.count()

# Count chunks per conversation in Chroma
sec_chroma = storage.doc_collection.get(where={"conversation_id": conv1_id}, include=["metadatas", "embeddings", "documents"])
gm_chroma = storage.doc_collection.get(where={"conversation_id": conv2_id}, include=["metadatas", "embeddings", "documents"])

sec_chunk_count = len(sec_chroma["ids"]) if sec_chroma and "ids" in sec_chroma else 0
gm_chunk_count = len(gm_chroma["ids"]) if gm_chroma and "ids" in gm_chroma else 0

embedding_dim = 0
if gm_chroma and gm_chroma.get("embeddings") is not None and len(gm_chroma["embeddings"]) > 0:
    embedding_dim = len(gm_chroma["embeddings"][0])
elif sec_chroma and sec_chroma.get("embeddings") is not None and len(sec_chroma["embeddings"]) > 0:
    embedding_dim = len(sec_chroma["embeddings"][0])

lines.append(f"Chroma Collection Name: {collection_name}")
lines.append(f"Total Chunks in Collection: {total_chroma_chunks}")
lines.append(f"Security Notes Chunk Count: {sec_chunk_count}")
lines.append(f"Game Mechanics Chunk Count: {gm_chunk_count}")
lines.append(f"Embedding Dimension: {embedding_dim}")
lines.append("-" * 80)

# Check Q8 retrieval
q8_query = "What are Bartle's four player types described in the game mechanics notes?"
lines.append(f"Testing Q8 Query: {q8_query}")

# 1. Direct Chroma vector query
query_emb = storage.embed_fn([q8_query])[0]
lines.append(f"Query Embedding Dimension: {len(query_emb)}")

raw_chroma_results = storage.doc_collection.query(
    query_embeddings=[query_emb],
    n_results=5,
    where={"conversation_id": conv2_id},
    include=["documents", "metadatas", "distances"]
)

lines.append("\n[Direct Chroma Vector Query Results for Q8]")
if raw_chroma_results and raw_chroma_results.get("documents"):
    docs = raw_chroma_results["documents"][0]
    metas = raw_chroma_results["metadatas"][0]
    dists = raw_chroma_results["distances"][0]
    for idx, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
        vec_sim = max(0.0, 1.0 - dist)
        lines.append(f"Rank {idx+1}: vec_sim={vec_sim:.4f} (distance={dist:.4f}) | page={meta.get('page_number')} | section_title='{meta.get('section_title')}'")
        lines.append(f"Chunk text (first 250 chars):\n{doc[:250]}...\n")
else:
    lines.append("NO CHROMA RESULTS RETURNED!")

# 2. Pipeline get_document_context_for_query
lines.append("-" * 80)
lines.append("[Pipeline get_document_context_for_query for Q8]")
raw_ctx, cov = attachment_manager.get_document_prompt_context(conv2_id, q8_query)
lines.append(f"Gate Info: {cov.get('gate')}")
lines.append(f"Retrieved Sections: {cov.get('sections')}")
lines.append(f"Retrieved Pages: {cov.get('pages')}")
lines.append(f"Context Text Preview (first 500 chars):\n{raw_ctx[:500]}...")

out_text = "\n".join(lines) + "\n"
output_path.write_text(out_text, encoding="utf-8")
print(out_text)
print(f"Saved to {output_path}")
