"""
Note lifecycle domain service: capture and on-demand enrichment.

Client-agnostic — used by the Telegram bot today and the public API later. No
client (Telegram) specifics leak in here; callers pass a resolved user_id.
Reminder detection/creation lives in `reminders`; search in `search_service`.
"""

import logging

import config
from services import semantic
from services import atomize
from services import polish as polish_svc
import storage
from services import enrichment
import i18n
from services import user_service
from stores import note_store
from stores import chunk_store
from stores import link_store
from stores import attachment_store

logger = logging.getLogger(__name__)


def _localized_roots(locale: str) -> tuple[dict[str, str], str]:
    """Root folders for a locale: {translated folder name -> English definition},
    plus the translated default folder name. The translated name is what the LLM
    writes into the path and what gets stored."""
    roots = {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


def _all_root_names() -> set[str]:
    """Every root-folder display name across all supported locales — used to
    validate a path regardless of the language it was written in."""
    return {i18n.t(loc, key) for key in config.ROOT_FOLDERS for loc in i18n.SUPPORTED}


def capture_note(
    user_id: int,
    text: str,
    source_type: str = "text",
    audio_bytes: bytes | None = None,
    mime: str | None = None,
    images: list[dict] | None = None,
) -> int:
    """Persist a note (upload audio/images if any, chunk + embed). Returns the
    note id.

    The sender's username is stored on the user, not the note, so it isn't passed
    here. `images` is an optional list of {bytes, mime, ext} — each is uploaded to
    object storage and recorded as a note attachment in order. Enrichment and
    search only ever use `text`, so image-only notes still capture (with empty
    text); attachments are purely for display.
    """
    audio_key = None
    if audio_bytes is not None:
        audio_key = storage.upload_audio(audio_bytes, content_type=mime or "audio/ogg")

    chunks = semantic.build_chunks(text)
    note_id = note_store.save_note(
        user_id, text,
        source_type=source_type, audio_key=audio_key, audio_mime=mime,
    )
    chunk_store.save_chunks(note_id, chunks)
    n_attached = _attach_images(note_id, images or [])
    logger.info(
        "Captured note %s (user %s, %s, %d chunk(s), %d image(s))",
        note_id, user_id, source_type, len(chunks), n_attached,
    )
    return note_id


def _attach_images(note_id: int, images: list[dict]) -> int:
    """Upload each image to object storage and record it as an attachment (in the
    given order). Skips any that fail to upload (storage off / error) so the note
    itself is never lost. Returns how many attachments were stored."""
    stored = 0
    for pos, img in enumerate(images):
        data = img.get("bytes")
        if not data:
            continue
        key = storage.upload_attachment(
            data, kind="image",
            content_type=img.get("mime") or "application/octet-stream",
            ext=img.get("ext") or "bin",
        )
        if not key:
            logger.warning("Skipped image %d for note %s (storage unavailable)", pos, note_id)
            continue
        attachment_store.add_attachment(
            note_id, key, kind="image",
            mime=img.get("mime"), size_bytes=len(data), position=pos,
        )
        stored += 1
    return stored


def _attachment_views(rows: list[dict]) -> list[dict]:
    """Client-facing attachment metadata: [{id, kind, mime}]. The storage key
    stays server-side; the API layer turns each id into a signed proxy URL (an
    <img> can't send auth headers, so the browser loads bytes through the API)."""
    return [{"id": a["id"], "kind": a["kind"], "mime": a["mime"]} for a in rows]


def atomize_note(user_id: int, note_id: int) -> list[dict]:
    """Split a note into atomic notes, persisting each as a new (plain) note.

    Returns [{note_id, text}] for the created atoms, or [] when the note is
    already a single idea (nothing is created). Atoms are plain notes — no
    metadata, no links — so each can be enriched, atomized again, or cancelled
    independently.
    """
    text = note_store.get_text(note_id)
    if not text:
        logger.warning("atomize_note: note %s not found", note_id)
        return []
    atoms = atomize.split(text)
    if len(atoms) < 2:
        logger.info("Note %s is already atomic; nothing split", note_id)
        return []
    created = [{"note_id": capture_note(user_id, atom), "text": atom} for atom in atoms]
    logger.info("Atomized note %s into %d note(s)", note_id, len(created))
    return created


def polish_note(note_id: int) -> str | None:
    """Clean up a note's wording/punctuation via the LLM (no invention). When the
    text actually changes, persist it and rebuild the note's chunks so semantic
    search reflects the corrected text. Returns the (possibly unchanged) text, or
    None if the note doesn't exist."""
    text = note_store.get_text(note_id)
    if not text:
        logger.warning("polish_note: note %s not found", note_id)
        return None
    cleaned = polish_svc.polish(text)
    if cleaned != text:
        note_store.set_text(note_id, cleaned)
        chunk_store.delete_chunks(note_id)
        chunk_store.save_chunks(note_id, semantic.build_chunks(cleaned))
        logger.info("Polished note %s (re-embedded)", note_id)
    else:
        logger.info("Polish left note %s unchanged", note_id)
    return cleaned


def delete_bare_note(note_id: int) -> bool:
    """Delete a note only if it has no metadata and no links (guarded, to protect
    enriched/linked notes from an accidental Cancel). Returns True if deleted."""
    deleted = note_store.delete_if_bare(note_id)
    logger.info(
        "Delete note %s: %s", note_id,
        "deleted" if deleted else "blocked (has metadata, links, or an active reminder)",
    )
    return deleted


def enrich_note(user_id: int, note_id: int) -> dict | None:
    """Run the deferred enrichment pass and persist the metadata. Returns the
    metadata dict, or None if the note no longer exists."""
    text = note_store.get_text(note_id)
    if not text:
        logger.warning("enrich_note: note %s not found", note_id)
        return None

    embedding = semantic.embed(text)
    similar = chunk_store.similar_notes(
        user_id, embedding, exclude_note_id=note_id,
        limit=config.ENRICH_SIMILAR_LIMIT,
    )
    # Present the root folders in the user's language; the model writes the
    # translated folder name into the path and it's stored as-is.
    root_folders, default_root = _localized_roots(user_service.language(user_id))
    meta = enrichment.enrich(
        text,
        known_paths=note_store.list_paths(user_id),
        known_tags=note_store.list_tags(user_id),
        similar_notes=similar,
        root_folders=root_folders,
        default_root_folder=default_root,
    )
    note_store.set_metadata(
        note_id, meta["type"], meta["title"], meta["priority"],
        meta["tags"], meta["path"],
    )
    logger.info("Enriched note %s -> %s '%s'", note_id, meta["type"], meta["title"])
    return meta


def _display_title(title: str | None, text: str | None, limit: int = 60) -> str:
    """A note's browser label: its enriched title, else a trimmed text snippet."""
    t = (title or "").strip()
    if t:
        return t
    snippet = " ".join((text or "").split())
    if not snippet:
        return "untitled"
    return snippet[:limit] + "…" if len(snippet) > limit else snippet


def list_notes_for_user(user_id: int) -> list[dict]:
    """The user's notes for the web-app browser/feed (newest first): [{id, title,
    path, snippet, created_at, links}]. `title` falls back to a text snippet when
    the note isn't enriched; `snippet` is a short text preview for the feed."""
    out = []
    for n in note_store.list_notes(user_id):
        created = n.get("created_at")
        out.append({
            "id": n["id"],
            "title": _display_title(n["title"], n["text"]),
            "path": n["path"],
            "snippet": " ".join((n["text"] or "").split())[:160],
            "created_at": created.isoformat() if created else None,
            "links": n["links"],
        })
    return out


def feed_for_user(user_id: int) -> list[dict]:
    """Full note details for the web-app feed (newest first) — the same shape as a
    single note preview, so each note renders as a complete card. Links/backlinks
    are computed from one edge query (no per-note round trips)."""
    notes = note_store.list_notes(user_id)
    edges = link_store.all_links(user_id)
    ids = {i for e in edges for i in e}
    briefs = {b["id"]: b for b in note_store.notes_brief(user_id, ids)}
    # One query for every note's attachments (no per-note round trip).
    attachments = attachment_store.for_notes([n["id"] for n in notes])
    out_map: dict[int, list[int]] = {}
    in_map: dict[int, list[int]] = {}
    for f, t in edges:
        out_map.setdefault(f, []).append(t)
        in_map.setdefault(t, []).append(f)

    def chip(nid: int) -> dict:
        b = briefs.get(nid)
        return {"id": nid, "title": _display_title(b["title"], b["text"]) if b else str(nid)}

    feed = []
    for n in notes:
        created = n.get("created_at")
        feed.append({
            "id": n["id"],
            "title": _display_title(n["title"], n["text"]),
            "path": n["path"],
            "text": n["text"] or "",
            "tags": n.get("tags") or [],
            "type": n.get("type"),
            "created_at": created.isoformat() if created else None,
            "links": [chip(t) for t in out_map.get(n["id"], [])],
            "backlinks": [chip(f) for f in in_map.get(n["id"], [])],
            "attachments": _attachment_views(attachments.get(n["id"], [])),
        })
    return feed


def web_note_detail(user_id: int, note_id: int) -> dict | None:
    """Full note detail for the web-app preview, scoped to its owner. Returns None
    if the note doesn't exist or isn't the user's."""
    n = note_store.get_note_for_user(user_id, note_id)
    if n is None:
        return None
    created = n.get("created_at")

    # Direct neighbours only (depth 1) — a single non-recursive query. The client
    # navigates one hop per tap, so graph cycles never cause recursion here.
    links, backlinks = [], []
    for _id, title, text, direction in link_store.links_of_for_user(user_id, note_id):
        (links if direction == "out" else backlinks).append(
            {"id": _id, "title": _display_title(title, text)}
        )

    return {
        "id": n["id"],
        "title": _display_title(n["title"], n["text"]),
        "path": n["path"],
        "text": n["text"] or "",
        "tags": n["tags"] or [],
        "type": n["type"],
        "created_at": created.isoformat() if created else None,
        "links": links,
        "backlinks": backlinks,
        "attachments": _attachment_views(attachment_store.list_for_note(note_id)),
    }


def graph(user_id: int) -> dict:
    """The user's connection map: {nodes:[{id,title,path,degree}], edges:[{source,target}]}.

    Only notes that participate in a link appear. Direction is preserved in the
    edges (the client can render it undirected for now, directed later)."""
    edges = link_store.all_links(user_id)
    ids = {i for e in edges for i in e}
    briefs = {b["id"]: b for b in note_store.notes_brief(user_id, ids)}

    degree: dict[int, int] = {}
    for f, t in edges:
        degree[f] = degree.get(f, 0) + 1
        degree[t] = degree.get(t, 0) + 1

    nodes = [
        {"id": nid, "title": _display_title(b["title"], b["text"]),
         "path": b["path"], "degree": degree.get(nid, 0)}
        for nid, b in briefs.items()
    ]
    out_edges = [
        {"source": f, "target": t}
        for f, t in edges if f in briefs and t in briefs
    ]
    return {"nodes": nodes, "edges": out_edges}


def known_paths(user_id: int) -> list[str]:
    """The path vocabulary offered to the user: their existing DB paths (most-used
    first), then the localized root folders not already present."""
    root_folders, _ = _localized_roots(user_service.language(user_id))
    paths = [name for name, _ in note_store.list_paths(user_id)]
    for name in root_folders:
        if name not in paths:
            paths.append(name)
    return paths


def clean_root_path(path: str) -> str | None:
    """Normalize a user-entered path and require it to start with a root folder
    (in any supported language). Returns the canonical path, or None if empty or
    not under a known root folder."""
    if not path:
        return None
    parts = [p.strip() for p in str(path).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    if not parts:
        return None
    roots = {name.lower(): name for name in _all_root_names()}
    canonical = roots.get(parts[0].lower())
    if canonical is None:
        return None
    return "/".join([canonical] + parts[1:])


def set_path(note_id: int, path: str) -> dict | None:
    """Move a note to a different vault path. Returns the note's updated metadata,
    or None if the note doesn't exist."""
    if note_store.get_text(note_id) is None:
        logger.warning("set_path: note %s not found", note_id)
        return None
    note_store.set_path(note_id, path)
    logger.info("Note %s path set to %r", note_id, path)
    return note_store.get_meta(note_id)


def move_note(user_id: int, note_id: int, raw_path: str) -> tuple[str, dict | None]:
    """Owner-scoped: validate + set a single note's full path. Returns
    (status, meta): ('ok', meta) | ('invalid', None) | ('not_found', None)."""
    cleaned = clean_root_path(raw_path)
    if cleaned is None:
        return ("invalid", None)
    if note_store.get_note_for_user(user_id, note_id) is None:
        return ("not_found", None)
    note_store.set_path(note_id, cleaned)
    logger.info("Note %s (user %s) path set to %r", note_id, user_id, cleaned)
    return ("ok", note_store.get_meta(note_id))


def move_folder(user_id: int, old_path: str, raw_new_path: str) -> tuple[str, dict | None]:
    """Owner-scoped bulk rename of a sub-folder: move every note whose path is
    exactly `old_path` to a validated new path. Root folders can't be moved.
    Returns (status, data): ('ok', {count, new_path}) | ('invalid', None) | ('root', None)."""
    if "/" not in (old_path or ""):
        return ("root", None)   # a bare root folder — not movable
    cleaned = clean_root_path(raw_new_path)
    if cleaned is None:
        return ("invalid", None)
    count = note_store.move_folder_paths(user_id, old_path, cleaned)
    logger.info("Moved folder %r -> %r for user %s (%d notes)", old_path, cleaned, user_id, count)
    return ("ok", {"count": count, "new_path": cleaned})
