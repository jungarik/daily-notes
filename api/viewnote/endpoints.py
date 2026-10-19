"""Viewnote router — the View note page's data.

Three reads: the note the page opens, and the two rosters its path wheels offer
(the root folders, and the sub-folders under one root). There are no writes:
the page cannot save yet.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

import i18n
from api.deps import current_user
from api.viewnote import db, helper
from api.viewnote.schemas import (
    ChildrenPayload,
    RootsPayload,
    ViewableNote,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/viewnote", tags=["viewnote"])


@router.get("/roots", response_model=RootsPayload)
def list_roots(user_id: int = Depends(current_user)) -> RootsPayload:
    """The root folders the viewer's root wheel offers, plus the default.

    **Declared before `/{note_id}`, and that is load-bearing.** FastAPI matches
    routes in declaration order, so with this second, `GET /api/viewnote/roots`
    would try `{note_id}` first and answer 422 for a perfectly good URL — a
    broken feature with a correct handler behind it. The same holds for
    `/children` below.

    The roots are the fixed vault roots, empty ones included, so there is no
    per-note read here at all: the endpoint only resolves the locale.
    `default_root` is where a note with no chosen path goes
    (`config.DEFAULT_ROOT_FOLDER_KEY`, localised).
    """
    locale = i18n.resolve_locale(db.get_language(user_id))

    return RootsPayload(
        roots=helper.root_labels(locale),
        default_root=helper.default_root(locale),
    )


@router.get("/children", response_model=ChildrenPayload)
def list_children(root: str = Query(min_length=1, max_length=200),
                  user_id: int = Depends(current_user)) -> ChildrenPayload:
    """The second-level folders already in use under one root.

    Owner-scoped and filtered in SQL, so choosing a root costs a read of that
    root's notes rather than the whole vault. `root` is matched as given — a
    root left behind by a language switch is still a root with children, and
    validating it against today's roster would hide them.
    """
    return ChildrenPayload(children=db.list_children(user_id, root.strip()))


@router.get("/{note_id}", response_model=ViewableNote)
def get_note(note_id: int, user_id: int = Depends(current_user)) -> ViewableNote:
    """The note being viewed, owner-scoped.

    404 covers both "no such note" and "not yours": a caller who does not own
    it learns nothing about whether it exists, and the ownership predicate is in
    the SQL rather than a check after the fact.

    The endpoint is the impure boundary: it resolves the caller, performs the
    reads, and signs the attachment URLs (which reads the clock and a secret).
    The ownership check is the first read's `WHERE`, and the follow-up reads
    happen only once it has passed — so an id that is not the caller's is never
    used to query links or attachments at all.

    The response is built here rather than through a mapper. `text` and `path`
    feed *controlled* React inputs, where `null` means uncontrolled, and `tags`
    is a nullable jsonb the client renders with `.map`, which throws on `null` —
    so an absent value becomes the empty string or the empty list, which is what
    "not filed yet" and "no tags" actually are. Pydantic ignores the row's other
    columns and copies the lists, so nothing is smuggled into the payload.
    """
    row = db.note_for_user(user_id, note_id)

    if row is None:
        raise HTTPException(status_code=404, detail="note not found")

    return ViewableNote(
        id=row["id"],
        text=row["text"] or "",
        path=row["path"] or "",
        tags=row["tags"] or [],
        attachments=helper.attachment_views(db.attachments(note_id)),
        linked_note_ids=db.linked_note_ids(user_id, note_id),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        timezone=db.get_timezone(user_id),
    )
