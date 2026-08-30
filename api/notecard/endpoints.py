"""Notecard router — GET /api/notecard/attachments/{id}?t=<token>."""

from fastapi import APIRouter, HTTPException, Response

import config
from api.notecard import helper

router = APIRouter(prefix="/api/notecard", tags=["notecard"])


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: int, t: str = "") -> Response:
    """Proxy an attachment's bytes from object storage. Auth is the signed `t`
    token (an <img> can't send headers), so this endpoint is not user-guarded.
    The API reaches the bucket even when the browser can't (private endpoint)."""
    status, payload = helper.fetch(attachment_id, t)
    if status == "forbidden":
        raise HTTPException(status_code=403, detail="bad or expired token")
    if status != "ok":
        raise HTTPException(status_code=404, detail="attachment not found")
    data, content_type, mime = payload
    return Response(
        content=data,
        media_type=content_type or mime or "application/octet-stream",
        headers={"Cache-Control": f"private, max-age={config.ATTACHMENT_URL_TTL_SECONDS}"},
    )
