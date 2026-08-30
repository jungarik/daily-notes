"""Self-contained domain + persistence for the chat agent.

Everything the chat agent's tools + orchestration need — SQL, embeddings, RAG
search, reminder creation, note capture/move, and chat-thread persistence — lives
here, duplicated so `agents/chat` depends on no shared domain layer (only infra:
db, config, i18n, openai_client). Mirrors what the other verticals each own.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta

from psycopg.types.json import Json

import config
import i18n
from db import cursor
from openai_client import get_client

logger = logging.getLogger(__name__)


# ===== persistence =========================================================

def notes_brief(user_id: int, ids) -> list[dict]:
    ids = list(ids)
    if not ids:
        return []
    with cursor() as cur:
        cur.execute(
            "SELECT id, title, text, path FROM notes WHERE user_id = %s AND id = ANY(%s);",
            (user_id, ids),
        )
        return [{"id": r[0], "title": r[1], "text": r[2], "path": r[3]} for r in cur.fetchall()]


def get_note_for_user(user_id: int, note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, text, title, path, tags FROM notes WHERE id = %s AND user_id = %s;",
            (note_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "text": row[1], "title": row[2], "path": row[3], "tags": row[4] or []}


def get_text(note_id: int) -> str | None:
    with cursor() as cur:
        cur.execute("SELECT text FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        return row[0] if row else None


def save_note(user_id: int, text: str) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO notes (user_id, text, source_type) VALUES (%s, %s, 'text') RETURNING id;",
            (user_id, text),
        )
        return cur.fetchone()[0]


def set_path(note_id: int, path: str) -> None:
    with cursor() as cur:
        cur.execute("UPDATE notes SET path = %s WHERE id = %s;", (path, note_id))


def get_meta(note_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT note_type, title, path, tags, priority FROM notes WHERE id = %s;", (note_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {"type": row[0], "title": row[1], "path": row[2],
                "tags": row[3] or [], "priority": row[4]}


def list_paths(user_id: int, limit: int = 30) -> list[tuple[str, int]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT path, count(*) AS c FROM notes
            WHERE user_id = %s AND path IS NOT NULL AND path <> ''
            GROUP BY path ORDER BY c DESC, path LIMIT %s;
            """,
            (user_id, limit),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def save_chunks(note_id: int, chunks: list[dict]) -> None:
    if not chunks:
        return
    with cursor() as cur:
        for ch in chunks:
            cur.execute(
                """
                INSERT INTO note_chunks
                    (note_id, chunk_index, content, token_count, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector);
                """,
                (note_id, ch["index"], ch["content"], ch["token_count"],
                 Json(ch["metadata"]), ch["embedding"]),
            )


def links_of_for_user(user_id: int, note_id: int, limit: int = 100):
    with cursor() as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.text, 'out' AS direction
            FROM note_links l JOIN notes n ON n.id = l.to_note_id
            WHERE l.from_note_id = %s AND n.user_id = %s
            UNION
            SELECT n.id, n.title, n.text, 'in' AS direction
            FROM note_links l JOIN notes n ON n.id = l.from_note_id
            WHERE l.to_note_id = %s AND n.user_id = %s
            ORDER BY direction LIMIT %s;
            """,
            (note_id, user_id, note_id, user_id, limit),
        )
        return cur.fetchall()


def create_reminder(note_id: int, user_id: int, remind_at) -> int:
    with cursor() as cur:
        cur.execute(
            "INSERT INTO reminders (note_id, user_id, remind_at) VALUES (%s, %s, %s) RETURNING id;",
            (note_id, user_id, remind_at),
        )
        return cur.fetchone()[0]


def upcoming_reminders(user_id: int, limit: int = 10):
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.remind_at, m.text, r.status
            FROM reminders r JOIN notes m ON m.id = r.note_id
            WHERE r.user_id = %s AND r.status IN ('scheduled', 'postponed')
            ORDER BY r.remind_at LIMIT %s;
            """,
            (user_id, limit),
        )
        return cur.fetchall()


def get_user_settings(user_id: int) -> tuple[str | None, str | None]:
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def search_chunks(user_id: int, query_embedding: str, limit: int = 5,
                  remind_start=None, remind_end=None) -> list[dict]:
    filtering = remind_start is not None and remind_end is not None
    remind_range = "AND r.remind_at >= %s AND r.remind_at < %s" if filtering else ""
    where_filter = "AND rem.remind_at IS NOT NULL" if filtering else ""
    params: list = [query_embedding]
    if filtering:
        params += [remind_start, remind_end]
    params += [user_id, limit]
    with cursor() as cur:
        cur.execute(
            f"""
            WITH scored AS (
                SELECT mc.id AS chunk_id, mc.note_id AS note_id, mc.content AS content,
                       mc.chunk_index AS chunk_index, mc.token_count AS token_count,
                       mc.metadata AS metadata, m.source_type AS source_type,
                       m.created_at AS created_at, rem.remind_at AS remind_at,
                       (mc.embedding <=> %s::vector) AS distance
                FROM note_chunks mc
                JOIN notes m ON m.id = mc.note_id
                LEFT JOIN (
                    SELECT r.note_id, MIN(r.remind_at) AS remind_at
                    FROM reminders r
                    WHERE r.status IN ('scheduled', 'postponed') {remind_range}
                    GROUP BY r.note_id
                ) rem ON rem.note_id = mc.note_id
                WHERE m.user_id = %s {where_filter}
                ORDER BY distance LIMIT %s
            )
            SELECT s.chunk_id, s.note_id, s.content, s.chunk_index, s.token_count,
                   s.metadata, s.source_type, s.created_at, s.remind_at, s.distance,
                   ROW_NUMBER() OVER (ORDER BY s.distance) AS rank,
                   (SELECT count(*) FROM note_chunks c2 WHERE c2.note_id = s.note_id) AS chunk_count
            FROM scored s ORDER BY s.distance;
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    hits, top = [], None
    for r in rows:
        distance = float(r[9]); similarity = 1.0 - distance
        if top is None:
            top = similarity
        hits.append({
            "rank": r[10], "similarity": round(similarity, 4), "distance": round(distance, 4),
            "rel_to_top": round(top - similarity, 4), "content": r[2], "note_id": r[1],
            "chunk_id": r[0], "chunk_index": r[3], "chunk_count": r[11],
            "source_type": r[6], "created_at": r[7], "remind_at": r[8],
            "token_count": r[4], "metadata": r[5],
        })
    return hits


# ----- chat threads -----

def create_thread(user_id: int) -> int:
    with cursor() as cur:
        cur.execute("INSERT INTO chat_threads (user_id) VALUES (%s) RETURNING id;", (user_id,))
        return cur.fetchone()[0]


def get_thread(user_id: int, thread_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, messages, pending FROM chat_threads WHERE id = %s AND user_id = %s;",
            (thread_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "messages": row[1] or [], "pending": row[2]}


def save_thread(thread_id: int, messages: list, pending: dict | None) -> None:
    with cursor() as cur:
        cur.execute(
            "UPDATE chat_threads SET messages = %s, pending = %s, updated_at = now() WHERE id = %s;",
            (Json(messages), Json(pending) if pending is not None else None, thread_id),
        )


# ===== embeddings + RAG ====================================================

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
    hits = search_chunks(user_id, embed(query), remind_start=start, remind_end=end)
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
    return create_reminder(note_id, user_id, remind_at), remind_at


def upcoming(user_id: int):
    return upcoming_reminders(user_id)


# ===== note capture / move (write tools) ===================================

def language(user_id: int) -> str:
    _, lang = get_user_settings(user_id)
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
    paths = [name for name, _ in list_paths(user_id)]
    for name in roots:
        if name not in paths:
            paths.append(name)
    return paths


def capture_note(user_id: int, text: str) -> int:
    """Persist a text note (chunk + embed). Text-only path (the agent never
    captures audio/images)."""
    note_id = save_note(user_id, text)
    save_chunks(note_id, build_chunks(text))
    logger.info("Agent captured note %s (user %s)", note_id, user_id)
    return note_id


def move_note(user_id: int, note_id: int, raw_path: str) -> tuple[str, dict | None]:
    cleaned = clean_root_path(raw_path)
    if cleaned is None:
        return ("invalid", None)
    if get_note_for_user(user_id, note_id) is None:
        return ("not_found", None)
    set_path(note_id, cleaned)
    return ("ok", get_meta(note_id))
