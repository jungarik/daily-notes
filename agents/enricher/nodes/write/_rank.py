"""Idea-level ranking for link candidates.

Vector recall returns notes that are *about the same thing* — same words, same
topic, same folder. A Zettelkasten link is worth more when two notes share an
*idea*: a principle, mechanism, tension or mental model that carries across
both, even when the subject matter differs. This pass reorders the recalled
neighbours so those come first and names the shared idea for each one.

Not a graph node — a helper for the `link` node. It degrades to the retrieval
order (nearest neighbour first) whenever the model is unavailable or answers
with anything unusable, so linking never fails because ranking did.
"""

import json
import logging

import config
from agents.runtime import model_gateway

logger = logging.getLogger(__name__)

REASON_MAX_CHARS = 120

_SYSTEM_PROMPT = (
    "You connect notes in a personal Zettelkasten vault. Given a source note and "
    "candidate notes retrieved by semantic similarity, order the candidates by "
    "the IDEA they share with the source note — the principle, mechanism, "
    "tension, pattern or mental model that carries across both. A candidate that "
    "illuminates, contradicts, generalises or is generalised by the source note "
    "ranks highest, even when its subject matter is different. "
    "Rank DOWN candidates that merely repeat the same topic, keywords or folder "
    "without adding a connected thought — surface similarity is what retrieval "
    "already did, and it is not a reason to link. "
    "Set idea_link true only for candidates where you can name the shared idea "
    "concretely; if nothing genuinely connects, set it false for every candidate "
    "rather than inventing a connection. "
    "For each candidate write `reason`: the shared idea in a few words, not a "
    "summary of the candidate. "
    "Return every candidate id exactly once, best first, as JSON: "
    '{"ranked": [{"note_id": <int>, "reason": "<text>", "idea_link": <bool>}]}'
)


def _source_payload(note: dict) -> dict:
    return {
        "title": note.get("title"),
        "path": note.get("path"),
        "tags": note.get("tags") or [],
        "text": (note.get("text") or "")[:1500],
    }


def _candidate_payload(candidates: list[dict]) -> list[dict]:
    return [{
        "note_id": item["note_id"],
        "title": item.get("title"),
        "path": item.get("path"),
        "tags": item.get("tags") or [],
        "snippet": item.get("snippet") or "",
    } for item in candidates]


def _user_message(note: dict, candidates: list[dict], locale: str | None) -> str:
    payload = {
        "source_note": _source_payload(note),
        "candidates": _candidate_payload(candidates),
    }

    return (
        "Write every `reason` in the language with locale code "
        f"'{locale or 'en'}'.\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
    )


def _parse(content: str) -> list[dict]:
    data = json.loads(content or "{}")
    ranked = data.get("ranked")

    if not isinstance(ranked, list):
        raise ValueError("ranked is not a list")

    return ranked


def _clean_reason(value) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= REASON_MAX_CHARS:
        return text

    return text[:REASON_MAX_CHARS].rsplit(" ", 1)[0].strip() + "..."


def _apply(ranked: list[dict], candidates: list[dict]) -> list[dict]:
    """Order `candidates` by the model's ranking, dropping ids it invented and
    keeping ids it forgot (in retrieval order) at the end."""
    by_id = {item["note_id"]: item for item in candidates}
    ordered = []
    seen = set()

    for entry in ranked:
        if not isinstance(entry, dict):
            continue

        try:
            note_id = int(entry.get("note_id"))
        except (TypeError, ValueError):
            continue

        if note_id not in by_id or note_id in seen:
            continue

        seen.add(note_id)
        ordered.append({
            **by_id[note_id],
            "reason": _clean_reason(entry.get("reason")),
            "idea_link": bool(entry.get("idea_link")),
        })

    ordered.extend(item for item in candidates if item["note_id"] not in seen)

    return ordered


def rank(note: dict, candidates: list[dict], locale: str | None = None) -> list[dict]:
    """Return `candidates` ordered by the idea they share with `note`.

    Each ranked candidate gains a short `reason` and an `idea_link` flag. On any
    failure the input order (nearest neighbour first) is returned unchanged.
    """
    if not config.LINK_RANK_ENABLED or len(candidates) < 2:
        return candidates

    try:
        response = model_gateway.chat_completion(
            model=config.LINK_RANK_LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_message(note, candidates, locale)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        ranked = _parse(response.choices[0].message.content)
    except model_gateway.ModelGatewayError as exc:
        logger.warning("Link ranking unavailable (%s); using retrieval order",
                       exc.kind)

        return candidates
    except Exception:
        logger.exception("Link ranking failed; using retrieval order")

        return candidates

    logger.info("Link ranking ordered %s candidates for note %s",
                len(ranked), note.get("id"))

    return _apply(ranked, candidates)
