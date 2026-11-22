"""
backend/attachments/storage.py

Storage engine for file attachments:
- Physical files in data/uploads/<conversation_id>/
- SQLite attachments table in data/hinaku.db
- Isolated Chroma collection 'hinaku_documents' (never memories)
- Vector embedding with qwen3-embedding:0.6b
- Cascading hard delete (files, sqlite row, chroma chunks, VACUUM)
"""

import datetime
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import get_settings
from backend.models.ollama_shared import get_shared_embedding_settings, log_ollama_call
from backend.database.backup import coordinated_write, get_write_coordinator
from .chunker import DocumentChunk, estimate_tokens, MAX_WHOLE_FILE_TOKENS

logger = logging.getLogger("hinaku.attachments.storage")

def l2_normalize(v: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]

class AttachmentStorage:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        uploads_dir: Optional[Path] = None,
        chroma_dir: Optional[Path] = None,
        embed_fn = None
    ):
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else settings.sqlite_path
        self.uploads_dir = Path(uploads_dir) if uploads_dir else (settings.data_dir / "uploads")
        self.chroma_dir = Path(chroma_dir) if chroma_dir else settings.chroma_dir
        self.embed_fn = embed_fn or self._default_embedder

        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()

        # Register handle release/reopen callbacks with write coordinator
        try:
            coord = get_write_coordinator()
            coord.register_handle_release_callback(self.close)
            coord.register_handle_reopen_callback(self.reopen)
        except Exception as e:
            logger.warning(f"Could not register handle callbacks with coordinator: {e}")

    def close(self):
        """Release ChromaDB client resources and close open handles."""
        try:
            if hasattr(self, "chroma_client") and self.chroma_client is not None:
                self.chroma_client._system.stop()
                self.chroma_client = None
                self.doc_collection = None
                logger.info("AttachmentStorage: Chroma client handles successfully closed.")
        except Exception as e:
            logger.warning(f"Error stopping Chroma client during handle release: {e}")

    def reopen(self):
        """Reopen ChromaDB client after restoration or maintenance."""
        self._init_chroma()
        logger.info("AttachmentStorage: Chroma client handles successfully re-initialized.")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_sqlite(self):
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    token_count INTEGER DEFAULT 0,
                    extracted_text TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attachment_sections (
                    id TEXT PRIMARY KEY,
                    attachment_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    unit_name TEXT,
                    topic_number INTEGER,
                    title TEXT NOT NULL,
                    start_page INTEGER NOT NULL,
                    end_page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    section_order INTEGER NOT NULL,
                    explanation_cache TEXT,
                    section_type TEXT DEFAULT 'topic',
                    is_study_aid INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (attachment_id) REFERENCES attachments(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_attachments_conv ON attachments (conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_sections_att ON attachment_sections (attachment_id, section_order ASC);
            """)

            # Graceful migration for existing databases
            try:
                conn.execute("ALTER TABLE attachment_sections ADD COLUMN section_type TEXT DEFAULT 'topic';")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE attachment_sections ADD COLUMN is_study_aid INTEGER DEFAULT 0;")
            except Exception:
                pass

    def _init_chroma(self):
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        # Dedicated collection for documents with cosine distance; strictly isolated from memories
        try:
            self.doc_collection = self.chroma_client.get_or_create_collection(
                name="hinaku_documents",
                metadata={"hnsw:space": "cosine", "description": "Isolated document attachment text chunks"}
            )
        except Exception:
            try:
                self.chroma_client.delete_collection("hinaku_documents")
            except Exception:
                pass
            self.doc_collection = self.chroma_client.create_collection(
                name="hinaku_documents",
                metadata={"hnsw:space": "cosine", "description": "Isolated document attachment text chunks"}
            )

    def _default_embedder(self, texts: List[str]) -> List[List[float]]:
        settings = get_settings()
        model = settings.embedding_model
        host = settings.local_host
        shared = get_shared_embedding_settings(override_model=model)

        body = json.dumps({
            "model": model,
            "input": texts,
            "keep_alive": shared["keep_alive"],
            "options": {"num_ctx": shared["options"]["num_ctx"]}
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw = data.get("embeddings", [])
                log_ollama_call(
                    call_type="document_embeddings",
                    model=model,
                    num_ctx=shared["options"]["num_ctx"],
                    keep_alive=shared["keep_alive"],
                    options={"num_ctx": shared["options"]["num_ctx"]},
                    load_duration_ns=data.get("load_duration", 0),
                    total_duration_ns=data.get("total_duration", 0),
                    extra_info=f"embedded {len(texts)} doc chunks"
                )
                return [l2_normalize(e) for e in raw]
        except Exception as e:
            logger.warning(f"Default embedder failed to call Ollama: {e}. Falling back to deterministic offline vectors.")
            import hashlib
            out = []
            for t in texts:
                vec = [0.0] * 128
                for w in t.split():
                    h = int(hashlib.md5(w.encode()).hexdigest(), 16) % 128
                    vec[h] += 1.0
                out.append(l2_normalize(vec))
            return out

    @coordinated_write("attachment_storage")
    def save_attachment(
        self,
        conversation_id: str,
        filename: str,
        file_bytes: bytes,
        file_type: str,
        mime_type: str,
        extracted_text: str = "",
        chunks: Optional[List[DocumentChunk]] = None,
        sections: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Saves attachment file to disk, persists metadata to SQLite,
        persists outline sections if present, and indexes chunks in Chroma.
        """
        attachment_id = str(uuid.uuid4())
        created_at = datetime.datetime.now().isoformat()

        # Save physical file
        conv_folder = self.uploads_dir / conversation_id
        conv_folder.mkdir(parents=True, exist_ok=True)
        target_path = conv_folder / f"{attachment_id}_{filename}"
        target_path.write_bytes(file_bytes)

        token_count = estimate_tokens(extracted_text)

        # SQLite insert
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO attachments (
                    id, conversation_id, filename, stored_path,
                    file_type, mime_type, size_bytes, token_count,
                    extracted_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                attachment_id, conversation_id, filename, str(target_path),
                file_type, mime_type, len(file_bytes), token_count,
                extracted_text, created_at
            ))

            if sections:
                for sec in sections:
                    sec_id = f"{attachment_id}_s{sec.section_order}"
                    sec_type = getattr(sec, "section_type", "topic")
                    is_aid = 1 if getattr(sec, "is_study_aid", False) else 0
                    conn.execute("""
                        INSERT INTO attachment_sections (
                            id, attachment_id, conversation_id, unit_name,
                            topic_number, title, start_page, end_page,
                            text, token_count, section_order, explanation_cache,
                            section_type, is_study_aid, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sec_id, attachment_id, conversation_id, sec.unit_name,
                        sec.topic_number, sec.title, sec.start_page, sec.end_page,
                        sec.text, sec.token_count, sec.section_order, None,
                        sec_type, is_aid, created_at
                    ))

        # Index chunks in Chroma if text chunks exist
        if chunks:
            # Update chunk_id with real attachment_id
            for c in chunks:
                c.attachment_id = attachment_id
                c.chunk_id = f"{attachment_id}_p{c.page_number}_c{c.chunk_index}"

            chunk_texts = [c.text for c in chunks]
            chunk_ids = [c.chunk_id for c in chunks]
            metadatas = []
            for c in chunks:
                matched_sec_title = ""
                best_sec = None
                if sections:
                    # Match by checking if section title or key terms are in chunk text
                    for s in sections:
                        s_title = getattr(s, "title", "")
                        clean_title = re.sub(r"^(?:Topic|Session|Section|\d+[\.\s\-]+)+", "", s_title, flags=re.IGNORECASE).strip()
                        if (clean_title and clean_title.lower() in c.text.lower()) or (s_title and s_title.lower() in c.text.lower()):
                            best_sec = s
                            break
                    # Fallback to page range
                    if not best_sec:
                        for s in sections:
                            sp = getattr(s, "start_page", 1)
                            ep = getattr(s, "end_page", sp)
                            if sp <= c.page_number <= ep:
                                best_sec = s
                                break
                    if best_sec:
                        matched_sec_title = getattr(best_sec, "title", "")
                metadatas.append({
                    "attachment_id": attachment_id,
                    "conversation_id": conversation_id,
                    "filename": filename,
                    "page_number": c.page_number,
                    "chunk_index": c.chunk_index,
                    "citation": c.citation(),
                    "section_title": matched_sec_title
                })

            # Also index sections directly as dedicated semantic documents
            if sections:
                for s in sections:
                    s_title = getattr(s, "title", "").strip()
                    s_text = (getattr(s, "text", "") or "").strip()
                    if s_title and s_text:
                        s_doc = f"{s_title}\n\n{s_text}"
                        sec_chunk_id = f"{attachment_id}_sec_{getattr(s, 'section_order', 0)}"
                        chunk_ids.append(sec_chunk_id)
                        chunk_texts.append(s_doc)
                        metadatas.append({
                            "attachment_id": attachment_id,
                            "conversation_id": conversation_id,
                            "filename": filename,
                            "page_number": getattr(s, "start_page", 1),
                            "chunk_index": getattr(s, "section_order", 0),
                            "citation": f"[File: {filename}, Page: {getattr(s, 'start_page', 1)}]",
                            "section_title": s_title
                        })

            embeddings = self.embed_fn(chunk_texts)
            try:
                self.doc_collection.add(
                    ids=chunk_ids,
                    embeddings=embeddings,
                    documents=chunk_texts,
                    metadatas=metadatas
                )
            except Exception as e:
                if "dimension" in str(e).lower():
                    logger.warning(f"Dimension mismatch in document collection. Recreating collection: {e}")
                    try:
                        self.chroma_client.delete_collection("hinaku_documents")
                    except Exception:
                        pass
                    self.doc_collection = self.chroma_client.create_collection(
                        name="hinaku_documents",
                        metadata={"hnsw:space": "cosine", "description": "Isolated document attachment text chunks"}
                    )
                    self.doc_collection.add(
                        ids=chunk_ids,
                        embeddings=embeddings,
                        documents=chunk_texts,
                        metadatas=metadatas
                    )
                else:
                    raise

        return {
            "id": attachment_id,
            "conversation_id": conversation_id,
            "filename": filename,
            "file_type": file_type,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
            "token_count": token_count,
            "created_at": created_at
        }

    def list_attachments(self, conversation_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT id, conversation_id, filename, file_type, mime_type,
                       size_bytes, token_count, created_at
                FROM attachments
                WHERE conversation_id = ?
                ORDER BY created_at ASC
            """, (conversation_id,)).fetchall()
            return [dict(r) for r in rows]

    def has_attachments(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM attachments WHERE conversation_id = ?",
                (conversation_id,)
            ).fetchone()
            return bool(row["cnt"] > 0)

    def get_sections(
        self,
        conversation_id: str,
        unit_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves structured document sections in reading order."""
        with self._get_connection() as conn:
            if unit_name:
                rows = conn.execute("""
                    SELECT * FROM attachment_sections
                    WHERE conversation_id = ? AND unit_name = ?
                    ORDER BY section_order ASC
                """, (conversation_id, unit_name)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM attachment_sections
                    WHERE conversation_id = ?
                    ORDER BY section_order ASC
                """, (conversation_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_section_by_id(self, section_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM attachment_sections WHERE id = ?", (section_id,)).fetchone()
            return dict(row) if row else None

    @coordinated_write("attachment_storage")
    def update_section_cache(self, section_id: str, explanation_cache: str) -> None:
        """Caches generated topic walkthrough in SQLite so retries/continues do not recompute."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE attachment_sections
                SET explanation_cache = ?
                WHERE id = ?
            """, (explanation_cache, section_id))

    def get_document_outline_summary(self, conversation_id: str) -> Dict[str, Any]:
        """Returns outline summary: document title, units list, topic counts, study aids, and formatted intro string."""
        sections = self.get_sections(conversation_id)
        if not sections:
            return {
                "title": "Document",
                "units": [],
                "topics": [],
                "total_topics": 0,
                "study_aids": [],
                "study_aids_count": 0,
                "intro_text": "Your notes contain topics to learn step by step."
            }

        # Separate study aids from regular learning topics
        topics = [
            s for s in sections
            if not s.get("is_study_aid") and s.get("section_type") != "study_aid"
        ]
        study_aids = [
            s for s in sections
            if s.get("is_study_aid") or s.get("section_type") == "study_aid"
        ]

        units: List[str] = []
        for s in topics:
            u = s.get("unit_name") or "Unit 1"
            if u not in units:
                units.append(u)
        if not units:
            units = ["Unit 1"]

        # Counts per unit
        unit1_topics = [s for s in topics if "UNIT 1" in (s.get("unit_name") or "").upper()]
        unit2_topics = [s for s in topics if "UNIT 2" in (s.get("unit_name") or "").upper()]

        # Determine if unit 2 uses sessions or topics
        unit2_has_sessions = any("session" in (s.get("title") or "").lower() for s in unit2_topics)
        unit2_label = "sessions" if unit2_has_sessions else "topics"

        # Construct exact preamble description (e.g. "2 units, 9 topics in Unit 1, 5 sessions in Unit 2, plus 3 study aids")
        parts = []
        parts.append(f"{len(units)} units")
        if unit1_topics:
            parts.append(f"{len(unit1_topics)} topics in Unit 1")
        if unit2_topics:
            parts.append(f"{len(unit2_topics)} {unit2_label} in Unit 2")
        intro_desc = ", ".join(parts)
        if study_aids:
            intro_desc += f", plus {len(study_aids)} study aids"

        # Determine document title from attachment record or first section
        doc_title = "Study Notes"
        with self._get_connection() as conn:
            att_row = conn.execute("SELECT filename FROM attachments WHERE conversation_id = ? ORDER BY created_at ASC LIMIT 1", (conversation_id,)).fetchone()
            if att_row:
                doc_title = att_row["filename"]
                if doc_title.endswith(".pdf") or doc_title.endswith(".html") or doc_title.endswith(".docx"):
                    doc_title = doc_title.rsplit(".", 1)[0]

        return {
            "title": doc_title,
            "units": units,
            "unit_count": len(units),
            "topics": [s.get("title") for s in topics],
            "total_topics": len(topics),
            "study_aids": [s.get("title") for s in study_aids],
            "study_aids_count": len(study_aids),
            "unit1_count": len(unit1_topics),
            "unit2_count": len(unit2_topics),
            "unit1_name": unit1_topics[0].get("unit_name") if unit1_topics else "Unit 1",
            "unit2_name": unit2_topics[0].get("unit_name") if unit2_topics else "Unit 2",
            "intro_desc": intro_desc,
            "sections": sections
        }

    def get_document_context_for_query(
        self,
        conversation_id: str,
        query_text: str,
        top_k: int = 5,
        min_similarity: float = 0.35
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Hybrid retrieval (outline keywords + vector similarity) with strict intent gating:
        - Evaluates document gate: explicit cues ("notes", "Session 8", "Topic 1", "exam themes")
          and section keywords trigger retrieval.
        - Clearly unrelated chatter/coding/hardware questions ("can you code", "CPUs vs GPUs")
          get NO document context and return empty.
        - Combines section-level keyword matching and chunk-level Chroma vector search.
        - Returns (context_text, coverage_metadata) with exact outline metadata for code citations.
        """
        q_lower = query_text.strip().lower()
        if not q_lower:
            gate_info = {"query": query_text, "decision": "skip", "reason": "empty_query", "similarity": 0.0}
            return "", {"sections": [], "pages": [], "sections_meta": [], "gate": gate_info}

        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT id, filename, extracted_text, token_count
                FROM attachments
                WHERE conversation_id = ? AND file_type IN ('text', 'pdf', 'docx')
                ORDER BY created_at ASC
            """, (conversation_id,)).fetchall()

        if not rows:
            gate_info = {"query": query_text, "decision": "skip", "reason": "no_attachments_found", "similarity": 0.0}
            return "", {"sections": [], "pages": [], "sections_meta": [], "gate": gate_info}

        sections = self.get_sections(conversation_id)
        outline_summary = self.get_document_outline_summary(conversation_id)
        total_tokens = sum(r["token_count"] or 0 for r in rows)

        # 1. Gate: Check conversational greetings / chit-chat
        greetings = {
            "hi", "hello", "hey", "howdy", "sup", "good morning", "good evening",
            "good night", "thanks", "thank you", "bye", "who are you",
            "what can you do", "tell me a joke", "what are you"
        }
        words = set(re.findall(r"\b[a-z]+\b", q_lower))
        if words and words.issubset(greetings):
            gate_info = {"query": query_text, "decision": "skip", "reason": "conversational_greeting", "similarity": 0.0}
            logger.info(f"[Gate] query='{query_text[:50]}' | decision=skip | reason=conversational_greeting")
            return "", {"sections": [], "pages": [], "sections_meta": [], "gate": gate_info}

        # 2. Gate: Check explicit document cues
        sec_num_match = re.search(r"(?i)\b(?:Topic|Session|Section)\s+(\d+)\b", query_text)
        target_topic_num = int(sec_num_match.group(1)) if sec_num_match else None

        unit_num_match = re.search(r"(?i)\bUnit\s+(\d+)\b", query_text)
        target_unit_num = int(unit_num_match.group(1)) if unit_num_match else None

        doc_cues_pat = r"(?i)\b(?:notes|document|pdf|syllabus|midterm|exam|themes|cheat\s*sheet|according\s+to|from\s+the|in\s+the\s+notes|session\s*\d+|topic\s*\d+|section\s*\d+|unit\s*\d+)\b"
        has_explicit_doc_cue = bool(re.search(doc_cues_pat, query_text)) or (target_topic_num is not None)

        # Check section title and keyword matches across outline sections
        matched_sections = []
        if target_topic_num is not None:
            for s in sections:
                t_lower = (s.get("title") or "").lower()
                s_topic_num = s.get("topic_number")
                if s_topic_num == target_topic_num:
                    if s not in matched_sections:
                        matched_sections.append(s)
                    break
                if (f"topic {target_topic_num}" in t_lower or 
                    f"session {target_topic_num}" in t_lower or 
                    f"section {target_topic_num}" in t_lower or 
                    t_lower.startswith(f"{target_topic_num}.") or
                    t_lower.startswith(f"{target_topic_num} ")):
                    if s not in matched_sections:
                        matched_sections.append(s)
                    break

        # Match key domain concepts directly to their authoritative sections
        topic_kw_mappings = [
            (["bartle", "player types"], ["player types"]),
            (["mda"], ["mda framework"]),
            (["prototyping", "prototype"], ["prototyping"]),
            (["game economy", "economy design"], ["game economy"]),
            (["transforms", "object parenting"], ["transforms"]),
            (["cheat sheet"], ["cheat sheet"]),
            (["ai triad"], ["ai triad"]),
            (["evasion", "poisoning"], ["evasion"]),
            (["mlsecops"], ["mlsecops"]),
            (["mitre", "atlas"], ["atlas"]),
            (["exam themes"], ["exam themes"]),
            (["15-puzzle", "sliding puzzle", "solvability"], ["15-puzzle", "sliding puzzle"]),
            (["genres", "simulation", "sports"], ["genres"]),
            (["provenance", "lineage"], ["provenance"]),
            (["hardware", "cpus vs gpus", "cpu and gpu"], ["hardware foundations", "cpus vs gpus"]),
        ]
        for query_terms, title_terms in topic_kw_mappings:
            if any(term in q_lower for term in query_terms):
                for s in sections:
                    s_t = (s.get("title") or "").lower()
                    if any(tt in s_t for tt in title_terms):
                        if s not in matched_sections:
                            matched_sections.append(s)
                        break

        q_words = set(re.findall(r"\b[a-z0-9]{3,}\b", q_lower)) - {"what", "when", "where", "which", "with", "from", "that", "this", "explain", "describe", "compare", "between", "tell", "show"}
        for s in sections:
            s_title_lower = s["title"].lower()
            s_words = set(re.findall(r"\b[a-z0-9]{3,}\b", s_title_lower))
            overlap = q_words.intersection(s_words)
            if len(overlap) >= 2 or (len(overlap) >= 1 and any(len(w) >= 6 for w in overlap)):
                if s not in matched_sections:
                    matched_sections.append(s)

        # 3. Check for clearly unrelated general coding / hardware queries (e.g. factorial, cpus vs gpus)
        unrelated_general_pat = (
            r"(?i)\b(?:can\s+you\s+code|learn\s+python|recursive|factorial|binary\s+tree|async\s+python|why\s+might\s+a\s+company)\b"
            r"|\bcpus?\b.*?\b(?:and|vs|versus)\b.*?\bgpus?\b"
            r"|\bgpus?\b.*?\b(?:and|vs|versus)\b.*?\bcpus?\b"
        )
        is_unrelated_general = bool(re.search(unrelated_general_pat, query_text)) and not has_explicit_doc_cue and not any(term in q_lower for term in ["notes", "document", "topic", "section", "session", "unit"])

        if is_unrelated_general:
            gate_info = {"query": query_text, "decision": "skip", "reason": "unrelated_general_query", "similarity": 0.0}
            logger.info(f"[Gate] query='{query_text[:50]}' | decision=skip | reason=unrelated_general_query")
            return "", {"sections": [], "pages": [], "sections_meta": [], "gate": gate_info}

        # 4. Small document fast-path (under 2500 tokens)
        if total_tokens <= MAX_WHOLE_FILE_TOKENS:
            blocks = []
            pages_used = set()
            for r in rows:
                if r["extracted_text"]:
                    blocks.append(f"--- Document: {r['filename']} ---\n{r['extracted_text']}\n--- End of {r['filename']} ---")
            gate_info = {"query": query_text, "decision": "retrieve", "reason": "whole_document_under_limit", "similarity": 1.0}
            coverage = {
                "sections": [s["title"] for s in sections[:4]] if sections else ["Full Document"],
                "pages": [1],
                "sections_meta": [{"title": s["title"], "start_page": s["start_page"], "end_page": s["end_page"]} for s in sections[:4]],
                "gate": gate_info
            }
            return "\n\n".join(blocks), coverage

        # 5. Hybrid Retrieval: Vector query + Section/lexical boost
        query_emb = self.embed_fn([query_text])[0]
        results = self.doc_collection.query(
            query_embeddings=[query_emb],
            n_results=min(top_k + 4, 15),
            where={"conversation_id": conversation_id},
            include=["documents", "metadatas", "distances"]
        )

        retrieved_docs = results.get("documents", [[]])[0]
        retrieved_metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0] if "distances" in results and results["distances"] else [0.0] * len(retrieved_docs)

        scored_chunks = []
        max_vec_sim = 0.0
        space = (self.doc_collection.metadata or {}).get("hnsw:space", "cosine")

        for doc, meta, dist in zip(retrieved_docs, retrieved_metas, distances):
            if space == "cosine":
                vec_sim = max(0.0, 1.0 - dist)
            else:
                vec_sim = max(0.0, 1.0 - (dist / 2.0))
            if vec_sim > max_vec_sim:
                max_vec_sim = vec_sim

            # Lexical scoring
            doc_lower = doc.lower()
            doc_words = set(re.findall(r"\b[a-z0-9]{3,}\b", doc_lower))
            overlap_count = len(q_words.intersection(doc_words))
            kw_score = min(1.0, overlap_count * 0.25)

            # Section match bonus: match by exact section_title metadata
            sec_bonus = 0.0
            chunk_sec_title = meta.get("section_title", "").strip().lower()
            chunk_page_num = meta.get("page_number", 1)
            for ms in matched_sections:
                ms_title = (ms.get("title") or "").strip().lower()
                if chunk_sec_title and ms_title == chunk_sec_title:
                    sec_bonus = 0.80
                    break
                elif ms["start_page"] <= chunk_page_num <= ms["end_page"]:
                    sec_bonus = 0.15

            hybrid_score = 0.4 * vec_sim + 0.3 * kw_score + 0.3 * sec_bonus
            scored_chunks.append({
                "doc": doc,
                "meta": meta,
                "vec_sim": vec_sim,
                "hybrid_score": hybrid_score
            })

        # Rank by hybrid score
        scored_chunks.sort(key=lambda x: x["hybrid_score"], reverse=True)

        valid_entries = []
        for item in scored_chunks:
            # Include if hybrid score >= 0.25 or vec_sim >= min_similarity or matched section
            if item["hybrid_score"] >= 0.25 or item["vec_sim"] >= min_similarity:
                valid_entries.append((item["doc"], item["meta"]))
            if len(valid_entries) >= top_k:
                break

        # If vector search missed an explicitly matched outline section (e.g. Bartle or Session 8), inject it directly
        if matched_sections:
            for ms in matched_sections[:3]:
                already_covered = any(ms["title"].lower() == (m.get("section_title") or "").lower() for _, m in valid_entries)
                if not already_covered and ms.get("text"):
                    synth_meta = {
                        "filename": rows[0]["filename"],
                        "page_number": ms["start_page"],
                        "citation": f"[File: {rows[0]['filename']}, Page: {ms['start_page']}]",
                        "section_title": ms["title"]
                    }
                    valid_entries.insert(0, (f"{ms['title']}\n\n{ms['text'][:1200]}", synth_meta))

        # Gate threshold check: if no entries qualify and no section matched
        if not valid_entries:
            gate_info = {"query": query_text, "decision": "skip", "reason": "no_relevant_chunks_above_threshold", "similarity": round(max_vec_sim, 4)}
            logger.info(f"[Gate] query='{query_text[:50]}' | decision=skip | reason=no_relevant_chunks | max_sim={max_vec_sim:.4f}")
            return "", {"sections": [], "pages": [], "sections_meta": [], "gate": gate_info}

        # Build outline summary header
        outline_lines = []
        if outline_summary.get("units"):
            outline_lines.append(f"[Document Outline: {rows[0]['filename']}]")
            outline_lines.append(f"Units: {', '.join(outline_summary['units'])}")
            if outline_summary.get("topics"):
                sample_topics = outline_summary["topics"][:8]
                outline_lines.append(f"Sample Topics ({len(outline_summary['topics'])} total): {'; '.join(sample_topics)}...")
            outline_lines.append("")

        chunk_blocks = ["\n".join(outline_lines)] if outline_lines else []
        sections_used_meta = []
        pages_used = []

        for doc, meta in valid_entries:
            page_num = meta.get("page_number", 1)
            filename = meta.get("filename", "document")
            citation = meta.get("citation", f"[File: {filename}, Page: {page_num}]")
            pages_used.append(page_num)

            # Match chunk with its outline section metadata
            matched_sec_obj = None
            meta_sec_title = (meta.get("section_title") or "").strip().lower()
            if meta_sec_title:
                for s in sections:
                    if s["title"].strip().lower() == meta_sec_title:
                        matched_sec_obj = s
                        break
            if not matched_sec_obj:
                for s in sections:
                    if s["start_page"] <= page_num <= s["end_page"]:
                        matched_sec_obj = s
                        break

            if matched_sec_obj and matched_sec_obj not in sections_used_meta:
                sections_used_meta.append(matched_sec_obj)

            sec_label = f"[Section: {matched_sec_obj['title']}] " if matched_sec_obj else ""
            chunk_blocks.append(f"{citation} {sec_label}\n{doc}")

        sections_used_titles = [s["title"] for s in sections_used_meta]
        gate_info = {
            "query": query_text,
            "decision": "retrieve",
            "reason": "hybrid_match_above_threshold",
            "similarity": round(max_vec_sim, 4)
        }
        logger.info(f"[Gate] query='{query_text[:50]}' | decision=retrieve | reason=hybrid_match | max_sim={max_vec_sim:.4f} | sections={sections_used_titles}")

        coverage = {
            "sections": sections_used_titles or ["Relevant Excerpts"],
            "pages": sorted(list(set(pages_used))),
            "sections_meta": [
                {"title": s["title"], "start_page": s["start_page"], "end_page": s["end_page"]}
                for s in sections_used_meta
            ],
            "gate": gate_info
        }

        return "\n\n".join(chunk_blocks), coverage

    @coordinated_write("attachment_storage")
    def delete_attachment(self, attachment_id: str) -> bool:
        """
        Cascading hard delete for a single attachment:
        1. Remove physical file
        2. Delete chunks from Chroma
        3. Delete SQLite row
        4. Run SQLite VACUUM
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT stored_path, conversation_id FROM attachments WHERE id = ?",
                (attachment_id,)
            ).fetchone()
            if not row:
                return False

            stored_path = Path(row["stored_path"])
            conv_id = row["conversation_id"]

            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))

        # Delete physical file
        try:
            if stored_path.exists():
                stored_path.unlink()
            # Clean folder if empty
            folder = stored_path.parent
            if folder.exists() and not any(folder.iterdir()):
                folder.rmdir()
        except Exception as e:
            logger.warning(f"Failed deleting physical file {stored_path}: {e}")

        # Delete from Chroma
        try:
            self.doc_collection.delete(where={"attachment_id": attachment_id})
        except Exception as e:
            logger.warning(f"Failed deleting Chroma chunks for attachment {attachment_id}: {e}")

        # VACUUM SQLite
        self._vacuum_db()
        return True

    @coordinated_write("attachment_storage")
    def delete_conversation_attachments(self, conversation_id: str) -> int:
        """
        Cascades deletion for all attachments belonging to a conversation.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, stored_path FROM attachments WHERE conversation_id = ?",
                (conversation_id,)
            ).fetchall()
            if not rows:
                return 0

            conn.execute("DELETE FROM attachments WHERE conversation_id = ?", (conversation_id,))

        deleted_count = 0
        for r in rows:
            path = Path(r["stored_path"])
            try:
                if path.exists():
                    path.unlink()
                deleted_count += 1
            except Exception:
                pass

        # Remove folder
        conv_folder = self.uploads_dir / conversation_id
        if conv_folder.exists():
            shutil.rmtree(conv_folder, ignore_errors=True)

        # Delete from Chroma
        try:
            self.doc_collection.delete(where={"conversation_id": conversation_id})
        except Exception as e:
            logger.warning(f"Failed deleting Chroma chunks for conv {conversation_id}: {e}")

        # VACUUM SQLite
        self._vacuum_db()
        return deleted_count

    def _vacuum_db(self):
        try:
            with self._get_connection() as conn:
                conn.execute("VACUUM;")
        except Exception as e:
            logger.warning(f"SQLite VACUUM failed: {e}")
