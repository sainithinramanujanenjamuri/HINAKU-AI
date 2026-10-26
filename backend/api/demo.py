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
    return {"app_info": {}, "conversations": [], "memories": [], "dataset": {}, "ratings": []}

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

@router.get("/conversations/{conv_id}/attachments")
async def demo_get_conversation_attachments(conv_id: str):
    data = _load_demo_data()
    for c in data.get("conversations", []):
        if c["id"] == conv_id:
            atts = c.get("attachments", [])
            return {"conversation_id": conv_id, "count": len(atts), "attachments": atts}
    return {"conversation_id": conv_id, "count": 0, "attachments": []}

@router.get("/memories")
async def demo_memories():
    data = _load_demo_data()
    return data.get("memories", [])

@router.get("/curate")
async def demo_curate():
    data = _load_demo_data()
    return data.get("dataset", {
        "candidate_count": 42,
        "min_required": 200,
        "ready": False,
        "candidates": [
            {
                "id": "cand-1",
                "user_prompt": "Compare surface codes and bosonic cat codes for fault-tolerant computing.",
                "answer": "Surface codes offer an established 2D layout but demand thousands of physical qubits per logical qubit. Bosonic cat codes leverage infinite-dimensional Hilbert spaces to autonomously correct bit flips.",
                "model": "bonsai-2:9b",
                "backend": "local",
                "feedback": "thumbs_up"
            },
            {
                "id": "cand-2",
                "user_prompt": "What is the capital of Australia?",
                "answer": "Canberra.",
                "model": "bonsai-2:9b",
                "backend": "local",
                "feedback": "thumbs_up"
            }
        ]
    })

@router.get("/settings")
async def demo_settings():
    data = _load_demo_data()
    app_info = data.get("app_info", {})
    return {
        "app_name": app_info.get("app_name", "HINAKU"),
        "router_mode": app_info.get("router", {}).get("mode", "auto"),
        "memory_enabled": True,
        "reduced_motion": bool(app_info.get("reduced_motion", False)),
        "default_local_model": app_info.get("default_model", "bonsai-2:9b"),
        "allowed_local_models": app_info.get("allowed_models", ["bonsai-2:9b", "gemma3:4b", "qwen3.5:4b"]),
        "model_options": [
            {"name": "bonsai-2:9b", "description": "Local primary (9B)"},
            {"name": "gemma3:4b", "description": "Local lightweight (4B)"},
            {"name": "qwen3.5:4b", "description": "Local fast (4B)"}
        ],
        "quality_mode": True,
        "api_provider": app_info.get("router", {}).get("api_provider", "openrouter"),
        "api_model": app_info.get("router", {}).get("api_model", "meta-llama/llama-3.3-70b-instruct:free"),
        "api_ready": True,
        "api_logged_by_provider": True
    }

@router.get("/ratings")
async def demo_ratings():
    data = _load_demo_data()
    return data.get("ratings", [
        {
            "model": "bonsai-2:9b",
            "backend": "local",
            "thumbs_up": 24,
            "thumbs_down": 1,
            "total_feedback": 25,
            "upvote_pct": 96.0,
            "avg_latency_ms": 1340
        },
        {
            "model": "gemma3:4b",
            "backend": "local",
            "thumbs_up": 18,
            "thumbs_down": 2,
            "total_feedback": 20,
            "upvote_pct": 90.0,
            "avg_latency_ms": 980
        },
        {
            "model": "qwen3.5:4b",
            "backend": "local",
            "thumbs_up": 12,
            "thumbs_down": 3,
            "total_feedback": 15,
            "upvote_pct": 80.0,
            "avg_latency_ms": 1120
        }
    ])
