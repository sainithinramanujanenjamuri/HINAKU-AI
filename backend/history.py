import datetime
import math
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_UNSET = object()

def estimate_tokens(text: str) -> int:
    """Heuristic token estimation: ~4 chars per token + overhead."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4)) + 4

def trim_history(messages: List[Dict[str, str]], max_tokens: int = 2000) -> List[Dict[str, str]]:
    """
    Trims conversation messages to fit within max_tokens.
    - System messages are always preserved.
    - The latest message is always preserved.
    - Older messages are included from newest to oldest until max_tokens is reached.
    - Preserves chronological order in returned list.
    """
    if not messages:
        return []

    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system_msgs = [m for m in messages if m.get("role") != "system"]

    if not non_system_msgs:
        return system_msgs

    sys_tokens = sum(estimate_tokens(m.get("content", "")) for m in system_msgs)
    available_tokens = max(100, max_tokens - sys_tokens)

    latest_msg = non_system_msgs[-1]
    latest_tokens = estimate_tokens(latest_msg.get("content", ""))

    included_non_system = [latest_msg]
    used_tokens = latest_tokens

    for msg in reversed(non_system_msgs[:-1]):
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if used_tokens + msg_tokens > available_tokens:
            break
        included_non_system.append(msg)
        used_tokens += msg_tokens

    included_non_system.reverse()
    return system_msgs + included_non_system

def generate_title(first_message: str, max_len: int = 40) -> str:
    """Generate a clean conversation title from the first message."""
    clean = " ".join(first_message.strip().split())
    if not clean:
        return "New conversation"
    if len(clean) <= max_len:
        return clean
    truncated = clean[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > 15:
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;:?!- ") + "..."

class ChatHistoryManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    is_private INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    backend TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    message_id TEXT,
                    user_prompt TEXT,
                    answer TEXT,
                    model TEXT,
                    backend TEXT,
                    feedback TEXT,
                    edited_answer TEXT,
                    created_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations (updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_interactions_backend ON interactions (backend, created_at);
            """)

            # Soft migrations for existing tables if needed
            conv_cols = [c["name"] for c in conn.execute("PRAGMA table_info(conversations)").fetchall()]
            if "is_private" not in conv_cols:
                conn.execute("ALTER TABLE conversations ADD COLUMN is_private INTEGER DEFAULT 0")

            msg_cols = [c["name"] for c in conn.execute("PRAGMA table_info(messages)").fetchall()]
            if "backend" not in msg_cols:
                conn.execute("ALTER TABLE messages ADD COLUMN backend TEXT")

            int_cols = [c["name"] for c in conn.execute("PRAGMA table_info(interactions)").fetchall()]
            if "message_id" not in int_cols:
                conn.execute("ALTER TABLE interactions ADD COLUMN message_id TEXT")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_msg ON interactions (message_id)")

    def create_conversation(
        self,
        title: str = "New conversation",
        conv_id: Optional[str] = None,
        is_private: bool = False
    ) -> Dict[str, Any]:
        cid = conv_id or str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, is_private, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (cid, title, 1 if is_private else 0, now, now)
            )
            conn.commit()
        return {"id": cid, "title": title, "is_private": is_private, "created_at": now, "updated_at": now}

    def list_conversations(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, title, is_private, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "is_private": bool(r["is_private"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"]
                }
                for r in rows
            ]

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            conv = conn.execute(
                "SELECT id, title, is_private, created_at, updated_at FROM conversations WHERE id = ?",
                (conv_id,)
            ).fetchone()
            if not conv:
                return None

            msgs = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.model, m.backend, m.created_at,
                       i.id as interaction_id, i.feedback, i.edited_answer
                FROM messages m
                LEFT JOIN interactions i ON m.id = i.message_id
                WHERE m.conversation_id = ?
                ORDER BY m.created_at ASC
                """,
                (conv_id,)
            ).fetchall()

            conv_dict = {
                "id": conv["id"],
                "title": conv["title"],
                "is_private": bool(conv["is_private"]),
                "created_at": conv["created_at"],
                "updated_at": conv["updated_at"],
                "messages": [dict(m) for m in msgs]
            }
            return conv_dict

    def rename_conversation(self, conv_id: str, new_title: str) -> Optional[Dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (new_title.strip() or "Untitled", now, conv_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_conversation(conv_id)

    def set_conversation_privacy(self, conv_id: str, is_private: bool) -> Optional[Dict[str, Any]]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE conversations SET is_private = ?, updated_at = ? WHERE id = ?",
                (1 if is_private else 0, now, conv_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_conversation(conv_id)

    def delete_conversation(self, conv_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
            return cursor.rowcount > 0

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        model: Optional[str] = None,
        backend: Optional[str] = None
    ) -> Dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conv = conn.execute("SELECT id, title FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if not conv:
                title = generate_title(content) if role == "user" else "New conversation"
                conn.execute(
                    "INSERT INTO conversations (id, title, is_private, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
                    (conv_id, title, now, now)
                )
            else:
                if role == "user" and conv["title"] in ("New conversation", "Untitled"):
                    new_title = generate_title(content)
                    conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (new_title, conv_id))

            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, model, backend, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, conv_id, role, content, model, backend, now)
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
            conn.commit()

        return {
            "id": msg_id,
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "model": model,
            "backend": backend,
            "created_at": now
        }

    def log_interaction(
        self,
        conv_id: str,
        user_prompt: str,
        answer: str,
        model: str,
        backend: str,
        feedback: Optional[str] = None,
        edited_answer: Optional[str] = None,
        message_id: Optional[str] = None
    ) -> str:
        interaction_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO interactions (
                    id, conversation_id, message_id, user_prompt, answer, model, backend, feedback, edited_answer, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (interaction_id, conv_id, message_id, user_prompt, answer, model, backend, feedback, edited_answer, now)
            )
            conn.commit()
        return interaction_id

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.model, m.backend, m.created_at,
                       i.id as interaction_id, i.feedback, i.edited_answer
                FROM messages m
                LEFT JOIN interactions i ON m.id = i.message_id
                WHERE m.id = ?
                """,
                (message_id,)
            ).fetchone()
            return dict(row) if row else None

    def ensure_interaction_for_message(self, message_id: str) -> Optional[str]:
        msg = self.get_message(message_id)
        if not msg:
            return None
        if msg.get("interaction_id"):
            return msg["interaction_id"]

        with self._get_connection() as conn:
            user_msg = conn.execute(
                "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' AND created_at <= ? ORDER BY created_at DESC LIMIT 1",
                (msg["conversation_id"], msg["created_at"])
            ).fetchone()
            user_prompt = user_msg["content"] if user_msg else ""

        return self.log_interaction(
            conv_id=msg["conversation_id"],
            user_prompt=user_prompt,
            answer=msg["content"],
            model=msg.get("model") or "unknown",
            backend=msg.get("backend") or "local",
            message_id=message_id
        )

    def update_interaction_feedback(
        self,
        interaction_id: Optional[str] = None,
        message_id: Optional[str] = None,
        feedback: Any = _UNSET,
        edited_answer: Any = _UNSET
    ) -> bool:
        if not interaction_id and not message_id:
            return False

        with self._get_connection() as conn:
            clauses = []
            params = []
            if feedback is not _UNSET:
                clauses.append("feedback = ?")
                params.append(feedback)
            if edited_answer is not _UNSET:
                clauses.append("edited_answer = ?")
                params.append(edited_answer)
            if not clauses:
                return False

            if interaction_id:
                params.append(interaction_id)
                sql = f"UPDATE interactions SET {', '.join(clauses)} WHERE id = ?"
            else:
                params.append(message_id)
                sql = f"UPDATE interactions SET {', '.join(clauses)} WHERE message_id = ?"

            cur = conn.execute(sql, tuple(params))
            conn.commit()
            if cur.rowcount > 0:
                return True

        if message_id:
            inter_id = self.ensure_interaction_for_message(message_id)
            if inter_id:
                return self.update_interaction_feedback(interaction_id=inter_id, feedback=feedback, edited_answer=edited_answer)

        return False

    def update_message_content(self, message_id: str, new_content: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, message_id))
            conn.commit()
            return cur.rowcount > 0

    def get_interaction(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
            return dict(row) if row else None

    def get_interaction_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM interactions WHERE message_id = ?", (message_id,)).fetchone()
            return dict(row) if row else None

    def get_daily_api_request_count(self) -> int:
        now_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM interactions WHERE backend = 'api' AND substr(created_at, 1, 10) = ?",
                (now_date,)
            ).fetchone()
            return row["count"] if row else 0

    def export_all_data(self) -> Dict[str, Any]:
        """Export all conversations, messages, and interactions from SQLite."""
        with self._get_connection() as conn:
            convs = [dict(r) for r in conn.execute("SELECT * FROM conversations ORDER BY created_at ASC").fetchall()]
            msgs = [dict(r) for r in conn.execute("SELECT * FROM messages ORDER BY created_at ASC").fetchall()]
            interactions = [dict(r) for r in conn.execute("SELECT * FROM interactions ORDER BY created_at ASC").fetchall()]
            return {
                "conversations": convs,
                "messages": msgs,
                "interactions": interactions
            }

    def wipe_all_data(self) -> None:
        """Permanently delete all conversations, messages, and interactions."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM interactions")
            conn.execute("DELETE FROM conversations")
            conn.commit()

