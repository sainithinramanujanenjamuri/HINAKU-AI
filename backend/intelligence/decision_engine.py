"""
backend/intelligence/decision_engine.py

Decision Engine for HINAKU.
Determines what should happen and why through structured problem framing, alternative analysis,
adaptive uncertainty evaluation, and transparent recommendations with owner authority preservation.
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from .context import IntelligenceContext
from .decision_types import (
    AlternativeEvaluation,
    CriticalActionCategory,
    DecisionRecommendation,
    DecisionRecord,
    DecisionStatus,
    UncertaintyAssessment,
    UncertaintyLevel,
)
from .errors import IntelligenceError
from .graph_types import EdgeRelationship, KnowledgeEdge
from .knowledge_graph import KnowledgeGraph
from .types import (
    ImplementationStatus,
    KnowledgeDomain,
    KnowledgeProvenance,
    SourceAuthority,
)


class DecisionEngine:
    """Evaluates situations, compares alternatives, manages uncertainty, and maintains decision history."""

    def __init__(self, db_path: Path, knowledge_graph: Optional[KnowledgeGraph] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph = knowledge_graph
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    title TEXT NOT NULL,
                    problem_statement TEXT NOT NULL,
                    status TEXT NOT NULL,
                    uncertainty TEXT NOT NULL,
                    alternatives TEXT NOT NULL,
                    recommendation TEXT,
                    owner_decision TEXT,
                    owner_notes TEXT,
                    source_authority TEXT NOT NULL,
                    claim_confidence REAL NOT NULL,
                    verification_status TEXT NOT NULL,
                    implementation_evidence TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    deleted INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS decision_revisions (
                    revision_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    owner_decision TEXT,
                    owner_notes TEXT,
                    reason TEXT NOT NULL DEFAULT '',
                    changed_by TEXT NOT NULL DEFAULT 'owner',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (decision_id) REFERENCES decisions(decision_id)
                );

                CREATE INDEX IF NOT EXISTS idx_decisions_proj ON decisions (project_id, deleted);
                CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions (status, deleted);
            """)

    # --------------------------------------------------------------------------
    # Decision Evaluation & Framing
    # --------------------------------------------------------------------------

    def evaluate_decision(
        self,
        title: str,
        problem_statement: str,
        alternatives: List[AlternativeEvaluation],
        context: IntelligenceContext,
        project_id: Optional[str] = None,
        known_facts: Optional[List[str]] = None,
        assumptions: Optional[List[str]] = None,
        unknowns: Optional[List[str]] = None,
        conflicting_evidence: Optional[List[str]] = None,
        critical_category: Optional[CriticalActionCategory] = None,
        authority: SourceAuthority = SourceAuthority.ASSISTANT_SUGGESTION,
    ) -> DecisionRecord:
        """
        Conducts structured evaluation of alternatives and uncertainty, producing an inspectable recommendation.
        """
        # Validate domain access
        context.validate_domain_access(KnowledgeDomain.DECISION)

        # 1. Assess uncertainty
        k_facts = known_facts or []
        assump = assumptions or []
        unk = unknowns or []
        conflicts = conflicting_evidence or []

        # Calculate uncertainty level based on evidence gaps
        if critical_category is not None:
            uncertainty_level = UncertaintyLevel.CRITICAL
            clarification_needed = True
        elif conflicts or len(unk) >= 2:
            uncertainty_level = UncertaintyLevel.HIGH
            clarification_needed = True
        elif assump or len(unk) == 1:
            uncertainty_level = UncertaintyLevel.MODERATE
            clarification_needed = False
        else:
            uncertainty_level = UncertaintyLevel.LOW
            clarification_needed = False

        uncertainty = UncertaintyAssessment(
            level=uncertainty_level,
            known_facts=k_facts,
            assumptions=assump,
            unknowns=unk,
            conflicting_evidence=conflicts,
            clarification_needed=clarification_needed,
            suggested_investigation=(
                f"Clarify: {', '.join(unk)}" if unk else None
            ),
        )

        # 2. Score & Rank Alternatives
        if not alternatives:
            raise IntelligenceError("Decision evaluation requires at least one alternative.")

        best_alt = max(alternatives, key=lambda a: a.score)

        # 3. Formulate transparent recommendation
        requires_approval = (critical_category is not None) or (uncertainty_level == UncertaintyLevel.CRITICAL)

        recommendation = DecisionRecommendation(
            recommended_alternative_id=best_alt.alternative_id,
            summary=f"Recommend '{best_alt.title}': {best_alt.description}",
            justification=best_alt.alignment_with_goals or best_alt.score_explanation or "Optimal trade-off profile",
            contingencies=[f"If unknown variables change: {u}" for u in unk],
            key_risks=[best_alt.risk_assessment] if best_alt.risk_assessment else [],
            requires_owner_approval=requires_approval,
            critical_action_category=critical_category,
        )

        # Provenance: Decoupled properties
        provenance = KnowledgeProvenance(
            source_authority=authority,
            claim_confidence=1.0 if uncertainty_level == UncertaintyLevel.LOW else 0.8,
            verification_status=ImplementationStatus.PROPOSED,
            implementation_evidence=None,
        )

        decision_id = str(uuid.uuid4())
        now = time.time()

        record = DecisionRecord(
            decision_id=decision_id,
            project_id=project_id or context.active_project_id,
            title=title,
            problem_statement=problem_statement,
            status=DecisionStatus.RECOMMENDED,
            uncertainty=uncertainty,
            alternatives=alternatives,
            recommendation=recommendation,
            provenance=provenance,
            created_at=now,
            updated_at=now,
        )

        # Persist decision
        self._insert_decision(record)

        # If knowledge graph is available, connect decision to project
        if self.graph and record.project_id:
            self.graph.add_edge(KnowledgeEdge(
                edge_id=str(uuid.uuid4()),
                source_id=decision_id,
                source_domain=KnowledgeDomain.DECISION,
                target_id=record.project_id,
                target_domain=KnowledgeDomain.PROJECT,
                relationship=EdgeRelationship.RELATES_TO,
            ))

        return record

    # --------------------------------------------------------------------------
    # Owner Authorization & Decision Recording
    # --------------------------------------------------------------------------

    def record_owner_choice(
        self,
        decision_id: str,
        choice: str,
        owner_notes: str = "",
        approved: bool = True,
    ) -> DecisionRecord:
        """
        Records the owner's binding decision.
        ARCHITECTURAL INVARIANT: An approved decision has status APPROVED, strictly NOT IMPLEMENTED.
        """
        existing = self.get_decision(decision_id)
        if not existing:
            raise IntelligenceError(f"Decision '{decision_id}' not found.")

        old_status = existing.status
        new_status = DecisionStatus.APPROVED if approved else DecisionStatus.REJECTED
        now = time.time()

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE decisions SET
                    status = ?,
                    owner_decision = ?,
                    owner_notes = ?,
                    verification_status = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE decision_id = ?
                """,
                (
                    new_status.value,
                    choice,
                    owner_notes,
                    ImplementationStatus.ACCEPTED.value if approved else ImplementationStatus.REJECTED.value,
                    now,
                    decision_id,
                )
            )

            # Record audit revision
            conn.execute(
                """
                INSERT INTO decision_revisions (
                    revision_id, decision_id, previous_status, new_status,
                    owner_decision, owner_notes, reason, changed_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    decision_id,
                    old_status.value,
                    new_status.value,
                    choice,
                    owner_notes,
                    "Owner explicit decision recorded",
                    "owner",
                    now,
                )
            )

        return self.get_decision(decision_id)  # type: ignore

    def challenge_proposal_if_conflicting(
        self,
        proposal: str,
        project_id: Optional[str] = None,
        known_constraints: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Respectfully identifies when a proposal conflicts with established decisions or known constraints.
        Does not manipulate or repeatedly argue after confirmation.
        """
        constraints = known_constraints or []
        prop_clean = proposal.lower()

        # Check against constraints
        for c in constraints:
            c_clean = c.lower()
            if ("local-only" in c_clean or "no api" in c_clean) and ("external api" in prop_clean or "cloud" in prop_clean):
                return {
                    "conflict_detected": True,
                    "conflicting_constraint": c,
                    "explanation": (
                        "The proposal to route externally conflicts with the established local-only boundary constraint. "
                        "HINAKU can process this locally using Gemma/Qwen instead."
                    ),
                    "alternatives": ["Proceed strictly with local inference", "Explicitly modify project confidentiality"],
                }

        # Check against approved decisions for this project
        if project_id:
            decisions = self.list_decisions(project_id=project_id, status=DecisionStatus.APPROVED)
            for d in decisions:
                # If proposed statement conflicts with existing approved decision
                from .contradiction_manager import ContradictionManager
                if ContradictionManager.detect_direct_conflict(proposal, d.problem_statement + " " + d.title):
                    return {
                        "conflict_detected": True,
                        "conflicting_decision_id": d.decision_id,
                        "conflicting_decision_title": d.title,
                        "explanation": (
                            f"This proposal appears to conflict with previously approved decision: '{d.title}'. "
                            "Would you like to supersede that decision with this new directive?"
                        ),
                        "alternatives": ["Supersede previous decision with full audit history", "Keep existing decision"],
                    }

        return None

    def supersede_decision(
        self,
        old_decision_id: str,
        new_decision_id: str,
        reason: str = "",
    ) -> None:
        """Marks an older decision as superseded and records the graph link."""
        old = self.get_decision(old_decision_id)
        if not old:
            raise IntelligenceError(f"Old decision '{old_decision_id}' not found.")

        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE decisions SET
                    status = ?,
                    verification_status = ?,
                    updated_at = ?,
                    revision = revision + 1
                WHERE decision_id = ?
                """,
                (
                    DecisionStatus.SUPERSEDED.value,
                    ImplementationStatus.SUPERSEDED.value,
                    now,
                    old_decision_id,
                )
            )

        if self.graph:
            self.graph.record_superseded(
                old_id=old_decision_id,
                old_domain=KnowledgeDomain.DECISION,
                new_id=new_decision_id,
                new_domain=KnowledgeDomain.DECISION,
                reason=reason,
            )

    # --------------------------------------------------------------------------
    # Queries & Serialization
    # --------------------------------------------------------------------------

    def get_decision(self, decision_id: str) -> Optional[DecisionRecord]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE decision_id = ? AND deleted = 0",
                (decision_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_decision(row)

    def list_decisions(
        self,
        project_id: Optional[str] = None,
        status: Optional[DecisionStatus] = None,
    ) -> List[DecisionRecord]:
        query = "SELECT * FROM decisions WHERE deleted = 0"
        params: List[Any] = []
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY updated_at DESC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_decision(r) for r in rows]

    def _insert_decision(self, record: DecisionRecord) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO decisions (
                    decision_id, project_id, title, problem_statement, status,
                    uncertainty, alternatives, recommendation, owner_decision, owner_notes,
                    source_authority, claim_confidence, verification_status, implementation_evidence,
                    created_at, updated_at, revision, deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.decision_id,
                    record.project_id,
                    record.title,
                    record.problem_statement,
                    record.status.value,
                    json.dumps(record.uncertainty.to_dict()),
                    json.dumps([a.to_dict() for a in record.alternatives]),
                    json.dumps(record.recommendation.to_dict()) if record.recommendation else None,
                    record.owner_decision,
                    record.owner_notes,
                    record.provenance.source_authority.value,
                    record.provenance.claim_confidence,
                    record.provenance.verification_status.value,
                    json.dumps(record.provenance.implementation_evidence) if record.provenance.implementation_evidence else None,
                    record.created_at,
                    record.updated_at,
                    record.revision,
                    record.deleted,
                )
            )

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> DecisionRecord:
        uncertainty = UncertaintyAssessment.from_dict(json.loads(row["uncertainty"]))
        alts = [AlternativeEvaluation.from_dict(a) for a in json.loads(row["alternatives"])]
        rec = DecisionRecommendation.from_dict(json.loads(row["recommendation"])) if row["recommendation"] else None
        evidence = json.loads(row["implementation_evidence"]) if row["implementation_evidence"] else None
        provenance = KnowledgeProvenance(
            source_authority=SourceAuthority(row["source_authority"]),
            claim_confidence=row["claim_confidence"],
            verification_status=ImplementationStatus(row["verification_status"]),
            implementation_evidence=evidence,
            created_at=row["created_at"],
        )
        return DecisionRecord(
            decision_id=row["decision_id"],
            project_id=row["project_id"],
            title=row["title"],
            problem_statement=row["problem_statement"],
            status=DecisionStatus(row["status"]),
            uncertainty=uncertainty,
            alternatives=alts,
            recommendation=rec,
            owner_decision=row["owner_decision"],
            owner_notes=row["owner_notes"],
            provenance=provenance,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            revision=row["revision"],
            deleted=row["deleted"],
        )
