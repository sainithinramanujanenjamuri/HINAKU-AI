"""
tests/test_memory_knowledge_architecture.py

Unit and integration tests for HINAKU Phase 1 Milestone 3:
Memory and Knowledge Architecture, Knowledge Graph, Contradiction Handling, and Domain-Isolated Routing.
"""

from pathlib import Path
import pytest
import time

from backend.intelligence import (
    ContextBundle,
    ContextSecurityViolation,
    ContradictionManager,
    ContradictionResolutionError,
    CrossDomainLeakageError,
    DomainIsolationViolation,
    DomainRouter,
    EdgeRelationship,
    ImplementationStatus,
    IntelligenceContext,
    IntelligenceError,
    KnowledgeCategory,
    KnowledgeDomain,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeGraphError,
    KnowledgeProvenance,
    ProjectConfidentiality,
    ProjectConfidentialityViolation,
    ProjectEngine,
    ProjectRecord,
    SourceAuthority,
)


@pytest.fixture
def knowledge_graph(tmp_path):
    """Provides a fresh KnowledgeGraph instance backed by a temporary SQLite database."""
    db_file = tmp_path / "test_knowledge_graph.db"
    return KnowledgeGraph(db_file)


@pytest.fixture
def project_engine(tmp_path):
    """Provides a fresh ProjectEngine instance."""
    db_file = tmp_path / "test_projects_for_router.db"
    return ProjectEngine(db_file)


# Mock memory storage for personal memory domain
class MockPersonalMemoryStorage:
    def __init__(self, memories=None):
        self._memories = memories or ["Owner prefers dark mode theme", "Owner works on HP V15 laptop"]

    def list_memories(self):
        return [{"text": m} for m in self._memories]


# ==============================================================================
# 1. Knowledge Graph Edge Management & Traversal Tests
# ==============================================================================

def test_knowledge_graph_edge_addition_and_query(knowledge_graph):
    """Test adding edges and querying them by entity and direction."""
    edge1 = KnowledgeEdge(
        edge_id="edge-1",
        source_id="module_auth",
        source_domain=KnowledgeDomain.PROJECT,
        target_id="req_security",
        target_domain=KnowledgeDomain.PROJECT,
        relationship=EdgeRelationship.IMPLEMENTS,
        weight=1.0,
    )
    knowledge_graph.add_edge(edge1)

    # Query out-direction
    out_edges = knowledge_graph.get_edges("module_auth", direction="out")
    assert len(out_edges) == 1
    assert out_edges[0].target_id == "req_security"
    assert out_edges[0].relationship == EdgeRelationship.IMPLEMENTS

    # Query in-direction
    in_edges = knowledge_graph.get_edges("req_security", direction="in")
    assert len(in_edges) == 1
    assert in_edges[0].source_id == "module_auth"

    # Query both directions
    both_edges = knowledge_graph.get_edges("module_auth", direction="both")
    assert len(both_edges) == 1


def test_knowledge_graph_edge_idempotency_and_deletion(knowledge_graph):
    """Test that duplicate edges are handled idempotently and deletion works."""
    edge = KnowledgeEdge(
        edge_id="edge-dup",
        source_id="A",
        source_domain=KnowledgeDomain.GENERAL,
        target_id="B",
        target_domain=KnowledgeDomain.GENERAL,
        relationship=EdgeRelationship.RELATES_TO,
    )
    knowledge_graph.add_edge(edge)
    # Add again
    knowledge_graph.add_edge(edge)

    edges = knowledge_graph.get_edges("A", direction="out")
    assert len(edges) == 1

    # Delete
    deleted = knowledge_graph.delete_edge(edges[0].edge_id)
    assert deleted is True
    assert len(knowledge_graph.get_edges("A", direction="out")) == 0


def test_knowledge_graph_dependency_traversal_with_cycle_safety(knowledge_graph):
    """Test traversing directed dependencies (A -> B -> C -> A) safely without infinite loop."""
    # Create cyclic dependency: A -> B -> C -> A
    knowledge_graph.add_edge(KnowledgeEdge(
        edge_id="e1", source_id="task_A", source_domain=KnowledgeDomain.PROJECT,
        target_id="task_B", target_domain=KnowledgeDomain.PROJECT, relationship=EdgeRelationship.DEPENDS_ON
    ))
    knowledge_graph.add_edge(KnowledgeEdge(
        edge_id="e2", source_id="task_B", source_domain=KnowledgeDomain.PROJECT,
        target_id="task_C", target_domain=KnowledgeDomain.PROJECT, relationship=EdgeRelationship.DEPENDS_ON
    ))
    knowledge_graph.add_edge(KnowledgeEdge(
        edge_id="e3", source_id="task_C", source_domain=KnowledgeDomain.PROJECT,
        target_id="task_A", target_domain=KnowledgeDomain.PROJECT, relationship=EdgeRelationship.DEPENDS_ON
    ))

    # Traverse dependencies from task_A (should visit B and C and terminate safely)
    deps = knowledge_graph.traverse_dependencies("task_A", max_depth=5)
    visited_targets = {e.target_id for e in deps}
    assert "task_B" in visited_targets
    assert "task_C" in visited_targets
    # Ensure traversal terminated cleanly
    assert len(deps) <= 4


# ==============================================================================
# 2. Contradiction Detection & Superseding Tests
# ==============================================================================

def test_contradiction_detection_heuristics():
    """Test heuristic detection of direct conflicting claims."""
    # Direct polar pairs
    assert ContradictionManager.detect_direct_conflict(
        "Always enable debug logs",
        "Always disable debug logs"
    ) is True

    assert ContradictionManager.detect_direct_conflict(
        "Use SQLite for local storage",
        "Use Postgres for local storage"
    ) is True

    # Polarity negation
    assert ContradictionManager.detect_direct_conflict(
        "The system is ready for production",
        "The system is not ready for production"
    ) is True

    # Non-contradictory claims
    assert ContradictionManager.detect_direct_conflict(
        "Use Python 3.11",
        "Deploy on Windows"
    ) is False


def test_contradiction_recording_and_superseding_resolution(knowledge_graph):
    """Test recording contradiction edge and resolving it by superseding with full audit history."""
    old_fact_id = "fact-postgres"
    new_fact_id = "fact-sqlite"

    # Step 1: Record contradiction
    contra_edge = ContradictionManager.record_contradiction(
        graph=knowledge_graph,
        item_id_a=new_fact_id,
        domain_a=KnowledgeDomain.PROJECT,
        item_id_b=old_fact_id,
        domain_b=KnowledgeDomain.PROJECT,
        details="Postgres conflicts with single-user local SQLite requirement",
    )
    assert contra_edge.relationship == EdgeRelationship.CONTRADICTS

    # Check contradiction query
    contras = knowledge_graph.find_contradictions(new_fact_id)
    assert len(contras) == 1
    assert contras[0].target_id == old_fact_id

    # Step 2: Resolve by superseding (new supersedes old)
    supersede_edge = ContradictionManager.resolve_by_superseding(
        graph=knowledge_graph,
        old_id=old_fact_id,
        old_domain=KnowledgeDomain.PROJECT,
        new_id=new_fact_id,
        new_domain=KnowledgeDomain.PROJECT,
        resolution_reason="Owner confirmed SQLite as final local database choice",
    )
    assert supersede_edge.relationship == EdgeRelationship.SUPERSEDES
    assert supersede_edge.source_id == new_fact_id
    assert supersede_edge.target_id == old_fact_id

    # Self-superseding must be rejected
    with pytest.raises(ContradictionResolutionError, match="Cannot supersede an entity with itself"):
        ContradictionManager.resolve_by_superseding(
            graph=knowledge_graph,
            old_id=new_fact_id,
            old_domain=KnowledgeDomain.PROJECT,
            new_id=new_fact_id,
            new_domain=KnowledgeDomain.PROJECT,
            resolution_reason="Self-reference error",
        )


# ==============================================================================
# 3. Domain Router & Multi-Domain Context Bundling Tests
# ==============================================================================

def test_domain_router_context_bundle_synthesis(project_engine):
    """Test synthesizing a segregated context bundle across authorized domains."""
    # Setup project
    proj = project_engine.register_project(
        name="Project Chronos",
        purpose="Time-series cognitive planner",
        tech_stack=["Python", "FastAPI"],
    )
    project_engine.record_decision(
        project_id=proj.project_id,
        title="Async Loop",
        decision_content="Use AnyIO concurrency",
    )

    mem_storage = MockPersonalMemoryStorage()
    router = DomainRouter(project_engine=project_engine, memory_storage=mem_storage)

    ctx = IntelligenceContext(
        actor_id="owner",
        active_project_id=proj.project_id,
        permitted_domains={
            KnowledgeDomain.PERSONAL,
            KnowledgeDomain.PROJECT,
            KnowledgeDomain.DECISION,
        },
        operation_constraints={"allow_external_api": False},  # Local only
    )

    bundle = router.retrieve_context_bundle(
        query="What is the setup for Chronos?",
        intelligence_context=ctx,
    )

    assert bundle.personal_context is not None
    assert "Owner prefers dark mode theme" in bundle.personal_context

    assert bundle.project_context is not None
    assert "Project Chronos" in bundle.project_context

    assert bundle.decision_context is not None
    assert "Async Loop" in bundle.decision_context

    # Render prompt context verifies clear domain segregation
    prompt_md = bundle.render_prompt_context()
    assert "### Personal Memory (Owner Context)" in prompt_md
    assert "### Project Context" in prompt_md
    assert "### Decision History" in prompt_md


def test_domain_router_prevents_personal_memory_leakage_to_api(project_engine):
    """Test that personal memory is NEVER permitted or retrieved when external API is allowed."""
    mem_storage = MockPersonalMemoryStorage()
    router = DomainRouter(project_engine=project_engine, memory_storage=mem_storage)

    # Context with external API allowed attempting to retrieve personal memories MUST fail
    api_ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.PERSONAL, KnowledgeDomain.PROJECT},
        operation_constraints={"allow_external_api": True},
    )

    with pytest.raises(CrossDomainLeakageError, match="Personal owner memory cannot be retrieved"):
        router.retrieve_context_bundle(
            query="tell me about myself and the project",
            intelligence_context=api_ctx,
            target_domains={KnowledgeDomain.PERSONAL},
        )


def test_domain_router_enforces_domain_boundaries(project_engine):
    """Test that requesting unpermitted domains raises DomainIsolationViolation."""
    router = DomainRouter(project_engine=project_engine)

    restricted_ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.PROJECT},  # Only PROJECT permitted
    )

    # Attempting to target PERSONAL or DECISION when only PROJECT is permitted
    with pytest.raises(DomainIsolationViolation, match="not permitted"):
        router.retrieve_context_bundle(
            query="test",
            intelligence_context=restricted_ctx,
            target_domains={KnowledgeDomain.PERSONAL},
        )
