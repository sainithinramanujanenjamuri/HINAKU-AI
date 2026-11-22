from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.api import (
    chat_router,
    conversations_router,
    memories_router,
    settings_router,
    interactions_router,
    training_router,
    self_build_router,
    projects_router,
    tasks_router,
    learning_router,
)
from backend.api.demo import router as demo_router
from backend.api.attachments import router as attachments_router
from backend.config import ROOT_DIR
from backend.database.backup import get_backup_manager
import logging

logger = logging.getLogger("hinaku.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Milestone 7 Step 1: Startup Multi-Database Integrity Check (Fail-Closed)
    backup_mgr = get_backup_manager()
    integrity_result = backup_mgr.verify_startup_integrity()
    if not integrity_result["ok"]:
        failed = integrity_result.get("failed_databases", [])
        logger.critical(
            f"FATAL: Database startup integrity check failed on database(s): {failed}. "
            f"Details: {integrity_result}. Application startup halted to preserve damaged files."
        )
        raise RuntimeError(
            f"Database integrity verification failed on startup: {failed}. "
            "Startup halted to preserve files for recovery."
        )
    logger.info("Database startup integrity check passed for both databases.")

    import asyncio
    import backend.models.prewarm as prewarm_module
    asyncio.create_task(prewarm_module.prewarm_local_models())
    yield

app = FastAPI(title="HINAKU API", version="0.1.0", lifespan=lifespan)

LOCAL_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "pywebview://localhost",
    "app://localhost",
    "null",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(memories_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(interactions_router, prefix="/api")
app.include_router(training_router, prefix="/api")
app.include_router(self_build_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(learning_router, prefix="/api")
app.include_router(demo_router, prefix="/api")
app.include_router(attachments_router)

UI_DIR = ROOT_DIR / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

@app.get("/")
async def serve_index():
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "HINAKU backend is running. UI folder not found."}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import os
    os.environ["HINAKU_USE_REAL_DATA"] = "1"
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)

