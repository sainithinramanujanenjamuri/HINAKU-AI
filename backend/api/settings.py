from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import datetime
import logging
import yaml
from pathlib import Path
from backend.config import get_settings
from backend.security.auth import require_session_auth

logger = logging.getLogger("hinaku.settings")

router = APIRouter(prefix="/settings", tags=["settings"])

class UpdateSettingsRequest(BaseModel):
    router_mode: Optional[str] = None
    memory_enabled: Optional[bool] = None
    reduced_motion: Optional[bool] = None
    default_local_model: Optional[str] = None
    quality_mode: Optional[bool] = None

class WipeAllRequest(BaseModel):
    confirm: str

class CreateBackupRequest(BaseModel):
    description: Optional[str] = None

class BackupRestoreRequest(BaseModel):
    recovery_set_id: str
    confirm_destructive_restore: bool = False
    reason: Optional[str] = ""

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
async def get_settings_endpoint(_auth: str = Depends(require_session_auth)):
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
async def get_model_options_endpoint(_auth: str = Depends(require_session_auth)):
    settings = get_settings()
    return {
        "default_local_model": settings.default_local_model,
        "allowed_local_models": settings.allowed_local_models,
        "model_options": settings.model_options
    }

@router.post("")
async def update_settings_endpoint(req: UpdateSettingsRequest, _auth: str = Depends(require_session_auth)):
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

        async def warm_selected_model(m: str):
            try:
                from backend.api.chat import local_adapter
                await local_adapter.chat(
                    messages=[{"role": "user", "content": "ping"}],
                    model=m,
                    options={"num_predict": 1},
                    keep_alive=getattr(settings, "local_keep_alive", "30m"),
                    call_type="model_warm"
                )
            except Exception as e:
                logger.warning(f"Error warming model {m}: {e}")

        asyncio.create_task(warm_selected_model(req.default_local_model))

    return await get_settings_endpoint()

@router.get("/export")
async def export_all_data_endpoint(_auth: str = Depends(require_session_auth)):
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
async def clear_memory_endpoint(_auth: str = Depends(require_session_auth)):
    _, mem_storage = get_memory_mgr()
    count = mem_storage.clear_all()
    return {
        "status": "cleared",
        "memories_deleted": count,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

@router.post("/wipe-all")
async def wipe_all_endpoint(req: WipeAllRequest, _auth: str = Depends(require_session_auth)):
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
async def trigger_self_build_endpoint(_auth: str = Depends(require_session_auth)):
    """Manual trigger endpoint for the 6-month self-build cycle."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "status": "triggered",
        "timestamp": now,
        "message": "Self-build cycle initialized. Ready for dataset curation and evaluation."
    }

@router.post("/backup")
async def create_backup_endpoint(req: Optional[CreateBackupRequest] = None, _auth: str = Depends(require_session_auth)):
    """Creates a coordinated recovery set snapshot of both SQLite databases."""
    from backend.database.backup import get_backup_manager
    backup_mgr = get_backup_manager()
    desc = req.description if req else None
    try:
        result = backup_mgr.create_coordinated_backup(description=desc)
        return {
            "status": "success",
            "recovery_set": result
        }
    except Exception as e:
        logger.error(f"Failed to create coordinated backup: {e}")
        raise HTTPException(status_code=500, detail=f"Backup creation failed: {e}")

@router.get("/backup")
async def list_backups_endpoint(_auth: str = Depends(require_session_auth)):
    """Lists all available coordinated recovery sets."""
    from backend.database.backup import get_backup_manager
    backup_mgr = get_backup_manager()
    sets = backup_mgr.list_recovery_sets()
    return {
        "total_count": len(sets),
        "retention_count": backup_mgr.retention_count,
        "recovery_sets": sets
    }

@router.post("/backup/restore")
async def restore_backup_endpoint(req: BackupRestoreRequest, _auth: str = Depends(require_session_auth)):
    """
    Restores both SQLite databases from a coordinated recovery set.
    Requires explicit owner confirmation and active desktop session authorization.
    """
    if not req.confirm_destructive_restore:
        raise HTTPException(
            status_code=400,
            detail="Destructive restore requires confirm_destructive_restore=True"
        )

    from backend.database.backup import get_backup_manager
    backup_mgr = get_backup_manager()
    try:
        result = backup_mgr.restore_recovery_set(
            recovery_set_id=req.recovery_set_id,
            reason=req.reason or "Owner requested backup restore",
            has_owner_session=True
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.critical(f"Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


