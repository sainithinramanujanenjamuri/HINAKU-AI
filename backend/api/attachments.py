"""
backend/api/attachments.py

FastAPI routes for file attachments:
- POST /api/conversations/{id}/attachments: Upload 1-5 files (base64 JSON payload)
- GET  /api/conversations/{id}/attachments: List attachments for conversation
- DELETE /api/conversations/{id}/attachments/{attachment_id}: Cascading hard deletion
"""

import base64
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.attachments import AttachmentManager, AttachmentValidationError

logger = logging.getLogger("hinaku.api.attachments")

router = APIRouter(prefix="/api/conversations", tags=["attachments"])

# Global shared attachment manager
attachment_manager = AttachmentManager()

class FileUploadPayload(BaseModel):
    filename: str
    content_base64: str
    mime_type: Optional[str] = None

class UploadAttachmentsRequest(BaseModel):
    files: List[FileUploadPayload]

@router.post("/{conversation_id}/attachments")
async def upload_attachments(
    conversation_id: str,
    req: UploadAttachmentsRequest
):
    if not req.files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided."
        )

    if len(req.files) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 5 files per message permitted."
        )

    saved_records = []
    errors = []

    for file_item in req.files:
        try:
            # Decode base64
            try:
                raw_b64 = file_item.content_base64
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                content = base64.b64decode(raw_b64)
            except Exception as e:
                raise AttachmentValidationError(f"Invalid base64 payload: {e}")

            record = attachment_manager.process_and_save_upload(
                conversation_id=conversation_id,
                filename=file_item.filename or "attachment",
                content_bytes=content,
                mime_type=file_item.mime_type
            )
            saved_records.append(record)
        except AttachmentValidationError as e:
            errors.append(f"{file_item.filename}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error uploading {file_item.filename}: {e}")
            errors.append(f"{file_item.filename}: Upload failed ({str(e)})")

    if errors and not saved_records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="; ".join(errors)
        )

    storage_usage = attachment_manager.get_total_storage_usage()

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "attachments": saved_records,
        "errors": errors if errors else None,
        "storage_usage": storage_usage
    }

@router.get("/{conversation_id}/attachments")
async def list_attachments(conversation_id: str):
    attachments = attachment_manager.list_attachments(conversation_id)
    usage = attachment_manager.get_total_storage_usage()
    return {
        "conversation_id": conversation_id,
        "attachments": attachments,
        "count": len(attachments),
        "storage_usage": usage
    }

@router.delete("/{conversation_id}/attachments/{attachment_id}")
async def delete_attachment(conversation_id: str, attachment_id: str):
    success = attachment_manager.delete_attachment(attachment_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attachment {attachment_id} not found."
        )
    return {
        "status": "deleted",
        "conversation_id": conversation_id,
        "attachment_id": attachment_id
    }
