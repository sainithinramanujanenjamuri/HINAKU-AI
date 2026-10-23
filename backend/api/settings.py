from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import datetime
import yaml
from pathlib import Path
from backend.config import get_settings

router = APIRouter(prefix="/settings", tags=["settings"])

class UpdateSettingsRequest(BaseModel):
    router_mode: Optional[str] = None
    memory_enabled: Optional[bool] = None
    reduced_motion: Optional[bool] = None
    default_local_model: Optional[str] = None
    quality_mode: Optional[bool] = None

class WipeAllRequest(BaseModel):
    confirm: str

def get_history_mgr():
    from backend.api.chat import history_manager
    return history_manager

def get_memory_mgr():
    from backend.api.chat import memory_manager, memory_storage
    return memory_manager, memory_storage

def get_router():
    from backend.api.chat import model_router
    return model_router

@router.get("")
async def get_settings_endpoint():
    settings = get_settings()
    router_inst = get_router()
    mem_mgr, _ = get_memory_mgr()

    api_ready = bool(settings.get_api_key())
    return {
        "app_name": settings.app_name,
        "router_mode": router_inst.mode if router_inst else settings.router_mode,
        "memory_enabled": mem_mgr.enabled if mem_mgr else settings.memory_enabled,
        "reduced_motion": bool(settings.app.get("reduced_motion", False)),
        "default_local_model": settings.default_local_model,
        "allowed_local_models": settings.allowed_local_models,
        "model_options": settings.model_options,
        "quality_mode": settings.quality_mode,
        "api_provider": settings.api_provider,
        "api_model": settings.api_model,
        "api_ready": api_ready,
        "api_logged_by_provider": settings.api_logged_by_provider
    }

@router.get("/model-options")
async def get_model_options_endpoint():
    settings = get_settings()
    return {
        "default_local_model": settings.default_local_model,
        "allowed_local_models": settings.allowed_local_models,
        "model_options": settings.model_options
    }

@router.post("")
async def update_settings_endpoint(req: UpdateSettingsRequest):
    settings = get_settings()
    router_inst = get_router()
    mem_mgr, _ = get_memory_mgr()

    if req.router_mode is not None:
        if req.router_mode not in ("auto", "local_only", "api_only"):
            raise HTTPException(status_code=400, detail="Invalid router mode. Must be auto, local_only, or api_only")
        settings.router["mode"] = req.router_mode
        if router_inst:
            router_inst.mode = req.router_mode

    if req.memory_enabled is not None:
        settings.memory["enabled"] = req.memory_enabled
        if mem_mgr:
            mem_mgr.enabled = req.memory_enabled

    if req.reduced_motion is not None:
        settings.app["reduced_motion"] = req.reduced_motion

    if req.quality_mode is not None:
        settings.local["quality_mode"] = req.quality_mode

    if req.default_local_model is not None:
        if req.default_local_model not in settings.allowed_local_models:
            raise HTTPException(status_code=400, detail=f"Model '{req.default_local_model}' is not in allowed_local_models")
        settings.local["default_model"] = req.default_local_model

    return await get_settings_endpoint()

@router.get("/export")
async def export_all_data_endpoint():
    history_mgr = get_history_mgr()
    _, mem_storage = get_memory_mgr()

    db_data = history_mgr.export_all_data()
    memories = mem_storage.export_all()

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "export_version": "1.0",
        "exported_at": now,
        "app": "HINAKU",
        "conversations": db_data.get("conversations", []),
        "messages": db_data.get("messages", []),
        "interactions": db_data.get("interactions", []),
        "memories": memories
    }

@router.post("/clear-memory")
async def clear_memory_endpoint():
    _, mem_storage = get_memory_mgr()
    count = mem_storage.clear_all()
    return {
        "status": "cleared",
        "memories_deleted": count,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

@router.post("/wipe-all")
async def wipe_all_endpoint(req: WipeAllRequest):
    if req.confirm != "WIPE_ALL":
        raise HTTPException(status_code=400, detail="Confirmation token must be exactly 'WIPE_ALL'")

    history_mgr = get_history_mgr()
    _, mem_storage = get_memory_mgr()

    history_mgr.wipe_all_data()
    mem_count = mem_storage.clear_all()

    return {
        "status": "wiped",
        "message": "All conversations, messages, interactions, and memories have been permanently deleted.",
        "memories_cleared": mem_count,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

@router.post("/self-build/run")
async def trigger_self_build_endpoint():
    """Manual trigger endpoint for the 6-month self-build cycle."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "status": "triggered",
        "timestamp": now,
        "message": "Self-build cycle initialized. Ready for dataset curation and evaluation."
    }

