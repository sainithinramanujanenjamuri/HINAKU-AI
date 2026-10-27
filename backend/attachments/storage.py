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
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (attachment_id) REFERENCES attachments(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_attachments_conv ON attachments (conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_sections_att ON attachment_sections (attachment_id, section_order ASC);
                CREATE INDEX IF NOT EXISTS idx_sections_conv ON attachment_sections (conversation_id, section_order ASC);
            """)

    def _init_chroma(self):
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        # Dedicated collection for documents; strictly isolated from memories
        try:
            self.doc_collection = self.chroma_client.get_or_create_collection(
                name="hinaku_documents",
                metadata={"description": "Isolated document attachment text chunks"}
            )
        except Exception:
            try:
                self.chroma_client.delete_collection("hinaku_documents")
            except Exception:
                pass
            self.doc_collection = self.chroma_client.create_collection(
                name="hinaku_documents",
                metadata={"description": "Isolated document attachment text chunks"}
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
                    conn.execute("""
                        INSERT INTO attachment_sections (
                            id, attachment_id, conversation_id, unit_name,
                            topic_number, title, start_page, end_page,
                            text, token_count, section_order, explanation_cache,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        sec_id, attachment_id, conversation_id, sec.unit_name,
                        sec.topic_number, sec.title, sec.start_page, sec.end_page,
                        sec.text, sec.token_count, sec.section_order, None,
                        created_at
                    ))

        # Index chunks in Chroma if text chunks exist
        if chunks:
            # Update chunk_id with real attachment_id
            for c in chunks:
                c.attachment_id = attachment_id
                c.chunk_id = f"{attachment_id}_p{c.page_number}_c{c.chunk_index}"

            chunk_texts = [c.text for c in chunks]
            chunk_ids = [c.chunk_id for c in chunks]
            metadatas = [
                {
                    "attachment_id": attachment_id,
                    "conversation_id": conversation_id,
                    "filename": filename,
                    "page_number": c.page_number,
                    "chunk_index": c.chunk_index,
                    "citation": c.citation()
                }
                for c in chunks
            ]
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
                        metadata={"description": "Isolated document attachment text chunks"}
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

    def update_section_cache(self, section_id: str, explanation_cache: str) -> None:
        """Caches generated topic walkthrough in SQLite so retries/continues do not recompute."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE attachment_sections
                SET explanation_cache = ?
                WHERE id = ?
            """, (explanation_cache, section_id))

    def get_document_outline_summary(self, conversation_id: str) -> Dict[str, Any]:
        """Returns outline summary: document title, units list, and topic list."""
        sections = self.get_sections(conversation_id)
        if not sections:
            return {"title": "Document", "units": [], "topics": [], "total_topics": 0}

        units: List[str] = []
        for s in sections:
            u = s.get("unit_name") or "Unit 1"
            if u not in units:
                units.append(u)

        return {
            "title": sections[0].get("title", "Document"),
            "units": units,
            "topics": [s.get("title") for s in sections if s.get("topic_number") is not None],
            "total_topics": sum(1 for s in sections if s.get("topic_number") is not None) or len(sections),
            "sections": sections
        }

    def get_document_context_for_query(
        self,
        conversation_id: str,
        query_text: str,
        top_k: int = 5
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Retrieves document context for model prompt:
        - If total document tokens <= 2500 tokens: returns entire text with headers
        - If total document tokens > 2500 tokens: queries top-k chunks with citations
          and prepends the structural outline (Units & Topics list).
        Returns (context_text, coverage_metadata).
        """
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT id, filename, extracted_text, token_count
                FROM attachments
                WHERE conversation_id = ? AND file_type IN ('text', 'pdf', 'docx')
                ORDER BY created_at ASC
            """, (conversation_id,)).fetchall()

        if not rows:
            return "", {"sections": [], "pages": []}

        sections = self.get_sections(conversation_id)
        outline_summary = self.get_document_outline_summary(conversation_id)
        total_tokens = sum(r["token_count"] or 0 for r in rows)

        # Whole document under 2500 tokens: inject full text
        if total_tokens <= MAX_WHOLE_FILE_TOKENS:
            blocks = []
            pages_used = set()
            for r in rows:
                if r["extracted_text"]:
                    blocks.append(f"--- Document: {r['filename']} ---\n{r['extracted_text']}\n--- End of {r['filename']} ---")
            coverage = {
                "sections": [s["title"] for s in sections[:4]] if sections else ["Full Document"],
                "pages": [1]
            }
            return "\n\n".join(blocks), coverage

        # Over 2500 tokens: retrieve top chunks by vector similarity
        query_emb = self.embed_fn([query_text])[0]
        results = self.doc_collection.query(
            query_embeddings=[query_emb],
            n_results=min(top_k, 6),
            where={"conversation_id": conversation_id}
        )

        retrieved_docs = results.get("documents", [[]])[0]
        retrieved_metas = results.get("metadatas", [[]])[0]

        if not retrieved_docs:
            return "", {"sections": [], "pages": []}

        # Build structural outline header so the model knows the document's macro-structure
        outline_lines = []
        if outline_summary.get("units"):
            outline_lines.append(f"[Document Outline: {rows[0]['filename']}]")
            outline_lines.append(f"Units: {', '.join(outline_summary['units'])}")
            if outline_summary.get("topics"):
                sample_topics = outline_summary["topics"][:8]
                outline_lines.append(f"Sample Topics ({len(outline_summary['topics'])} total): {'; '.join(sample_topics)}...")
            outline_lines.append("")

        chunk_blocks = ["\n".join(outline_lines)] if outline_lines else []
        sections_used = []
        pages_used = []

        for doc, meta in zip(retrieved_docs, retrieved_metas):
            page_num = meta.get("page_number", 1)
            filename = meta.get("filename", "document")
            citation = meta.get("citation", f"[File: {filename}, Page: {page_num}]")
            pages_used.append(page_num)

            # Match chunk with its outline section if possible
            matched_sec = None
            for s in sections:
                if s["start_page"] <= page_num <= s["end_page"]:
                    matched_sec = s["title"]
                    break
            if matched_sec and matched_sec not in sections_used:
                sections_used.append(matched_sec)

            sec_label = f"[Section: {matched_sec}] " if matched_sec else ""
            chunk_blocks.append(f"{citation} {sec_label}\n{doc}")

        coverage = {
            "sections": sections_used or ["Relevant Excerpts"],
            "pages": sorted(list(set(pages_used)))
        }

        return "\n\n".join(chunk_blocks), coverage

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
