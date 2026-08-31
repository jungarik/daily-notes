"""Domain logic for the chat agent (no raw SQL — that lives in db.py).

Embeddings, RAG search, reminder-time extraction, note capture/move, and the
user's path vocabulary — over the agent's own `db` + shared infra (config, i18n,
openai_client). Self-contained: no shared domain layer.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta

import config
import i18n
from openai_client import get_client
from agents.chat import db

logger = logging.getLogger(__name__)


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


def embed(text: str) -> str:
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def build_chunks(text: str) -> list[dict]:
    return [{"index": i, "content": c, "token_count": len(c.split()),
             "metadata": {"char_len": len(c)}, "embedding": embed(c)}
            for i, c in enumerate(_chunk_text(text))]


# ===== RAG =================================================================

def _format_hits(hits: list[dict], tz=None) -> str:
    blocks = []
    for h in hits:
        meta = [f"similarity {h['similarity']:.2f}"]
        created = h["created_at"]; remind_at = h.get("remind_at")
        if tz is not None:
            created = created.astimezone(tz)
            remind_at = remind_at.astimezone(tz) if remind_at else None
        meta.append(f"saved {created:%Y-%m-%d %H:%M}")
        if remind_at:
            meta.append(f"reminder {remind_at:%Y-%m-%d %H:%M}")
        meta.append(h["source_type"])
        blocks.append(f"[note {h['rank']}] ({', '.join(meta)})\n{h['content']}")
    return "\n\n".join(blocks)


def _answer_from_hits(hits: list[dict], query: str, language: str = "en", tz=None) -> str:
    system = (
        "You are the user's personal notes assistant. Answer the user's question "
        "using ONLY the notes provided below — do not invent facts. Choose the "
        "single most relevant note and base your answer on it; ignore the others. "
        "If a note has a reminder time, mention it naturally. If none of the notes "
        "actually answer the question, say you couldn't find anything about it. "
        f"Reply in this language: {language}. Keep it short, warm, and conversational."
    )
    user = f"Question: {query}\n\nNotes:\n{_format_hits(hits, tz)}"
    try:
        resp = get_client().chat.completions.create(
            model=config.ANSWER_LLM_MODEL, temperature=0.3,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        logger.exception("Answer generation failed; falling back to top chunk")
        return hits[0]["content"]


# ----- agenda range gate (for scoping RAG to reminder dates) -----

_AGENDA_HINT = re.compile(
    r"what\s+(do\s+i\s+have\s+to\s+do|to\s+do|should\s+i\s+do|'?s\s+on)|"
    r"\bmy\s+(tasks|to-?dos|agenda|plans)\b|\bto-?do\b|"
    r"що\s+(мені\s+)?(треба\s+|потрібно\s+|маю\s+)?(з)?робити|"
    r"мо[її]\s+(завдання|справи|плани)|план[иі]\s+на|"
    r"що\s+(в\s+мене\s+)?на\s+(сьогодні|завтра|тиждень)", re.IGNORECASE)
_RANGE_KEYWORD = re.compile(
    r"\btoday\b|\btomorrow\b|\btonight\b|\bweek\b|weekend|month|\bnext\b|"
    r"\d+\s*(day|week|month)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"сьогодні|завтра|тижд|тижн|вихідн|місяц|наступн|"
    r"понеділ|вівтор|серед|четвер|п.?ятниц|субот|неділ", re.IGNORECASE)


def _parse_agenda(text: str, now: datetime):
    if not (_AGENDA_HINT.search(text) or _RANGE_KEYWORD.search(text)):
        return None
    try:
        system = (
            "The user asks what they need to do over some period. "
            "Return strict JSON {\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\"} "
            "for the inclusive date range they mean. "
            f"Today is {now.strftime('%Y-%m-%d')} ({now.tzname()}). "
            "If unclear, use today for both dates.")
        resp = get_client().chat.completions.create(
            model=config.REMINDER_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        data = json.loads(resp.choices[0].message.content)
        sd = date.fromisoformat(data["start"]); ed = date.fromisoformat(data["end"])
        tz = now.tzinfo
        start = datetime(sd.year, sd.month, sd.day, tzinfo=tz)
        end = datetime(ed.year, ed.month, ed.day, tzinfo=tz) + timedelta(days=1)
        return start, end
    except Exception:
        logger.exception("LLM agenda range failed")
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)


def answer_with_sources(user_id: int, query: str, now: datetime,
                        language: str = "en", tz=None) -> tuple[str | None, list[int]]:
    """RAG answer + the note ids it drew on (most-relevant first)."""
    rng = _parse_agenda(query, now)
    start, end = rng if rng else (None, None)
    hits = db.search_chunks(user_id, embed(query), remind_start=start, remind_end=end)
    if not hits:
        return (None, [])
    text = _answer_from_hits(hits, query, language=language, tz=tz)
    source_ids = list(dict.fromkeys(h["note_id"] for h in hits))
    return (text, source_ids)


# ===== reminders (time extraction) =========================================

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


def _extract_reminder(text: str, now: datetime):
    if not _TIME_HINT.search(text):
        return None
    try:
        system = (
            "Extract a reminder from the user's message (Ukrainian or English). "
            "Return strict JSON: {\"is_reminder\": bool, \"remind_at\": string|null}. "
            "remind_at is ISO-8601 local time with no timezone, e.g. 2026-07-30T09:00:00. "
            f"Current local time is {now.strftime('%Y-%m-%dT%H:%M:%S')} ({now.tzname()}). "
            "Resolve all relative expressions against it. If only a part of day is "
            "given, use morning=09:00, noon=12:00, afternoon=15:00, evening=19:00, "
            "night=21:00. If a date has no time, use 09:00. For an indefinite quantity "
            f"('кілька'/'a few') assume about {config.REMINDER_FEW_COUNT}. For a vague "
            f"'later'/'пізніше', schedule about {config.REMINDER_LATER} from now. "
            "If the message is not asking to be reminded, set is_reminder=false.")
        resp = get_client().chat.completions.create(
            model=config.REMINDER_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        data = json.loads(resp.choices[0].message.content)
        if not data.get("is_reminder") or not data.get("remind_at"):
            return None
        dt = datetime.fromisoformat(data["remind_at"])
        return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)
    except Exception:
        logger.exception("Reminder extraction failed")
        return None


def detect_reminder(note_id: int, user_id: int, text: str, now: datetime):
    remind_at = _extract_reminder(text, now)
    if not remind_at:
        return None
    return db.create_reminder(note_id, user_id, remind_at), remind_at


# ===== note capture / move (write tools) ===================================

def language(user_id: int) -> str:
    _, lang = db.get_user_settings(user_id)
    return i18n.normalize(lang) or i18n.DEFAULT_LOCALE


def _localized_roots(user_id: int) -> dict[str, str]:
    locale = language(user_id)
    return {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}


def _all_root_names() -> set[str]:
    return {i18n.t(loc, key) for key in config.ROOT_FOLDERS for loc in i18n.SUPPORTED}


def clean_root_path(path: str) -> str | None:
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


def known_paths(user_id: int) -> list[str]:
    roots = _localized_roots(user_id)
    paths = [name for name, _ in db.list_paths(user_id)]
    for name in roots:
        if name not in paths:
            paths.append(name)
    return paths


def capture_note(user_id: int, text: str) -> int:
    """Persist a text note (chunk + embed). Text-only path (the agent never
    captures audio/images)."""
    note_id = db.save_note(user_id, text)
    db.save_chunks(note_id, build_chunks(text))
    logger.info("Agent captured note %s (user %s)", note_id, user_id)
    return note_id


def move_note(user_id: int, note_id: int, raw_path: str) -> tuple[str, dict | None]:
    cleaned = clean_root_path(raw_path)
    if cleaned is None:
        return ("invalid", None)
    if db.get_note_for_user(user_id, note_id) is None:
        return ("not_found", None)
    db.set_path(note_id, cleaned)
    return ("ok", db.get_meta(note_id))
