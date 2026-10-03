"""Addnote router — the Add note page's data and its saves.

Four methods: the path roster the wheel offers, the note a tapped Edit opens,
and the two writes — `POST` for a note written from scratch, `PUT` for one
being edited. Both writes rebuild the note's embedded chunks, because the text
they store is what search and RAG are supposed to match on.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

import i18n
from api.deps import current_user
from api.addnote import db, helper
from common import embedings
from api.addnote.schemas import EditableNote, PathsPayload, SaveNoteRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/addnote", tags=["addnote"])


@router.get("/paths", response_model=PathsPayload)
def list_paths(user_id: int = Depends(current_user)) -> PathsPayload:
    """The paths the editor's path wheel offers, plus the default destination.

    **Declared before `/{note_id}`, and that is load-bearing.** FastAPI matches
    routes in declaration order, so with this second, `GET /api/addnote/paths`
    would try `{note_id}` first and answer 422 for a perfectly good URL —
    a broken feature with a correct handler behind it.

    Duplicated from `api/contextmenu` rather than imported: a section owns its
    reads, so the editor's picker cannot break because the ⋮ menu's changed.
    The endpoint is the impure boundary — it resolves the locale and reads the
    rows; `helper.known_paths` only maps them.

    `default_root` is where a note with no chosen path goes
    (`config.DEFAULT_ROOT_FOLDER_KEY`, localised). The page shows it rather
    than leaving an empty control that will quietly file the note somewhere.
    """
    locale = i18n.resolve_locale(db.get_language(user_id))

    return PathsPayload(
        paths=helper.known_paths(helper.root_labels(locale), db.list_paths(user_id)),
        default_root=helper.default_root(locale),
    )


@router.get("/{note_id}", response_model=EditableNote)
def get_note(note_id: int, user_id: int = Depends(current_user)) -> EditableNote:
    """The note being edited, owner-scoped.

    404 covers both "no such note" and "not yours": a caller who does not own
    it learns nothing about whether it exists. Same reasoning as the section's
    delete, and the ownership predicate is in the SQL rather than a check after
    the fact.

    The endpoint is the impure boundary: it resolves the caller, performs the
    reads, and signs the attachment URLs (which reads the clock and a secret).
    The ownership check is the first read's `WHERE`, and the two follow-up
    reads happen only once it has passed — so an id that is not the caller's is
    never used to query links or attachments at all.

    The response is built here rather than through a mapper. Three of the
    row's columns are nullable where the client needs a value: `text` and
    `path` feed *controlled* React inputs, where `null` means uncontrolled —
    React warns and the field stops tracking its own state — and `tags` is a
    nullable jsonb the client renders with `.map`, which throws on `null`. So
    an absent value becomes the empty string or the empty list, which is what
    "not filed yet" and "no tags" actually are. That is three `or` expressions
    at the one place that already owns the reads; a mapper for it would be a
    name to read past. Pydantic ignores the row's other columns and copies the
    lists, so nothing is smuggled into the payload and nothing the caller still
    holds can change it afterwards.
    """
    row = db.note_for_user(user_id, note_id)

    if row is None:
        raise HTTPException(status_code=404, detail="note not found")

    return EditableNote(
        id=row["id"],
        text=row["text"] or "",
        path=row["path"] or "",
        tags=row["tags"] or [],
        attachments=helper.attachment_views(db.attachments(note_id)),
        linked_note_ids=db.linked_note_ids(user_id, note_id),
    )


def _saved(user_id: int, note_id: int) -> EditableNote:
    """The note as the editor should now see it.

    A save answers with the same shape the page opened with, read back from
    the database rather than echoed from the request: the path it sends is not
    the path that was stored (an empty one became the default root, a typed
    one was normalised), and a client that trusted its own input would show
    the wrong folder until the next open.
    """
    row = db.note_for_user(user_id, note_id)

    return EditableNote(
        id=row["id"],
        text=row["text"] or "",
        path=row["path"] or "",
        tags=row["tags"] or [],
        attachments=helper.attachment_views(db.attachments(note_id)),
        linked_note_ids=db.linked_note_ids(user_id, note_id),
    )


@router.post("", response_model=EditableNote, status_code=201)
def create_note(req: SaveNoteRequest,
                user_id: int = Depends(current_user)) -> EditableNote:
    """Save a note written on the Add note page.

    The sequence is spelled out here rather than hidden in a helper, because
    every step of it is I/O and the order between them is the correctness
    argument:

    * The row is written **before** the embedding round trip. The text is what
      the user asked to keep, so a failed embedding costs the note its
      searchability and not its content. It is logged and swallowed —
      answering with an error would tell them nothing saved when it did.
    * The chunks are **built before** `replace_chunks` touches the table, and
      that function deletes and re-inserts inside one `cursor()`. A note with
      no chunks is invisible to search and RAG.
    """
    locale = i18n.resolve_locale(db.get_language(user_id))
    path = helper.clean_root_path(req.path, locale)

    if path is None:
        raise HTTPException(status_code=422, detail="path must start with a root folder")

    text = req.text.strip()
    note_id = db.create_note(user_id, text, path, helper.clean_tags(req.tags))

    try:
        chunks = embedings.build_chunks(text)
    except Exception:
        logger.exception("Embedding failed for new note %s; it saved without chunks",
                         note_id)
    else:
        db.replace_chunks(note_id, chunks)
        logger.info("Stored %d chunk(s) for new note %s", len(chunks), note_id)

    return _saved(user_id, note_id)


@router.put("/{note_id}", response_model=EditableNote)
def save_note(note_id: int, req: SaveNoteRequest,
              user_id: int = Depends(current_user)) -> EditableNote:
    """Save an edited note.

    Same sequence as create, spelled out again rather than shared: the two
    differ in more than they share — one inserts and answers 201, the other
    updates and can 404 — and `note_chunks` is what search matches on, so an
    edit that skipped the rebuild would leave the note findable only by its
    old wording. A failed embedding leaves the previous chunks in place, which
    is the better of the two wrong states.

    The update touches only the three fields the editor owns — `title`,
    `note_type` and `priority` are enrichment's, and `note_links` is nobody's
    business here: the page shows a
    note's neighbours and offers no way to change them, so a save must not
    rewrite that graph.

    404 for a note that is not the caller's, like every other read and write
    in this section.
    """
    locale = i18n.resolve_locale(db.get_language(user_id))
    path = helper.clean_root_path(req.path, locale)

    if path is None:
        raise HTTPException(status_code=422, detail="path must start with a root folder")

    text = req.text.strip()

    if not db.update_note(user_id, note_id, text, path, helper.clean_tags(req.tags)):
        raise HTTPException(status_code=404, detail="note not found")

    try:
        chunks = embedings.build_chunks(text)
    except Exception:
        logger.exception("Embedding failed for note %s; its chunks still match "
                         "the previous text", note_id)
    else:
        db.replace_chunks(note_id, chunks)
        logger.info("Rebuilt %d chunk(s) for note %s", len(chunks), note_id)

    return _saved(user_id, note_id)
