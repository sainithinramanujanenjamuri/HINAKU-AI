"""
backend/intelligence/knowledge_graph.py

Relational graph relationship manager for HINAKU knowledge entities.
Provides directed semantic edges (depends_on, implements, supersedes, contradicts, relates_to)
without external graph database overhead.
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set
import uuid

from .errors import KnowledgeGraphError
from .graph_types import EdgeRelationship, KnowledgeEdge
from .types import KnowledgeDomain
from backend.database.backup import coordinated_write


class KnowledgeGraph:
    """Manages semantic relationships across all HINAKU knowledge domains."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_domain TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_domain TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_edges_source ON knowledge_edges (source_domain, source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON knowledge_edges (target_domain, target_id);
                CREATE INDEX IF NOT EXISTS idx_edges_rel ON knowledge_edges (relationship);
                CREATE INDEX IF NOT EXISTS idx_edges_pair ON knowledge_edges (source_id, target_id, relationship);
            """)

    @coordinated_write("knowledge_graph")
    def add_edge(self, edge: KnowledgeEdge) -> KnowledgeEdge:
        """Adds a directed semantic edge between knowledge entities."""
        if not edge.source_id or not edge.target_id:
            raise KnowledgeGraphError("Source ID and Target ID must be non-empty strings.")

        edge.edge_id = edge.edge_id or str(uuid.uuid4())
        edge.created_at = edge.created_at or time.time()

        with self._get_connection() as conn:
            # Check for existing duplicate edge
            existing = conn.execute(
                """
                SELECT edge_id FROM knowledge_edges
                WHERE source_id = ? AND target_id = ? AND relationship = ?
                """,
                (edge.source_id, edge.target_id, edge.relationship.value)
            ).fetchone()
            if existing:
                return edge  # Idempotent addition

            conn.execute(
                """
                INSERT INTO knowledge_edges (
                    edge_id, source_id, source_domain, target_id, target_domain,
                    relationship, weight, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.edge_id,
                    edge.source_id,
                    edge.source_domain.value,
                    edge.target_id,
                    edge.target_domain.value,
                    edge.relationship.value,
                    edge.weight,
                    json.dumps(edge.metadata),
                    edge.created_at,
                )
            )
        return edge

    def get_edges(
        self,
        entity_id: str,
        domain: Optional[KnowledgeDomain] = None,
        direction: str = "both",
        relationship: Optional[EdgeRelationship] = None,
    ) -> List[KnowledgeEdge]:
        """
        Retrieves edges connected to an entity.
        direction: "out" (entity is source), "in" (entity is target), or "both".
        """
        clauses: List[str] = []
        params: List[Any] = []

        if direction == "out":
            c = "source_id = ?"
            p = [entity_id]
            if domain is not None:
                c += " AND source_domain = ?"
                p.append(domain.value)
            clauses.append(f"({c})")
            params.extend(p)
        elif direction == "in":
            c = "target_id = ?"
            p = [entity_id]
            if domain is not None:
                c += " AND target_domain = ?"
                p.append(domain.value)
            clauses.append(f"({c})")
            params.extend(p)
        else:  # both
            c1 = "source_id = ?"
            p1 = [entity_id]
            if domain is not None:
                c1 += " AND source_domain = ?"
                p1.append(domain.value)

            c2 = "target_id = ?"
            p2 = [entity_id]
            if domain is not None:
                c2 += " AND target_domain = ?"
                p2.append(domain.value)

            clauses.append(f"({c1} OR {c2})")
            params.extend(p1 + p2)

        if relationship is not None:
            clauses.append("relationship = ?")
            params.append(relationship.value)

        where_sql = " AND ".join(clauses) if clauses else "1=1"
        query = f"SELECT * FROM knowledge_edges WHERE {where_sql} ORDER BY created_at DESC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_edge(r) for r in rows]

    @coordinated_write("knowledge_graph")
    def delete_edge(self, edge_id: str) -> bool:
        """Deletes a graph edge by ID."""
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM knowledge_edges WHERE edge_id = ?", (edge_id,))
            return cur.rowcount > 0

    def record_superseded(
        self,
        old_id: str,
        old_domain: KnowledgeDomain,
        new_id: str,
        new_domain: KnowledgeDomain,
        reason: str = "",
    ) -> KnowledgeEdge:
        """
        Records that new_id supersedes old_id (new_id -> supersedes -> old_id).
        Preserves complete historical audit trail without destroying old records.
        """
        edge = KnowledgeEdge(
            edge_id=str(uuid.uuid4()),
            source_id=new_id,
            source_domain=new_domain,
            target_id=old_id,
            target_domain=old_domain,
            relationship=EdgeRelationship.SUPERSEDES,
            weight=1.0,
            metadata={"reason": reason},
            created_at=time.time(),
        )
        return self.add_edge(edge)

    def find_contradictions(
        self,
        entity_id: str,
        domain: Optional[KnowledgeDomain] = None,
    ) -> List[KnowledgeEdge]:
        """Finds any recorded contradiction edges for an entity."""
        return self.get_edges(
            entity_id=entity_id,
            domain=domain,
            direction="both",
            relationship=EdgeRelationship.CONTRADICTS,
        )

    def traverse_dependencies(
        self,
        root_entity_id: str,
        max_depth: int = 5,
    ) -> List[KnowledgeEdge]:
        """
        Traverses outbound dependency edges (root depends_on target, target depends_on ...).
        Uses a visited set to safely handle cycles in dependency graphs.
        """
        visited_entities: Set[str] = {root_entity_id}
        collected_edges: List[KnowledgeEdge] = []
        current_layer: Set[str] = {root_entity_id}

        for _ in range(max_depth):
            if not current_layer:
                break
            next_layer: Set[str] = set()
            for curr_id in current_layer:
                out_edges = self.get_edges(
                    entity_id=curr_id,
                    direction="out",
                    relationship=EdgeRelationship.DEPENDS_ON,
                )
                for edge in out_edges:
                    collected_edges.append(edge)
                    if edge.target_id not in visited_entities:
                        visited_entities.add(edge.target_id)
                        next_layer.add(edge.target_id)
            current_layer = next_layer

        return collected_edges

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> KnowledgeEdge:
        return KnowledgeEdge(
            edge_id=row["edge_id"],
            source_id=row["source_id"],
            source_domain=KnowledgeDomain(row["source_domain"]),
            target_id=row["target_id"],
            target_domain=KnowledgeDomain(row["target_domain"]),
            relationship=EdgeRelationship(row["relationship"]),
            weight=row["weight"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
        )
