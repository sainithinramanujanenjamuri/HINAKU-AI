import json
import logging
import math
import sqlite3
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import get_settings

logger = logging.getLogger("hinaku.memory.storage")

def l2_normalize(v: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]

def default_ollama_embedder(host: str, model: str, texts: List[str], keep_alive: str = "5m", num_ctx: int = 512) -> List[List[float]]:
    """
    Generate embeddings using Ollama /api/embed endpoint.
    Uses keep_alive="5m" to avoid cold-loading model on every query.
    """
    body = json.dumps({"model": model, "input": texts, "keep_alive": keep_alive, "options": {"num_ctx": num_ctx}}).encode("utf-8")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/embed",
        data=body,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        raw_embeddings = data.get("embeddings", [])
        return [l2_normalize(vec) for vec in raw_embeddings]

class MemoryStorage:
    def __init__(
        self,
        db_path: Path,
        chroma_path: Path,
        embedding_model: str = "qwen3-embedding:0.6b",
        embedding_dims: int = 1024,
        query_prefix: str = "",
        document_prefix: str = "",
        ollama_host: str = "http://localhost:11434",
        custom_embedder: Optional[Callable[[str, List[str]], List[List[float]]]] = None,
        embedding_keep_alive: Optional[str] = None,
        embedding_num_ctx: Optional[int] = None
    ):
        settings = get_settings()
        self.db_path = Path(db_path)
        self.chroma_path = Path(chroma_path)
        self.embedding_model = embedding_model
        self.embedding_dims = embedding_dims
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self.ollama_host = ollama_host
        self._custom_embedder = custom_embedder
        self.embedding_keep_alive = embedding_keep_alive or settings.memory_embedding_keep_alive
        self.embedding_num_ctx = embedding_num_ctx if embedding_num_ctx is not None else settings.memory_embedding_num_ctx

        # Ensure directory structures exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.chroma_path.mkdir(parents=True, exist_ok=True)

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
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_conversation_id TEXT,
                    deleted INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_memories_deleted ON memories (deleted, updated_at DESC);
            """)

    def _init_chroma(self):
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_path),
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        collection_name = "owner_memories"
        try:
            col = self.chroma_client.get_collection(collection_name)
            stored_model = col.metadata.get("embedding_model") if col.metadata else None
            stored_dims = col.metadata.get("embedding_dims") if col.metadata else None
            if stored_model and stored_model != self.embedding_model:
                logger.warning(
                    f"Stored embedding model '{stored_model}' differs from settings '{self.embedding_model}'. "
                    f"Triggering collection re-index."
                )
                self.reindex_chroma()
                return
            elif stored_dims and int(stored_dims) != int(self.embedding_dims):
                logger.warning(
                    f"Stored embedding dimension {stored_dims} differs from settings {self.embedding_dims}. "
                    f"Triggering collection re-index."
                )
                self.reindex_chroma()
                return
            self.collection = col
        except Exception:
            # Collection does not exist yet; create it
            self.collection = self.chroma_client.create_collection(
                name=collection_name,
                metadata={
                    "hnsw:space": "cosine",
                    "embedding_model": self.embedding_model,
                    "embedding_dims": self.embedding_dims
                }
            )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        prefixed = [f"{self.document_prefix}{t}" for t in texts]
        if self._custom_embedder:
            return [l2_normalize(v) for v in self._custom_embedder(self.embedding_model, prefixed)]
        return default_ollama_embedder(self.ollama_host, self.embedding_model, prefixed, keep_alive=self.embedding_keep_alive, num_ctx=self.embedding_num_ctx)

    def embed_query(self, query: str) -> List[float]:
        prefixed = f"{self.query_prefix}{query}"
        if self._custom_embedder:
            return l2_normalize(self._custom_embedder(self.embedding_model, [prefixed])[0])
        return default_ollama_embedder(self.ollama_host, self.embedding_model, [prefixed], keep_alive=self.embedding_keep_alive, num_ctx=self.embedding_num_ctx)[0]

    def add_memory(self, text: str, source_conversation_id: Optional[str] = None) -> Dict[str, Any]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Memory text cannot be empty")

        mem_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Insert SQLite record
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO memories (id, text, created_at, updated_at, source_conversation_id, deleted)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (mem_id, clean_text, now, now, source_conversation_id)
            )
            conn.commit()

        # Insert ChromaDB vector
        try:
            vec = self.embed_documents([clean_text])[0]
            self.collection.add(
                ids=[mem_id],
                documents=[clean_text],
                embeddings=[vec],
                metadatas=[{
                    "created_at": now,
                    "updated_at": now,
                    "source_conversation_id": source_conversation_id or ""
                }]
            )
        except Exception as e:
            logger.error(f"Failed to index memory into ChromaDB: {e}")

        return {
            "id": mem_id,
            "text": clean_text,
            "created_at": now,
            "updated_at": now,
            "source_conversation_id": source_conversation_id,
            "deleted": 0
        }

    def update_memory(self, mem_id: str, new_text: str) -> Optional[Dict[str, Any]]:
        clean_text = new_text.strip()
        if not clean_text:
            raise ValueError("Memory text cannot be empty")

        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE memories SET text = ?, updated_at = ? WHERE id = ? AND deleted = 0",
                (clean_text, now, mem_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None

        # Re-embed updated text into ChromaDB (ensures typo corrections immediately update Chroma vectors)
        try:
            vec = self.embed_documents([clean_text])[0]
            self.collection.upsert(
                ids=[mem_id],
                documents=[clean_text],
                embeddings=[vec]
            )
        except Exception as e:
            logger.error(f"Failed to update ChromaDB vector for {mem_id}: {e}")

        return self.get_memory(mem_id)

    def delete_memory(self, mem_id: str) -> bool:
        """
        Permanently remove memory: hard-delete row from SQLite and remove vector from Chroma.
        No deleted flag left behind. Runs VACUUM on database.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return False
            try:
                old_iso = conn.isolation_level
                conn.isolation_level = None
                conn.execute("VACUUM")
                conn.isolation_level = old_iso
            except Exception as e:
                logger.error(f"Failed to vacuum: {e}")

        try:
            self.collection.delete(ids=[mem_id])
        except Exception as e:
            logger.error(f"Failed to delete memory vector from ChromaDB: {e}")

        return True

    def get_memory(self, mem_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT id, text, created_at, updated_at, source_conversation_id, deleted FROM memories WHERE id = ?",
                (mem_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

    def get_memories(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            sql = "SELECT id, text, created_at, updated_at, source_conversation_id, deleted FROM memories"
            if not include_deleted:
                sql += " WHERE deleted = 0"
            sql += " ORDER BY updated_at DESC"
            cur = conn.execute(sql)
            return [dict(r) for r in cur.fetchall()]

    def query_memories(
        self,
        query_text: str,
        top_k: int = 3,
        min_similarity: float = 0.46
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Retrieve relevant memories with cosine similarity >= min_similarity.
        Returns list of (memory_dict, similarity_score).
        """
        clean_q = query_text.strip()
        if not clean_q or self.collection.count() == 0:
            return []

        try:
            q_vec = self.embed_query(clean_q)
            results = self.collection.query(
                query_embeddings=[q_vec],
                n_results=min(top_k, self.collection.count()),
                include=["documents", "metadatas", "distances"]
            )
        except Exception as e:
            logger.error(f"Chroma query failed: {e}")
            return []

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        matched = []
        ids = results["ids"][0]
        distances = results["distances"][0] if "distances" in results and results["distances"] else [0.0] * len(ids)

        for mem_id, dist in zip(ids, distances):
            # Chroma cosine distance = 1 - cosine_similarity
            similarity = 1.0 - dist
            if similarity >= min_similarity:
                mem = self.get_memory(mem_id)
                if mem and mem.get("deleted") == 0:
                    matched.append((mem, similarity))

        return matched

    def find_similar(
        self,
        text: str,
        threshold: float = 0.80
    ) -> Optional[Tuple[Dict[str, Any], float]]:
        """
        Find existing memory highly similar to `text` for merging.
        """
        if self.collection.count() == 0:
            return None

        clean_text = text.strip()
        vec = self.embed_documents([clean_text])[0]
        try:
            results = self.collection.query(
                query_embeddings=[vec],
                n_results=1,
                include=["documents", "distances"]
            )
        except Exception as e:
            logger.error(f"find_similar query failed: {e}")
            return None

        if not results or not results["ids"] or not results["ids"][0]:
            return None

        best_id = results["ids"][0][0]
        best_dist = results["distances"][0][0]
        best_similarity = 1.0 - best_dist

        if best_similarity >= threshold:
            mem = self.get_memory(best_id)
            if mem and mem.get("deleted") == 0:
                return (mem, best_similarity)

        return None

    def export_all(self) -> List[Dict[str, Any]]:
        return self.get_memories(include_deleted=False)

    def reindex_memories(self) -> int:
        """Alias for reindex_chroma returning count of active memories."""
        self.reindex_chroma()
        return len(self.get_memories(include_deleted=False))

    def reindex_chroma(self):
        """
        Re-indexes all active memories into ChromaDB using the current embedding model.
        Used on model change or vector store migration.
        """
        logger.info(f"Re-indexing memories into Chroma with model '{self.embedding_model}' (dims: {self.embedding_dims})")
        collection_name = "owner_memories"
        try:
            self.chroma_client.delete_collection(collection_name)
        except Exception:
            pass

        self.collection = self.chroma_client.create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": self.embedding_model,
                "embedding_dims": self.embedding_dims
            }
        )

        active_memories = self.get_memories(include_deleted=False)
        if not active_memories:
            return

        texts = [m["text"] for m in active_memories]
        ids = [m["id"] for m in active_memories]
        metadatas = [{
            "created_at": m["created_at"],
            "updated_at": m["updated_at"],
            "source_conversation_id": m.get("source_conversation_id") or ""
        } for m in active_memories]

        try:
            vectors = self.embed_documents(texts)
            self.collection.add(
                ids=ids,
                documents=texts,
                embeddings=vectors,
                metadatas=metadatas
            )
            logger.info(f"Re-indexing complete: {len(active_memories)} memories indexed.")
        except Exception as e:
            logger.error(f"Re-indexing failed: {e}")

    def clear_all(self) -> int:
        """
        Hard-deletes all memories from SQLite, runs VACUUM, and drops/recreates Chroma collection.
        Returns count of memories deleted.
        """
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM memories")
            conn.commit()
            count = cur.rowcount
            try:
                old_iso = conn.isolation_level
                conn.isolation_level = None
                conn.execute("VACUUM")
                conn.isolation_level = old_iso
            except Exception as e:
                logger.error(f"Failed to vacuum: {e}")

        try:
            self.chroma_client.delete_collection("owner_memories")
            self.collection = self.chroma_client.create_collection(
                name="owner_memories",
                metadata={
                    "hnsw:space": "cosine",
                    "embedding_model": self.embedding_model,
                    "embedding_dims": self.embedding_dims
                }
            )
        except Exception as e:
            logger.error(f"Error resetting Chroma on clear_all: {e}")

        return count
