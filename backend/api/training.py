from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from backend.training.curate import DatasetCurator
from backend.training.preflight import run_vram_preflight
from backend.training.train import QLoRATrainer
from backend.training.evaluate import EvaluationHarness
from backend.training.promote import ModelPromoter
from backend.config import get_settings

router = APIRouter(prefix="/training", tags=["training"])

class ExcludeRequest(BaseModel):
    interaction_id: str

class BuildDatasetRequest(BaseModel):
    excluded_interaction_ids: Optional[List[str]] = None
    version: Optional[str] = None

class PromoteRequest(BaseModel):
    version: str
    candidate_score: float
    current_local_score: float
    confirmed: bool = False
    dry_run: Optional[bool] = True

class RollbackRequest(BaseModel):
    target_version: Optional[str] = None

class ExportCloudRequest(BaseModel):
    version: str

def get_curator() -> DatasetCurator:
    from backend.api.chat import history_manager, persona_manager
    return DatasetCurator(history_manager=history_manager, persona_manager=persona_manager)

def get_trainer() -> QLoRATrainer:
    return QLoRATrainer()

def get_evaluator() -> EvaluationHarness:
    return EvaluationHarness()

def get_promoter() -> ModelPromoter:
    return ModelPromoter()

@router.get("/curate")
async def get_curation_summary_endpoint():
    curator = get_curator()
    summary = curator.get_curation_summary()
    return summary

@router.post("/curate/exclude")
async def exclude_interaction_endpoint(req: ExcludeRequest):
    curator = get_curator()
    ok = curator.exclude_interaction(req.interaction_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Interaction not found or failed to exclude")
    return {"status": "excluded", "interaction_id": req.interaction_id}

@router.post("/datasets/build")
async def build_dataset_endpoint(req: BuildDatasetRequest):
    curator = get_curator()
    jsonl_path, metadata = curator.build_dataset(
        excluded_ids=req.excluded_interaction_ids,
        version=req.version
    )
    return {
        "status": "ok",
        "dataset_path": str(jsonl_path),
        "metadata": metadata
    }

@router.get("/datasets")
async def list_datasets_endpoint():
    curator = get_curator()
    return curator.list_datasets()

@router.get("/preflight")
async def get_preflight_endpoint():
    trainer = get_trainer()
    return trainer.run_preflight_check()

@router.post("/export-cloud")
async def export_cloud_bundle_endpoint(req: ExportCloudRequest):
    settings = get_settings()
    dataset_path = settings.datasets_dir / req.version / "train.jsonl"
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset for version {req.version} not found at {dataset_path}")
    trainer = get_trainer()
    zip_path = trainer.export_cloud_bundle(dataset_path)
    return {
        "status": "ok",
        "bundle_path": str(zip_path),
        "filename": zip_path.name
    }

@router.get("/promotions")
async def get_promotions_endpoint():
    promoter = get_promoter()
    return {
        "active_model": promoter.get_active_model(),
        "history": promoter.get_history()
    }

@router.get("/pending-approval")
async def get_pending_approval_endpoint():
    promoter = get_promoter()
    candidate = promoter.get_pending_candidate()
    return candidate or {"status": "none"}

@router.post("/reject-pending")
async def reject_pending_endpoint():
    promoter = get_promoter()
    promoter.clear_pending_candidate()
    return {"status": "rejected"}

@router.post("/promote")
async def promote_model_endpoint(req: PromoteRequest):
    promoter = get_promoter()
    if not req.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Approval gate: Model promotion requires explicit owner confirmation in the UI."
        )
    try:
        record = promoter.promote(
            version=req.version,
            candidate_score=req.candidate_score,
            current_local_score=req.current_local_score,
            confirmed=True,
            dry_run=bool(req.dry_run)
        )
        return {"status": "promoted", "record": record}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/rollback")
async def rollback_model_endpoint(req: RollbackRequest):
    promoter = get_promoter()
    try:
        record = promoter.rollback(target_version=req.target_version)
        return {"status": "rolled_back", "active_model": record}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
