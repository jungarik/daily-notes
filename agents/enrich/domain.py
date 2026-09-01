"""Domain logic for the enrichment/action agent (no raw SQL; that lives in db.py).

Deterministic note operations live here: chunking/embedding, path and metadata
normalization, capture persistence, moves, and application of approved metadata.
The explicit metadata LangGraph nodes own classification LLM calls.
"""

import logging
import re
from datetime import datetime

import config
import i18n
from openai_client import get_client
from agents.enrich import db

logger = logging.getLogger(__name__)

TYPES = ("idea", "task", "reminder", "note", "question", "link")
PRIORITIES = ("low", "med", "high")

_ORDINALS = (
    (0, r"\b(first|1st)\b|\bперш(ий|а|е|у)\b"),
    (1, r"\b(second|2nd)\b|\bдруг(ий|а|е|у)\b"),
    (2, r"\b(third|3rd)\b|\bтрет(ій|я|є|ю)\b"),
)
_REFERENCE = re.compile(
    r"\b(that|this|it|one|note)\b|\b(цей|ця|це|цю|той|та|те|його|її|нотатк)\w*\b",
    re.IGNORECASE)
_REL_UNITS = (r"хвилин|хвил|секунд|годин|тижн|тиждень|дн(і|ів|я)|день|"
              r"seconds?|minutes?|\bmin\b|hours?|\bhr\b|days?|weeks?")
_TIME_HINT = re.compile(
    r"(remind|reminder|schedule|нагада|нагадай|"
    r"tomorrow|today|tonight|завтра|сьогодні|післязавтра|"
    r"morning|afternoon|evening|night|noon|"
    r"вранці|зранку|ранок|вдень|ввечері|увечері|вечір|вночі|ніч|опівдні|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ|"
    r"пізніше|later|кілька|декілька|пару|couple|few|через|"
    rf"{_REL_UNITS}|\bin\s+\d|\bat\s+\d|\d{{1,2}}:\d{{2}}|"
    r"\d{1,2}\s*(am|pm)|(?<![а-яіїєґ])[оo]\s+\d)", re.IGNORECASE)
# ===== user language + roots ===============================================

def _language(user_id: int) -> str:
    return i18n.normalize(db.get_language(user_id)) or i18n.DEFAULT_LOCALE


def localized_roots(user_id: int) -> tuple[dict[str, str], str]:
    locale = _language(user_id)
    roots = {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


# ===== embeddings ==========================================================

def _chunk_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP):
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def _embed(text: str) -> str:
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def _build_chunks(text: str) -> list[dict]:
    return [{"index": i, "content": c, "token_count": len(c.split()),
             "metadata": {"char_len": len(c)}, "embedding": _embed(c)}
            for i, c in enumerate(_chunk_text(text))]


def execute_capture(user_id: int, args: dict) -> dict:
    """Validate and atomically persist a previously approved capture proposal."""
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text is required")
    roots, default_root = localized_roots(user_id)
    metadata = normalize({
        "type": args.get("type"), 
        "title": args.get("title"),
        "path": args.get("path"), 
        "tags": args.get("tags"),
        "priority": args.get("priority"),
    }, text, roots, default_root)
    linked_note_ids = [int(note_id) for note_id in args.get("linked_note_ids") or []]
    return db.save_captured_thought(
        user_id, text, metadata, _build_chunks(text), linked_note_ids)


# ===== metadata normalization and deterministic persistence ================

def _clean_path(raw) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")][:2]
    return "/".join(parts) or None


def _enforce_root(path, root_folders, default_root_folder):
    if not path:
        return default_root_folder
    if not root_folders:
        return path
    roots = {name.lower(): name for name in root_folders}
    parts = path.split("/")
    canonical = roots.get(parts[0].lower())
    if canonical is None:
        return default_root_folder
    return "/".join([canonical] + parts[1:])


def normalize(data: dict, text: str, root_folders=None, default_root_folder=None) -> dict:
    note_type = str(data.get("type", "note")).lower()
    if note_type not in TYPES:
        note_type = "note"
    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]
    tags = [str(g).strip().lower() for g in (data.get("tags") or []) if str(g).strip()][:5]
    priority = str(data.get("priority", "low")).lower()
    if priority not in PRIORITIES:
        priority = "low"
    path = _clean_path(data.get("path")) or default_root_folder
    path = _enforce_root(path, root_folders, default_root_folder)
    return {"type": note_type, "title": title, "path": path, "tags": tags, "priority": priority}


# ===== reminders ===========================================================

def has_reminder_time_hint(text: str) -> bool:
    """Cheap gate before the reminder extraction node spends an LLM call."""
    return bool(_TIME_HINT.search(text or ""))


def parse_reminder_time(data: dict, now: datetime) -> datetime | None:
    """Normalize reminder model output into an aware local datetime."""
    if not data.get("is_reminder") or not data.get("remind_at"):
        return None
    parsed = datetime.fromisoformat(data["remind_at"])
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=now.tzinfo)


def plan_reminder(contract: dict, remind_at: datetime) -> dict | None:
    """Build one reminder proposal from a resolved datetime."""
    instruction = contract["instruction"].strip()
    notes = list((contract.get("resolved_entities") or {}).get(
        "referenced_notes") or [])
    selected = None
    for index, pattern in _ORDINALS:
        if re.search(pattern, instruction, re.IGNORECASE) and index < len(notes):
            selected = notes[index]
            break
    if selected is None and notes and _REFERENCE.search(instruction):
        selected = notes[-1]
    text = instruction
    if selected:
        label = selected.get("title") or " ".join(
            (selected.get("text") or "").split())[:120]
        text = f"{instruction}\nReferenced note: “{label or 'note'}” (id {selected['note_id']})."
    args = {"text": text, "remind_at": remind_at.isoformat()}
    if selected:
        args["note_id"] = int(selected["note_id"])
    return {"name": "create_reminder", "args": args,
            "summary": "Create a reminder for %s: “%s”." %
                       (remind_at.isoformat(), text.strip())}


def create_reminder(user_id: int, text: str, remind_at: datetime) -> dict:
    """Create the reminder's backing note and reminder after confirmation."""
    note_id, reminder_id = db.create_note_with_reminder(
        user_id, text, _build_chunks(text), remind_at)
    logger.info("Enrich created reminder %s for user %s", reminder_id, user_id)
    return {"note_id": note_id, "reminder_id": reminder_id,
            "remind_at": remind_at.isoformat()}


def attach_reminder(user_id: int, note_id: int, remind_at: datetime) -> dict | None:
    """Attach a reminder to an existing user-owned note."""
    reminder_id = db.attach_reminder(user_id, note_id, remind_at)
    if reminder_id is None:
        return None
    logger.info("Enrich attached reminder %s to note %s (user %s)",
                reminder_id, note_id, user_id)
    return {"note_id": note_id, "reminder_id": reminder_id,
            "remind_at": remind_at.isoformat()}
