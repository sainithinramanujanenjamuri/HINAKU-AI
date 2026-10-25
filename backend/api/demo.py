import json
import os
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.config import ROOT_DIR

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_FIXTURE_PATH = ROOT_DIR / "tests" / "fixtures" / "demo_data.json"

def _load_demo_data():
    if DEMO_FIXTURE_PATH.exists():
        with open(DEMO_FIXTURE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"app_info": {}, "conversations": [], "memories": []}

@router.get("/status")
async def demo_status():
    is_demo = os.environ.get("HINAKU_UI_DEMO", "0") == "1"
    return {"demo_mode": is_demo}

@router.get("/info")
async def demo_info():
    data = _load_demo_data()
    return data.get("app_info", {})

@router.get("/conversations")
async def demo_conversations():
    data = _load_demo_data()
    # Return without full message payloads for list view
    return [
        {
            "id": c["id"],
            "title": c["title"],
            "is_private": c.get("is_private", False),
            "pinned": bool(c.get("pinned", 0)),
            "created_at": c["created_at"],
            "updated_at": c["updated_at"]
        }
        for c in data.get("conversations", [])
    ]

@router.get("/conversations/{conv_id}")
async def demo_get_conversation(conv_id: str):
    data = _load_demo_data()
    for c in data.get("conversations", []):
        if c["id"] == conv_id:
            return c
    raise HTTPException(status_code=404, detail="Demo conversation not found")

@router.get("/memories")
async def demo_memories():
    data = _load_demo_data()
    return data.get("memories", [])

