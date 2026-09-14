"""link_context node: gather selectable link candidates before a link_notes write.

Retrieval (embeddings + nearest-neighbour lookup) and the idea-level ranking
pass that reorders its results live here, out of the stage/validate nodes —
mirroring how enrich_note gathers classify context first. `run` performs every
lookup and hands plain rows to the pure builders below; the proposal (or an
error) is stashed for the downstream node. Single public `run`.
"""

import config
import i18n
from agents.enrich.nodes.write import _rank
from agents.enrich.state import context_from_state
from common import embedings
from tools.enrich import db

_BAD_SOURCE = "Error: choose a valid user-owned source note id."
_NO_CANDIDATES = "Error: no related notes were found to link."


def _target_note_id(args: dict) -> int | None:
    try:
        return int(args.get("note_id"))
    except (TypeError, ValueError):
        return None


def _preselect_ids(args: dict, note_id: int) -> list[int]:
    """The caller's explicit link targets, de-duplicated and self-link free."""
    preselect_ids = []

    for value in args.get("linked_note_ids") or []:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue

        if candidate != note_id and candidate not in preselect_ids:
            preselect_ids.append(candidate)

    return preselect_ids


def _source_text(note: dict) -> str:
    return (note.get("text") or note.get("title") or "").strip()


def _ranked_candidate(row: dict) -> dict:
    return {
        "note_id": row["note_id"],
        "title": row["title"],
        "path": row.get("path"),
        "tags": row.get("tags") or [],
        "distance": row.get("distance"),
        "reason": row.get("reason") or "",
    }


def _explicit_candidate(note_id: int, note: dict) -> dict:
    return {
        "note_id": note_id,
        "title": note.get("title") or "note",
        "path": note.get("path"),
        "tags": note.get("tags") or [],
        "distance": None,
        "reason": "",
    }


def _candidates(ranked: list[dict], explicit: list[tuple]) -> list[dict]:
    """Ranked neighbours first, then any explicitly requested note not among them."""
    return [
        *[_ranked_candidate(row) for row in ranked],
        *[_explicit_candidate(note_id, note) for note_id, note in explicit if note],
    ]


def _preselected(ranked: list[dict],
                 candidates: list[dict],
                 owned_preselect: list[int]) -> list[int]:
    """Explicit targets win; else the ranker's idea-level verdict; else distance."""
    if owned_preselect:
        return owned_preselect

    if any("idea_link" in row for row in ranked):
        # Ranking ran: trust its verdict, including "nothing genuinely connects".
        return [row["note_id"] for row in ranked
                if row.get("idea_link")][:config.LINK_PRESELECT_LIMIT]

    return [
        item["note_id"]
        for item in candidates
        if item["distance"] is not None
        and item["distance"] <= config.ENRICH_SIMILAR_MAX_DISTANCE
    ]


def _proposal(note_id: int,
              args: dict,
              candidates: list[dict],
              preselected: list[int],
              locale: str | None) -> dict:
    return {
        "name": "link_notes",
        "args": {
            **args,
            "note_id": note_id,
            "candidates": candidates,
            "linked_note_ids": preselected,
        },
        "summary": i18n.t(locale, "action_link_notes", id=note_id),
        "kind": "select",
    }


def run(state) -> dict:
    ctx = context_from_state(state)
    args = dict((state.get("tool_call") or {}).get("args") or {})
    note_id = _target_note_id(args)
    note = db.get_note_for_user(ctx.user_id, note_id) if note_id is not None else None

    if note is None:
        return {"link_proposal": {"error": _BAD_SOURCE}}

    preselect_ids = _preselect_ids(args, note_id)
    text = _source_text(note)
    rows = db.link_candidates(
        ctx.user_id,
        embedings.embed(text),
        note_id,
        config.LINK_RECALL_LIMIT,
    ) if text else []
    ranked = _rank.rank(note, rows, ctx.locale)[:config.ENRICH_SIMILAR_LIMIT]
    owned = db.owned_note_ids(ctx.user_id, preselect_ids) if preselect_ids else set()
    owned_preselect = [
        candidate_id for candidate_id in preselect_ids if candidate_id in owned
    ]
    ranked_ids = {row["note_id"] for row in ranked}
    explicit = [
        (explicit_id, db.get_note_for_user(ctx.user_id, explicit_id))
        for explicit_id in owned_preselect
        if explicit_id not in ranked_ids
    ]
    candidates = _candidates(ranked, explicit)

    if not candidates:
        return {"link_proposal": {"error": _NO_CANDIDATES}}

    return {
        "link_proposal": _proposal(
            note_id,
            args,
            candidates,
            _preselected(ranked, candidates, owned_preselect),
            ctx.locale,
        ),
    }
