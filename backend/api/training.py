from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from backend.training.curate import DatasetCurator
from backend.config import get_settings

router = APIRouter(prefix="/training", tags=["training"])

class ExcludeRequest(BaseModel):
    interaction_id: str

class BuildDatasetRequest(BaseModel):
    excluded_interaction_ids: Optional[List[str]] = None
    version: Optional[str] = None

def get_curator() -> DatasetCurator:
    from backend.api.chat import history_manager, persona_manager
    return DatasetCurator(history_manager=history_manager, persona_manager=persona_manager)

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
