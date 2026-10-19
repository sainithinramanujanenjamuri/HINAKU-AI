import datetime
import math
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    # Calculate tokens used by system messages
    sys_tokens = sum(estimate_tokens(m.get("content", "")) for m in system_msgs)
    available_tokens = max(100, max_tokens - sys_tokens)

    # Always keep the most recent message
    latest_msg = non_system_msgs[-1]
    latest_tokens = estimate_tokens(latest_msg.get("content", ""))

    included_non_system = [latest_msg]
    used_tokens = latest_tokens

    # Walk backwards through remaining messages
    for msg in reversed(non_system_msgs[:-1]):
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if used_tokens + msg_tokens > available_tokens:
            break
        included_non_system.append(msg)
        used_tokens += msg_tokens

    # Restore chronological order
    included_non_system.reverse()

    return system_msgs + included_non_system

def generate_title(first_message: str, max_len: int = 40) -> str:
    """Generate a clean conversation title from the first message."""
    clean = " ".join(first_message.strip().split())
    if not clean:
        return "New conversation"
    if len(clean) <= max_len:
        return clean
    # Truncate at word boundary if possible
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations (updated_at DESC);
            """)

    def create_conversation(self, title: str = "New conversation", conv_id: Optional[str] = None) -> Dict[str, Any]:
        cid = conv_id or str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, title, now, now)
            )
            conn.commit()
        return {"id": cid, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            conv = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conv_id,)
            ).fetchone()
            if not conv:
                return None

            msgs = conn.execute(
                "SELECT id, conversation_id, role, content, model, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,)
            ).fetchall()

            conv_dict = dict(conv)
            conv_dict["messages"] = [dict(m) for m in msgs]
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

    def delete_conversation(self, conv_id: str) -> bool:
        with self._get_connection() as conn:
            # Explicitly delete messages as well as cascade
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
            return cursor.rowcount > 0

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        msg_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            # Check if conversation exists, if not create it
            conv = conn.execute("SELECT id, title FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if not conv:
                title = generate_title(content) if role == "user" else "New conversation"
                conn.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conv_id, title, now, now)
                )
            else:
                # If first user message and title is default, auto-title
                if role == "user" and conv["title"] in ("New conversation", "Untitled"):
                    new_title = generate_title(content)
                    conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (new_title, conv_id))

            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, model, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (msg_id, conv_id, role, content, model, now)
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
            conn.commit()

        return {
            "id": msg_id,
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "model": model,
            "created_at": now
        }

