"""
Note endpoints.

Currently: the user's known vault paths (controlled vocabulary) and moving a
note to a different path. Both go through `note_service`; the store is never
touched by a client directly.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

import config
from services import note_service
from api.deps import require_internal_token
from api.schemas import PathsResponse, SetPathRequest, NoteMeta

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/notes",
    tags=["notes"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/paths", response_model=PathsResponse)
def known_paths(user_id: int) -> PathsResponse:
    """The user's existing vault paths, most-used first."""
    return PathsResponse(paths=note_service.known_paths(user_id))


@router.post("/{note_id}/path", response_model=NoteMeta)
def set_path(note_id: int, req: SetPathRequest) -> NoteMeta:
    """Move a note to a different vault path; returns the note's updated metadata.

    The path must start with a root folder (422 otherwise); it's canonicalized
    before saving so casing matches config.ROOT_FOLDERS.
    """
    cleaned = note_service.clean_root_path(req.path)
    if cleaned is None:
        raise HTTPException(
            status_code=422,
            detail="Path must start with a root folder: " + ", ".join(config.ROOT_FOLDERS),
        )
    meta = note_service.set_path(note_id, cleaned)
    if meta is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)
