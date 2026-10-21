from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from backend.scheduler.service import SelfBuildScheduler
from backend.scheduler.coordinator import SelfBuildCoordinator
from backend.scheduler.activity import check_training_activity_and_power

router = APIRouter(prefix="/self-build", tags=["self-build"])

_scheduler_instance: Optional[SelfBuildScheduler] = None

def get_scheduler() -> SelfBuildScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SelfBuildScheduler()
    return _scheduler_instance

class TriggerRunRequest(BaseModel):
    force: Optional[bool] = True
    dry_run: Optional[bool] = True
    version: Optional[str] = None

@router.get("/status")
async def get_self_build_status_endpoint():
    sched = get_scheduler()
    status = sched.get_status()
    activity = check_training_activity_and_power()
    status["activity"] = activity
    return status

@router.get("/check-due")
async def check_self_build_due_endpoint():
    sched = get_scheduler()
    return sched.check_run_due()

@router.post("/run")
async def trigger_self_build_endpoint(req: Optional[TriggerRunRequest] = None):
    sched = get_scheduler()
    force = req.force if req else True
    dry_run = req.dry_run if req else True
    ver = req.version if req else None

    result = await sched.trigger_now(force=force, dry_run=dry_run)
    return {
        "status": "success",
        "result": result
    }

@router.get("/reports")
async def get_self_build_reports_endpoint():
    sched = get_scheduler()
    return sched.coordinator.get_reports()

@router.get("/reports/latest")
async def get_latest_self_build_report_endpoint():
    sched = get_scheduler()
    rep = sched.coordinator.get_latest_report()
    if not rep:
        raise HTTPException(status_code=404, detail="No self-build reports found.")
    return rep
