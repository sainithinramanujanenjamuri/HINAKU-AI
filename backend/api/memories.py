from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from backend.config import get_settings
from backend.memory.storage import MemoryStorage

router = APIRouter(prefix="/memories", tags=["memories"])
settings = get_settings()

def get_storage():
    from backend.api.chat import memory_storage
    return memory_storage

class MemoryPatchRequest(BaseModel):
    text: str

class MemoryResponse(BaseModel):
    id: str
    text: str
    created_at: str
    updated_at: str
    source_conversation_id: Optional[str] = None
    deleted: int = 0

@router.get("", response_model=List[MemoryResponse])
async def list_memories():
    return get_storage().get_memories(include_deleted=False)

@router.patch("/{memory_id}", response_model=MemoryResponse)
@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory_endpoint(memory_id: str, req: MemoryPatchRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Memory text cannot be empty")
    updated = get_storage().update_memory(memory_id, req.text)
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found")
    return updated

@router.delete("/{memory_id}")
async def delete_memory_endpoint(memory_id: str):
    success = get_storage().delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "id": memory_id}

@router.post("/clear")
async def clear_all_memories_endpoint():
    count = get_storage().clear_all()
    return {"status": "cleared", "deleted_count": count}

@router.post("/reindex")
async def reindex_memories_endpoint():
    count = get_storage().reindex_memories()
    return {"status": "reindexed", "count": count}
