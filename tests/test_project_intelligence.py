"""
tests/test_project_intelligence.py

Comprehensive unit and integration test suite for HINAKU Phase 1 Milestone 2:
Project Intelligence Engine, Repository Grounding, Discovery, and Context Security.
"""

from pathlib import Path
import pytest
import time

from backend.intelligence import (
    CognitiveTask,
    ContextSecurityViolation,
    DomainIsolationViolation,
    DuplicateProjectError,
    ImplementationStatus,
    IntelligenceContext,
    IntelligenceError,
    KnowledgeCategory,
    KnowledgeDomain,
    KnowledgeProvenance,
    ProjectConfidentiality,
    ProjectConfidentialityViolation,
    ProjectDiscovery,
    ProjectEngine,
    ProjectNotFoundError,
    ProjectRecord,
    ProjectStatus,
    ProvenanceError,
    RepoGrounding,
    RepositoryAccessViolation,
    SourceAuthority,
    UnauthorizedRepositoryAccessError,
)


@pytest.fixture
def project_engine(tmp_path):
    """Provides a fresh ProjectEngine instance backed by a temporary SQLite database."""
    db_file = tmp_path / "test_projects.db"
    return ProjectEngine(db_file)


@pytest.fixture
def sample_repo(tmp_path):
    """Creates a mock repository structure with safe source files and forbidden secret files."""
    repo_dir = tmp_path / "mock_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Safe source files
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "main.py").write_text("print('Hello HINAKU')", encoding="utf-8")
    (src_dir / "utils.py").write_text("def add(a, b): return a + b", encoding="utf-8")
    (repo_dir / "README.md").write_text("# Mock Project", encoding="utf-8")

    # Forbidden files that MUST be excluded from indexing
    git_dir = repo_dir / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text("git config", encoding="utf-8")

    venv_dir = repo_dir / "venv" / "Lib"
    venv_dir.mkdir(parents=True, exist_ok=True)
    (venv_dir / "site.py").write_text("venv code", encoding="utf-8")

    (repo_dir / ".env").write_text("SECRET_KEY=supersecret123", encoding="utf-8")
    (repo_dir / "database.sqlite3").write_text("sqlite dummy data", encoding="utf-8")
    (repo_dir / "private.key").write_text("PRIVATE KEY DATA", encoding="utf-8")

    return repo_dir


# ==============================================================================
# 1. Project Identity and Registration Tests
# ==============================================================================

def test_project_registration_and_retrieval(project_engine):
    """Test registering a project and retrieving it by ID and in lists."""
    proj = project_engine.register_project(
        name="HINAKU Core",
        purpose="Personal AI digital companion and intelligence core",
        description="Autonomous desktop assistant",
        tech_stack=["Python", "FastAPI", "SQLite", "Ollama"],
        confidentiality=ProjectConfidentiality.INTERNAL,
        status=ProjectStatus.ACTIVE,
    )

    assert proj.project_id == "hinaku-core"
    assert proj.name == "HINAKU Core"
    assert proj.status == ProjectStatus.ACTIVE
    assert proj.confidentiality == ProjectConfidentiality.INTERNAL

    fetched = project_engine.get_project("hinaku-core")
    assert fetched is not None
    assert fetched.name == "HINAKU Core"
    assert "FastAPI" in fetched.tech_stack

    # List filtering
    active_projects = project_engine.list_projects(status=ProjectStatus.ACTIVE)
    assert len(active_projects) == 1
    assert active_projects[0].project_id == "hinaku-core"

    archived_projects = project_engine.list_projects(status=ProjectStatus.ARCHIVED)
    assert len(archived_projects) == 0


def test_project_duplicate_prevention(project_engine):
    """Test that duplicate project IDs and duplicate names are rejected."""
    project_engine.register_project(
        name="Alpha Project",
        purpose="Testing uniqueness",
        project_id="proj-alpha",
    )

    # Duplicate ID
    with pytest.raises(DuplicateProjectError, match="already exists"):
        project_engine.register_project(
            name="Different Name",
            purpose="Trying same ID",
            project_id="proj-alpha",
        )

    # Duplicate Name (case-insensitive)
    with pytest.raises(DuplicateProjectError, match="already exists"):
        project_engine.register_project(
            name="alpha project",
            purpose="Trying duplicate name",
            project_id="proj-alpha-2",
        )


def test_project_lifecycle_transitions(project_engine):
    """Test transitioning a project through lifecycle states."""
    proj = project_engine.register_project(
        name="Lifecycle Demo",
        purpose="Demonstrating status changes",
        status=ProjectStatus.PROVISIONAL,
    )
    assert proj.status == ProjectStatus.PROVISIONAL

    # Promote provisional to active
    promoted = project_engine.promote_provisional_project(proj.project_id, owner_confirmed=True)
    assert promoted.status == ProjectStatus.ACTIVE

    # Pause project
    paused = project_engine.update_project(proj.project_id, {"status": ProjectStatus.PAUSED})
    assert paused.status == ProjectStatus.PAUSED

    # Archive project
    archived = project_engine.update_project(proj.project_id, {"status": ProjectStatus.ARCHIVED})
    assert archived.status == ProjectStatus.ARCHIVED


def test_project_soft_and_hard_delete_safety(project_engine):
    """Test non-destructive soft deletion vs. owner-confirmed hard deletion."""
    proj = project_engine.register_project(
        name="Deletable Proj",
        purpose="Testing deletion rules",
    )

    # Soft delete (default)
    success = project_engine.delete_project(proj.project_id, hard_delete=False)
    assert success is True
    assert project_engine.get_project(proj.project_id) is None
    # Still retrievable via internal flag to preserve history
    assert project_engine.store.get_project(proj.project_id, include_deleted=True) is not None

    # Hard delete without owner confirmation MUST fail
    with pytest.raises(IntelligenceError, match="owner confirmation"):
        project_engine.delete_project(proj.project_id, hard_delete=True, owner_confirmed=False)

    # Hard delete WITH owner confirmation succeeds
    hard_success = project_engine.delete_project(proj.project_id, hard_delete=True, owner_confirmed=True)
    assert hard_success is True
    assert project_engine.store.get_project(proj.project_id, include_deleted=True) is None


# ==============================================================================
# 2. Project Discovery Tests
# ==============================================================================

def test_project_discovery_matches_existing_project(project_engine):
    """Test recognizing an existing registered project from conversational text."""
    project_engine.register_project(
        name="HINAKU Core",
        purpose="Personal AI desktop companion",
        tech_stack=["Python", "FastAPI", "Ollama"],
        project_id="hinaku-core",
    )

    # Exact name match
    cand = project_engine.discover_project_from_text("Can you check the architecture of HINAKU Core?")
    assert cand is not None
    assert cand.matched_project_id == "hinaku-core"
    assert cand.candidate_name == "HINAKU Core"
    assert cand.confidence >= 0.8
    assert cand.is_new_project is False

    # Tech stack overlap match
    cand2 = project_engine.discover_project_from_text("How is the FastAPI backend configured in hinaku-core?")
    assert cand2 is not None
    assert cand2.matched_project_id == "hinaku-core"


def test_project_discovery_detects_new_project_candidate(project_engine):
    """Test detecting a new candidate project from conversational declaration."""
    prompt = "I am working on a project called QuantumForge for simulation."
    cand = project_engine.discover_project_from_text(prompt)

    assert cand is not None
    assert cand.candidate_name.lower() == "quantumforge"
    assert cand.is_new_project is True
    assert cand.needs_owner_confirmation is True


# ==============================================================================
# 3. Structured Project Knowledge & Provenance Tests
# ==============================================================================

def test_knowledge_provenance_decoupling_and_invariants(project_engine):
    """Test that accepted decisions do NOT become implemented without evidence."""
    proj = project_engine.register_project(name="Orchestrator", purpose="Task routing")

    # Record accepted decision: status is ACCEPTED
    decision = project_engine.record_decision(
        project_id=proj.project_id,
        title="Router Architecture Decision",
        decision_content="Adopt hybrid model router with local Gemma and fallback API",
        authority=SourceAuthority.OWNER_DIRECTIVE,
    )
    assert decision.provenance.verification_status == ImplementationStatus.ACCEPTED
    assert decision.provenance.source_authority == SourceAuthority.OWNER_DIRECTIVE
    assert decision.provenance.implementation_evidence is None

    # Attempting to add an IMPLEMENTED item with no evidence MUST raise ProvenanceError
    with pytest.raises(ProvenanceError, match="strictly requires concrete implementation evidence"):
        project_engine.add_knowledge(
            project_id=proj.project_id,
            category=KnowledgeCategory.IMPLEMENTATION,
            title="Unverified claim",
            content="I implemented everything",
            provenance=KnowledgeProvenance(
                source_authority=SourceAuthority.ASSISTANT_SUGGESTION,
                claim_confidence=0.9,
                verification_status=ImplementationStatus.IMPLEMENTED,
                implementation_evidence=None,  # Forbidden!
            ),
        )


def test_knowledge_updates_create_audit_revisions(project_engine):
    """Test that updating a knowledge item creates immutable audit records in revision history."""
    proj = project_engine.register_project(name="DocEngine", purpose="Documentation analysis")

    item = project_engine.add_knowledge(
        project_id=proj.project_id,
        category=KnowledgeCategory.ARCHITECTURE,
        title="Context Budgeting",
        content="Max prompt tokens set to 1500",
        provenance=KnowledgeProvenance(
            source_authority=SourceAuthority.OWNER_DIRECTIVE,
            claim_confidence=1.0,
            verification_status=ImplementationStatus.ACCEPTED,
        ),
    )
    assert item.revision == 1

    # Check initial revision
    revs_initial = project_engine.get_revisions(item.item_id)
    assert len(revs_initial) == 1
    assert revs_initial[0].new_content == "Max prompt tokens set to 1500"

    # Update knowledge item with new content and updated provenance
    updated_prov = KnowledgeProvenance(
        source_authority=SourceAuthority.OWNER_DIRECTIVE,
        claim_confidence=1.0,
        verification_status=ImplementationStatus.ACCEPTED,
    )
    updated_item = project_engine.update_knowledge(
        item_id=item.item_id,
        new_content="Max prompt tokens increased to 2500 per hardware review",
        provenance=updated_prov,
        changed_by="owner",
        reason="Upgraded VRAM headroom",
    )
    assert updated_item.revision == 2
    assert updated_item.content == "Max prompt tokens increased to 2500 per hardware review"

    # Verify audit revision history
    revs_after = project_engine.get_revisions(item.item_id)
    assert len(revs_after) == 2
    assert revs_after[1].previous_content == "Max prompt tokens set to 1500"
    assert revs_after[1].new_content == "Max prompt tokens increased to 2500 per hardware review"
    assert revs_after[1].reason == "Upgraded VRAM headroom"


# ==============================================================================
# 4. Repository Grounding & Exclusion Tests
# ==============================================================================

def test_repo_grounding_indexes_safe_files_and_excludes_secrets(project_engine, sample_repo):
    """Test that repository grounding indexes safe files and strictly excludes secrets/git/venv."""
    proj = project_engine.register_project(
        name="Grounding Test",
        purpose="Verifying repo scanner",
        repo_path=str(sample_repo),
    )

    indexed = project_engine.index_project_repository(proj.project_id)
    rel_paths = [f.relative_path for f in indexed]

    # Safe files must be indexed
    assert "src/main.py" in rel_paths or "src\\main.py" in rel_paths
    assert "README.md" in rel_paths

    # Excluded files MUST NOT be indexed
    for p in rel_paths:
        p_norm = p.replace("\\", "/")
        assert ".git" not in p_norm, f"Found .git file: {p}"
        assert "venv" not in p_norm, f"Found venv file: {p}"
        assert ".env" not in p_norm, f"Found .env file: {p}"
        assert "database.sqlite3" not in p_norm, f"Found sqlite file: {p}"
        assert "private.key" not in p_norm, f"Found private key file: {p}"


def test_repo_grounding_rejects_unauthorized_paths(project_engine, tmp_path):
    """Test that invalid or non-existent repository paths are rejected."""
    with pytest.raises(UnauthorizedRepositoryAccessError):
        RepoGrounding.validate_repository_path(str(tmp_path / "non_existent_dir"))

    with pytest.raises(UnauthorizedRepositoryAccessError):
        RepoGrounding.validate_repository_path("")


def test_repo_grounding_detects_stale_index_and_generates_evidence(project_engine, sample_repo):
    """Test stale file detection when repository files change or are deleted."""
    proj = project_engine.register_project(
        name="Stale Test",
        purpose="Verifying staleness check",
        repo_path=str(sample_repo),
    )

    project_engine.index_project_repository(proj.project_id)

    # Check initially clean
    stale_initial = project_engine.check_repository_staleness(proj.project_id)
    assert len(stale_initial["modified"]) == 0
    assert len(stale_initial["deleted"]) == 0

    # Modify an indexed file
    time.sleep(0.05)  # Ensure mtime tick
    (sample_repo / "README.md").write_text("# Updated Readme Content", encoding="utf-8")

    # Delete an indexed file
    (sample_repo / "src" / "utils.py").unlink()

    stale_after = project_engine.check_repository_staleness(proj.project_id)
    assert "README.md" in stale_after["modified"]
    deleted_norm = [p.replace("\\", "/") for p in stale_after["deleted"]]
    assert "src/utils.py" in deleted_norm

    # Verify evidence generation
    evidence = project_engine.generate_file_evidence_for_project(proj.project_id, "README.md")
    assert evidence["evidence_type"] == "repository_file"
    assert "sha256" in evidence
    assert evidence["size_bytes"] > 0


# ==============================================================================
# 5. Project Context Retrieval & Security Tests
# ==============================================================================

def test_project_context_retrieval_success(project_engine):
    """Test structured context retrieval with decisions and architecture notes."""
    proj = project_engine.register_project(
        name="Project Apex",
        purpose="Core orchestration subsystem",
        tech_stack=["Python", "FastAPI"],
    )

    project_engine.record_decision(
        project_id=proj.project_id,
        title="Storage Backend",
        decision_content="Use embedded SQLite with WAL mode",
    )

    ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.PROJECT},
    )

    summary = project_engine.retrieve_project_context(proj.project_id, ctx)
    assert "### Project Context: Project Apex" in summary
    assert "Core orchestration subsystem" in summary
    assert "Storage Backend" in summary
    assert "embedded SQLite" in summary


def test_project_context_retrieval_domain_isolation(project_engine):
    """Test that access is denied if KnowledgeDomain.PROJECT is not permitted."""
    proj = project_engine.register_project(name="Domain Guard Proj", purpose="Boundary test")

    # Context without KnowledgeDomain.PROJECT
    restricted_ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.PERSONAL},  # Only PERSONAL
    )

    with pytest.raises(DomainIsolationViolation, match="not permitted"):
        project_engine.retrieve_project_context(proj.project_id, restricted_ctx)


def test_project_context_confidentiality_enforcement(project_engine):
    """Test that CONFIDENTIAL projects reject retrieval if external API routing is permitted."""
    proj = project_engine.register_project(
        name="TopSecret Engine",
        purpose="Proprietary reasoning architecture",
        confidentiality=ProjectConfidentiality.CONFIDENTIAL,
    )

    # Context with external API allowed MUST be rejected
    api_ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.PROJECT},
        operation_constraints={"allow_external_api": True},
    )

    with pytest.raises(ProjectConfidentialityViolation, match="External API transmission is strictly prohibited"):
        project_engine.retrieve_project_context(proj.project_id, api_ctx)

    # Context without external API succeeds
    local_ctx = IntelligenceContext(
        actor_id="owner",
        permitted_domains={KnowledgeDomain.PROJECT},
        operation_constraints={"allow_external_api": False},
    )
    result = project_engine.retrieve_project_context(proj.project_id, local_ctx)
    assert "TopSecret Engine" in result
