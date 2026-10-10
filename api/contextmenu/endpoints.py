"""Contextmenu router — the ⋮ menu's actions: change a note's path, rename a
folder, delete a note."""

from fastapi import APIRouter, Depends, HTTPException, Query

import i18n
from api.deps import current_user
from api.contextmenu import db, helper
from api.contextmenu.schemas import (
    SetPathRequest,
    NoteMeta,
    MoveFolderRequest,
    MoveFolderResponse,
    RootsPayload,
    ChildrenPayload,
)

router = APIRouter(prefix="/api/contextmenu", tags=["contextmenu"])


@router.get("/roots", response_model=RootsPayload)
def list_roots(user_id: int = Depends(current_user)) -> RootsPayload:
    """The root folders the change-path sheet's root selector offers.

    The fixed vault roots, empty ones included — an empty root is exactly where
    a note gets moved — so there is no per-note read: the endpoint only
    resolves the locale, and `helper.root_labels` maps it.
    """
    locale = i18n.resolve_locale(db.get_language(user_id))

    return RootsPayload(roots=helper.root_labels(locale))


@router.get("/children", response_model=ChildrenPayload)
def list_children(root: str = Query(min_length=1, max_length=200),
                  user_id: int = Depends(current_user)) -> ChildrenPayload:
    """The second-level folders already in use under one root.

    Owner-scoped and filtered in SQL, so choosing a root costs a read of that
    root's notes rather than the vault. `root` is matched as given — a root left
    behind by a language switch is still a root with children, and validating
    it against today's roster would hide them.
    """
    return ChildrenPayload(children=db.list_children(user_id, root.strip()))


@router.post("/notes/{note_id}/path", response_model=NoteMeta)
def set_path(note_id: int, req: SetPathRequest,
             user_id: int = Depends(current_user)) -> NoteMeta:
    """Move a note to a different vault path (owner-scoped, validated). The path
    must start with a root folder in any supported language (422 otherwise)."""
    status, meta = helper.move_note(user_id, note_id, req.path)
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    if status == "not_found":
        raise HTTPException(status_code=404, detail="note not found")
    return NoteMeta(**meta)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, user_id: int = Depends(current_user)) -> None:
    """Hard-delete a note and everything hanging off it.

    Chunks, attachments, links and reminders cascade; the attachment and voice
    objects are removed from the bucket, which does not. There is no undo and
    no soft-delete tombstone — the menu item says as much before it gets here.

    404 covers both "no such note" and "not yours": a caller who does not own it
    learns nothing about whether it exists.
    """
    if helper.delete_note(user_id, note_id) == "not_found":
        raise HTTPException(status_code=404, detail="note not found")


@router.post("/folder/move", response_model=MoveFolderResponse)
def move_folder(req: MoveFolderRequest,
                user_id: int = Depends(current_user)) -> MoveFolderResponse:
    """Bulk-rename a folder: move every note whose path is exactly `old_path`.
    Root folders can't be moved."""
    status, data = helper.move_folder(user_id, req.old_path, req.new_path)
    if status == "root":
        raise HTTPException(status_code=400, detail="root folders can't be moved")
    if status == "invalid":
        raise HTTPException(status_code=422, detail="path must start with a root folder")
    return MoveFolderResponse(count=data["count"], new_path=data["new_path"])
