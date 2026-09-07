"""link_context node: gather selectable link candidates before a link_notes write.

Retrieval (embeddings + nearest-neighbour lookup) and the idea-level ranking
pass that reorders its results live here, out of the stage/validate nodes —
mirroring how enrich_note gathers classify context first.
The proposal (or an error) is stashed for the downstream node. Single public
`run`.
"""

import config
import i18n
from agents.enrich.nodes.write import _rank
from agents.enrich.state import context_from_state
from common import embedings
from tools.enrich import db


def _link_candidates(user_id: int,
                     note: dict,
                     preselect_ids: list[int],
                     locale: str | None = None) -> tuple:
    """Return (candidates, preselected_ids) for a link proposal.

    Retrieval recalls the source note's nearest semantic neighbours; `_rank`
    then reorders them by the idea each one shares with the source note, so
    conceptual links are offered before merely same-topic notes. Preselected
    ids are the caller's explicit targets when given, otherwise the ranked
    idea-level matches (falling back to the distance threshold when ranking
    produced nothing).
    """
    text = (note.get("text") or note.get("title") or "").strip()
    rows = []

    if text:
        rows = db.link_candidates(
            user_id,
            embedings.embed(text),
            note["id"],
            config.LINK_RECALL_LIMIT,
        )

    ranked = _rank.rank(note, rows, locale)[:config.ENRICH_SIMILAR_LIMIT]
    candidates = [{
        "note_id": row["note_id"],
        "title": row["title"],
        "path": row.get("path"),
        "tags": row.get("tags") or [],
        "distance": row.get("distance"),
        "reason": row.get("reason") or "",
    } for row in ranked]
    by_id = {item["note_id"] for item in candidates}

    owned = db.owned_note_ids(user_id, preselect_ids) if preselect_ids else set()
    owned_preselect = [note_id for note_id in preselect_ids if note_id in owned]

    for note_id in owned_preselect:
        if note_id not in by_id:
            meta = db.get_note_for_user(user_id, note_id)

            if meta:
                candidates.append({
                    "note_id": note_id,
                    "title": meta.get("title") or "note",
                    "path": meta.get("path"),
                    "tags": meta.get("tags") or [],
                    "distance": None,
                    "reason": "",
                })
                by_id.add(note_id)

    if owned_preselect:
        preselected = owned_preselect
    elif any("idea_link" in row for row in ranked):
        # Ranking ran: trust its verdict, including "nothing genuinely connects".
        preselected = [row["note_id"] for row in ranked
                       if row.get("idea_link")][:config.LINK_PRESELECT_LIMIT]
    else:
        preselected = [
            item["note_id"]
            for item in candidates
            if item["distance"] is not None
            and item["distance"] <= config.ENRICH_SIMILAR_MAX_DISTANCE
        ]

    return candidates, preselected


def _link_action(user_id: int, call: dict, locale: str | None = None) -> dict:
    """Validate a link_notes call and enrich its args with pickable candidates.

    Returns either an action dict (kind='select') or a tool error message dict.
    """
    args = dict(call.get("args") or {})

    try:
        note_id = int(args.get("note_id"))
    except (TypeError, ValueError):
        note_id = None

    note = db.get_note_for_user(user_id, note_id) if note_id is not None else None

    if note is None:
        return {"error": "Error: choose a valid user-owned source note id."}

    preselect_ids = []

    for value in args.get("linked_note_ids") or []:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            continue

        if candidate != note_id and candidate not in preselect_ids:
            preselect_ids.append(candidate)

    candidates, preselected = _link_candidates(
        user_id,
        note,
        preselect_ids,
        locale,
    )

    if not candidates:
        return {"error": "Error: no related notes were found to link."}

    args["note_id"] = note_id
    args["candidates"] = candidates
    args["linked_note_ids"] = preselected

    return {
        "name": "link_notes",
        "args": args,
        "summary": i18n.t(locale, "action_link_notes", id=note_id),
        "kind": "select",
    }


def run(state) -> dict:
    ctx = context_from_state(state)
    proposal = _link_action(ctx.user_id, state["tool_call"], ctx.locale)

    return {"link_proposal": proposal}
