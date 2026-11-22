"""
backend/api/projects.py

FastAPI router for HINAKU Project Intelligence.
Provides endpoints for project registration, updating, querying, repository indexing,
and domain-isolated context retrieval.
"""

from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.security.auth import require_session_auth
from backend.intelligence.project_engine import ProjectEngine
from backend.intelligence.project_types import (
    KnowledgeCategory,
    ProjectConfidentiality,
    ProjectKnowledgeItem,
    ProjectRecord,
    ProjectStatus,
)
from backend.intelligence.types import (
    ImplementationStatus,
    KnowledgeDomain,
    KnowledgeProvenance,
    SourceAuthority,
)
from backend.intelligence.context import IntelligenceContext
from backend.intelligence.errors import (
    DuplicateProjectError,
    IntelligenceError,
    ProjectConfidentialityViolation,
    ProjectNotFoundError,
)

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_session_auth)])


def get_project_engine() -> ProjectEngine:
    settings = get_settings()
    return ProjectEngine(settings.sqlite_path)


# ------------------------------------------------------------------------------
# Request / Response Models
# ------------------------------------------------------------------------------

class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Name of the project")
    purpose: str = Field(..., min_length=1, description="Core objective / purpose of project")
    description: Optional[str] = Field("", description="Detailed overview")
    project_id: Optional[str] = Field(None, description="Optional custom project ID")
    tech_stack: Optional[List[str]] = Field(default_factory=list, description="Primary languages/frameworks")
    repo_path: Optional[str] = Field(None, description="Local filesystem path to project root")
    confidentiality: Optional[str] = Field("internal", description="internal | confidential | restricted")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary project metadata")


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    purpose: Optional[str] = None
    status: Optional[str] = None
    tech_stack: Optional[List[str]] = None
    repo_path: Optional[str] = None
    confidentiality: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class KnowledgeItemCreateRequest(BaseModel):
    category: str = Field(..., description="Structured category (e.g. decisions, architecture, tech_stack)")
    title: str = Field(..., min_length=1, description="Short summary title")
    content: str = Field(..., min_length=1, description="Knowledge detail content")
    claim_confidence: Optional[float] = Field(1.0, ge=0.0, le=1.0)
    verification_status: Optional[str] = Field("accepted", description="proposed | accepted | verified | rejected")
    source_authority: Optional[str] = Field("owner", description="owner_directive | assistant_suggestion | external_source")
    implementation_evidence: Optional[Dict[str, Any]] = Field(None, description="Concrete evidence if status is verified/implemented")
    tags: Optional[List[str]] = Field(default_factory=list)


class RepoIndexRequest(BaseModel):
    max_files: Optional[int] = Field(500, ge=1, le=5000)


# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------

@router.get("", response_model=List[Dict[str, Any]])
async def list_projects(
    status_filter: Optional[str] = Query(None, alias="status"),
    confidentiality: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
):
    """Lists registered projects with optional status and confidentiality filtering."""
    engine = get_project_engine()
    st = None
    if status_filter:
        try:
            st = ProjectStatus(status_filter.lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project status '{status_filter}'."
            )
    projects = engine.list_projects(status=st, include_deleted=include_deleted)

    if confidentiality:
        target_conf = confidentiality.lower()
        projects = [p for p in projects if p.confidentiality.value.lower() == target_conf]

    return [p.to_dict() for p in projects]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def create_project(req: ProjectCreateRequest):
    """Registers a new project."""
    engine = get_project_engine()
    try:
        conf = ProjectConfidentiality(req.confidentiality.lower()) if req.confidentiality else ProjectConfidentiality.INTERNAL
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid confidentiality classification '{req.confidentiality}'. Allowed: internal, confidential, restricted."
        )

    try:
        project = engine.register_project(
            name=req.name.strip(),
            purpose=req.purpose.strip(),
            description=(req.description or "").strip(),
            tech_stack=req.tech_stack or [],
            repo_path=req.repo_path,
            confidentiality=conf,
            metadata=req.metadata or {},
            project_id=req.project_id,
        )
        return project.to_dict()
    except DuplicateProjectError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{project_id}", response_model=Dict[str, Any])
async def get_project(project_id: str):
    """Retrieves project details by ID."""
    engine = get_project_engine()
    project = engine.get_project(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")
    return project.to_dict()


@router.patch("/{project_id}", response_model=Dict[str, Any])
@router.put("/{project_id}", response_model=Dict[str, Any])
async def update_project(project_id: str, req: ProjectUpdateRequest):
    """Updates an existing project."""
    engine = get_project_engine()
    updates = req.model_dump(exclude_unset=True)

    if "confidentiality" in updates and updates["confidentiality"]:
        try:
            updates["confidentiality"] = ProjectConfidentiality(updates["confidentiality"].lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid confidentiality classification '{updates['confidentiality']}'."
            )

    if "status" in updates and updates["status"]:
        try:
            updates["status"] = ProjectStatus(updates["status"].lower())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid project status '{updates['status']}'."
            )

    try:
        updated = engine.store.update_project(project_id, updates)
        return updated.to_dict()
    except ProjectNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    hard_delete: bool = Query(False),
    owner_confirmed: bool = Query(False),
):
    """Soft-deletes (or hard-deletes with explicit owner confirmation) a project."""
    engine = get_project_engine()
    try:
        success = engine.store.delete_project(
            project_id=project_id,
            hard_delete=hard_delete,
            owner_confirmed=owner_confirmed,
        )
        return {
            "status": "deleted",
            "project_id": project_id,
            "hard_deleted": hard_delete,
            "success": success,
        }
    except ProjectNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{project_id}/context")
async def get_project_context(
    project_id: str,
    max_tokens: int = Query(1500, ge=100, le=8000),
    allow_external_api: bool = Query(False),
):
    """
    Retrieves assembled context for a project.
    Strictly enforces domain isolation and blocks external transmission if confidential.
    """
    engine = get_project_engine()
    project = engine.get_project(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")

    ctx = IntelligenceContext(
        actor_id="owner",
        active_project_id=project_id,
        permitted_domains={KnowledgeDomain.PROJECT},
        operation_constraints={"allow_external_api": allow_external_api},
    )

    try:
        formatted_context = engine.retrieve_project_context(
            project_id=project_id,
            intelligence_context=ctx,
            max_tokens=max_tokens,
        )
        return {
            "project_id": project_id,
            "name": project.name,
            "confidentiality": project.confidentiality.value,
            "context": formatted_context,
        }
    except ProjectConfidentialityViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{project_id}/knowledge", response_model=List[Dict[str, Any]])
async def list_project_knowledge(
    project_id: str,
    category: Optional[str] = Query(None),
):
    """Lists structured knowledge items associated with a project."""
    engine = get_project_engine()
    project = engine.get_project(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")

    cat = KnowledgeCategory(category.lower()) if category else None
    items = engine.list_knowledge(project_id, category=cat)
    return [i.to_dict() for i in items]


@router.post("/{project_id}/knowledge", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def add_project_knowledge(project_id: str, req: KnowledgeItemCreateRequest):
    """Adds a structured knowledge item to a project."""
    engine = get_project_engine()
    project = engine.get_project(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")

    try:
        cat = KnowledgeCategory(req.category.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid knowledge category '{req.category}'."
        )

    try:
        auth = SourceAuthority(req.source_authority.lower())
    except ValueError:
        auth = SourceAuthority.OWNER_DIRECTIVE

    try:
        v_status = ImplementationStatus(req.verification_status.lower())
    except ValueError:
        v_status = ImplementationStatus.ACCEPTED

    evidence = req.implementation_evidence
    if v_status in (ImplementationStatus.IMPLEMENTED, ImplementationStatus.VERIFIED) and not evidence:
        evidence = {"source": "manual_entry", "verified_by": "owner"}

    provenance = KnowledgeProvenance(
        source_authority=auth,
        claim_confidence=req.claim_confidence if req.claim_confidence is not None else 1.0,
        verification_status=v_status,
        implementation_evidence=evidence,
    )

    item = ProjectKnowledgeItem(
        item_id=str(uuid.uuid4()),
        project_id=project_id,
        category=cat,
        title=req.title.strip(),
        content=req.content.strip(),
        provenance=provenance,
        tags=req.tags or [],
    )

    created = engine.store.add_knowledge_item(item)
    return created.to_dict()


@router.post("/{project_id}/index_repo", response_model=Dict[str, Any])
async def index_project_repo(project_id: str, req: Optional[RepoIndexRequest] = None):
    """Indexes repository files for a project if configured with repo_path."""
    engine = get_project_engine()
    project = engine.get_project(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")

    if not project.repo_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Project '{project_id}' does not have a configured repo_path."
        )

    max_files = req.max_files if req and req.max_files else 500
    try:
        files = engine.index_project_repository(project_id=project_id, max_files=max_files)
        # Suppress file summary snippets for restricted projects to prevent indirect leakage
        is_restricted = project.confidentiality == ProjectConfidentiality.RESTRICTED
        file_dicts = []
        for f in files[:20]:
            d = f.to_dict()
            if is_restricted:
                d["summary"] = "[restricted]"
            file_dicts.append(d)

        return {
            "status": "indexed",
            "project_id": project_id,
            "indexed_count": len(files),
            "files": file_dicts,
        }
    except IntelligenceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
