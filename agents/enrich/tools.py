"""Enrichment-agent tool registry.

Read tools let the agent gather the vocabulary/context it needs to classify a
note consistently (existing paths, existing tags, similar past notes); the
terminal `submit_metadata` tool is how the agent emits its final structured
answer. Handlers wrap existing services/stores — no duplicated logic. Validation
of the submitted metadata reuses the one-shot enricher's guardrails.
"""

import json
import logging

import config
from services import semantic
from services import enrichment as enrichment_svc
from stores import note_store
from stores import chunk_store

logger = logging.getLogger(__name__)


class Ctx:
    """Per-run context for enriching one note. Carries the note (id + text), the
    user's language and root-folder vocabulary, and collects the final metadata
    once `submit_metadata` is called."""

    def __init__(self, user_id, note_id, text, locale, root_folders, default_root):
        self.user_id = user_id
        self.note_id = note_id
        self.text = text
        self.locale = locale
        self.root_folders = root_folders
        self.default_root = default_root
        self.result = None            # set by submit_metadata


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ---- read tools -----------------------------------------------------------

def _list_paths(ctx: Ctx, args: dict) -> str:
    rows = note_store.list_paths(ctx.user_id)
    return _json([{"path": p, "count": c} for p, c in rows]) if rows else "No existing paths."


def _list_tags(ctx: Ctx, args: dict) -> str:
    rows = note_store.list_tags(ctx.user_id)
    return _json([{"tag": t, "count": c} for t, c in rows]) if rows else "No existing tags."


def _find_similar(ctx: Ctx, args: dict) -> str:
    emb = semantic.embed(ctx.text)
    sim = chunk_store.similar_notes(
        ctx.user_id, emb, exclude_note_id=ctx.note_id, limit=config.ENRICH_SIMILAR_LIMIT)
    out = [{"title": n["title"], "path": n.get("path"), "tags": n.get("tags") or [],
            "type": n["note_type"], "distance": n.get("distance")} for n in sim]
    return _json(out) if out else "No similar notes."


# ---- terminal tool --------------------------------------------------------

def _submit_metadata(ctx: Ctx, args: dict) -> str:
    """Record the final classification (normalized + guardrailed) and end the run."""
    ctx.result = enrichment_svc._normalize(
        args, ctx.text, ctx.root_folders, ctx.default_root)
    return "Metadata recorded."


HANDLERS = {
    "list_paths": _list_paths,
    "list_tags": _list_tags,
    "find_similar": _find_similar,
    "submit_metadata": _submit_metadata,
}

TERMINAL_TOOL = "submit_metadata"


def execute_tool(ctx: Ctx, name: str, args: dict) -> str:
    fn = HANDLERS.get(name)
    if not fn:
        return "Error: unknown tool %s." % name
    logger.info("enrich tool %s note=%s args=%s", name, ctx.note_id, args if name == TERMINAL_TOOL else "")
    try:
        return fn(ctx, args or {})
    except Exception as exc:
        logger.exception("enrich tool %s failed", name)
        return "Error running %s: %s" % (name, exc)


def _fn(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


TOOL_SPECS = [
    _fn("list_paths", "List the user's existing vault folder paths (with note counts) "
        "so you can reuse one instead of inventing a parallel path.", {}, []),
    _fn("list_tags", "List the user's existing tags (with counts) so you can reuse them.", {}, []),
    _fn("find_similar", "List notes most similar to this one and how they were "
        "classified (type/path/tags), for a consistent decision.", {}, []),
    _fn("submit_metadata",
        "Submit the FINAL classification for this note. Call this exactly once when "
        "you've decided. The path must start with one of the root folders.",
        {
            "type": {"type": "string", "enum": list(enrichment_svc.TYPES)},
            "title": {"type": "string", "description": "Concise summary, ≤8 words, in the note's language."},
            "path": {"type": "string", "description": "root folder + optional sub-folder (two levels max)."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "0–5 lowercase keywords."},
            "priority": {"type": "string", "enum": list(enrichment_svc.PRIORITIES)},
        },
        ["type", "title", "path"]),
]
