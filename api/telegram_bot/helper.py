"""Telegram-bot section service: the full note lifecycle the bot drives.

Self-contained domain — capture, one-shot enrichment, atomize, polish, delete,
links, reminder detection/dispatch, user settings, and RAG search — duplicated
here over the section's own `db` + shared infra (config, i18n, openai_client,
file_store). No shared domain layer.
"""

import io
import re
import json
import logging
import mimetypes
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config
import i18n
import file_store
from common import embedings
from openai_client import get_client
from api.telegram_bot import db

logger = logging.getLogger(__name__)


# ===== embeddings ==========================================================

def _embed(text: str) -> str:
    return embedings.embed(text)


def _build_chunks(text: str) -> list[dict]:
    return embedings.build_chunks(text)


# ===== capture =============================================================

def ext_for(mime: str, filename: str | None) -> str:
    guessed = mimetypes.guess_extension(mime or "")
    if guessed:
        return guessed.lstrip(".")
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    return "bin"


def _attach_images(note_id: int, images: list[dict]) -> int:
    stored = 0
    for pos, img in enumerate(images):
        data = img.get("bytes")
        if not data:
            continue
        key = file_store.upload_attachment(
            data, kind="image", content_type=img.get("mime") or "application/octet-stream",
            ext=img.get("ext") or "bin")
        if not key:
            logger.warning("Skipped image %d for note %s (storage unavailable)", pos, note_id)
            continue
        db.add_attachment(note_id, key, kind="image", mime=img.get("mime"),
                             size_bytes=len(data), position=pos)
        stored += 1
    return stored


def capture_note(user_id, text, source_type="text", audio_bytes=None, mime=None, images=None) -> int:
    audio_key = None
    if audio_bytes is not None:
        audio_key = file_store.upload_audio(audio_bytes, content_type=mime or "audio/ogg")
    chunks = _build_chunks(text)
    note_id = db.save_note(user_id, text, source_type=source_type,
                              audio_key=audio_key, audio_mime=mime)
    db.save_chunks(note_id, chunks)
    n = _attach_images(note_id, images or [])
    logger.info("Captured note %s (user %s, %s, %d chunk(s), %d image(s))",
                note_id, user_id, source_type, len(chunks), n)
    return note_id


# ===== transcription =======================================================

def _norm(text: str) -> str:
    kept = "".join(c if (c.isalnum() or c.isspace()) else " " for c in text.lower())
    return " ".join(kept.split())


def transcribe(audio_bytes: bytes) -> str:
    audio = io.BytesIO(audio_bytes)
    audio.name = "voice.ogg"
    kwargs = {"model": config.OPENAI_STT_MODEL, "file": audio, "response_format": "text"}
    if config.OPENAI_STT_PROMPT:
        kwargs["prompt"] = config.OPENAI_STT_PROMPT
    if config.OPENAI_STT_LANGUAGE:
        kwargs["language"] = config.OPENAI_STT_LANGUAGE
    result = get_client().audio.transcriptions.create(**kwargs)
    text = (result if isinstance(result, str) else getattr(result, "text", "")).strip()
    logger.info("Transcription: %r", text)
    normalized = _norm(text)
    if normalized and config.OPENAI_STT_PROMPT and normalized in _norm(config.OPENAI_STT_PROMPT):
        logger.info("Transcription matched the context prompt; treating as empty.")
        return ""
    return text


# ===== paths / roots =======================================================

def _localized_roots(user_id: int) -> tuple[dict[str, str], str]:
    locale = language(user_id)
    roots = {i18n.t(locale, key): definition for key, definition in config.ROOT_FOLDERS.items()}
    default = i18n.t(locale, config.DEFAULT_ROOT_FOLDER_KEY)
    return roots, default


def _all_root_names() -> set[str]:
    return {i18n.t(loc, key) for key in config.ROOT_FOLDERS for loc in i18n.SUPPORTED}


def _clean_root_path(path: str) -> str | None:
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
    roots, _ = _localized_roots(user_id)
    paths = [name for name, _ in db.list_paths(user_id)]
    for name in roots:
        if name not in paths:
            paths.append(name)
    return paths


def move_note(user_id: int, note_id: int, raw_path: str) -> tuple[str, dict | None]:
    cleaned = _clean_root_path(raw_path)
    if cleaned is None:
        return ("invalid", None)
    if db.get_note_for_user(user_id, note_id) is None:
        return ("not_found", None)
    db.set_path(note_id, cleaned)
    return ("ok", db.get_meta(note_id))


# ===== atomize / polish / delete ===========================================

_MIN_SPLIT_CHARS = 40


def _split(text: str) -> list[str]:
    clean = (text or "").strip()
    if len(clean) < _MIN_SPLIT_CHARS:
        return [clean] if clean else []
    try:
        system = (
            "You split a person's brain-dump note (Ukrainian or English) into ATOMIC "
            "notes — one self-contained idea, task, question or fact each "
            "(Zettelkasten style). Rules: keep each atom's original wording as much "
            "as possible; do NOT invent, summarise or add content; do NOT merge "
            "unrelated ideas; do NOT over-split a single coherent thought; preserve "
            "the note's language. If the note is already a single idea, return it "
            "unchanged as one atom. Return strict JSON: {\"atoms\": [\"...\", ...]}.")
        resp = get_client().chat.completions.create(
            model=config.ATOMIZE_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": clean}])
        data = json.loads(resp.choices[0].message.content)
        atoms = [str(a).strip() for a in data.get("atoms", []) if str(a).strip()]
        return atoms or [clean]
    except Exception:
        logger.exception("Atomization failed; keeping the note whole")
        return [clean]


def atomize_note(user_id: int, note_id: int) -> list[dict]:
    text = db.get_text(note_id)
    if not text:
        return []
    atoms = _split(text)
    if len(atoms) < 2:
        return []
    return [{"note_id": capture_note(user_id, a), "text": a} for a in atoms]


def _polish(text: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return clean
    try:
        system = (
            "You tidy up a person's brain-dump note (Ukrainian or English) so it "
            "reads as natural, clear language. Fix spelling, grammar, punctuation, "
            "capitalization and spacing, and lightly smooth awkward phrasing. STRICT "
            "rules: keep the SAME language as the input; preserve the meaning exactly; "
            "do NOT add, remove, invent, answer, explain, summarize or translate "
            "anything; never change names, numbers, dates or specific facts; keep it "
            "about the same length. If the text is already clean, return it "
            "unchanged. Return strict JSON: {\"text\": \"<cleaned note>\"}.")
        resp = get_client().chat.completions.create(
            model=config.POLISH_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": clean}])
        result = str(json.loads(resp.choices[0].message.content).get("text", "")).strip()
        return result or clean
    except Exception:
        logger.exception("Polish failed; keeping the note unchanged")
        return clean


def polish_note(note_id: int) -> str | None:
    text = db.get_text(note_id)
    if not text:
        return None
    cleaned = _polish(text)
    if cleaned != text:
        db.set_text(note_id, cleaned)
        db.delete_chunks(note_id)
        db.save_chunks(note_id, _build_chunks(cleaned))
    return cleaned


def delete_bare_note(note_id: int) -> bool:
    keys = db.attachment_keys_for_note(note_id)
    audio_key = db.get_audio_key(note_id)
    if audio_key:
        keys.append(audio_key)
    deleted = db.delete_if_bare(note_id)
    if deleted:
        for key in keys:
            file_store.delete_object(key)
    return deleted


# ===== enrichment (one-shot) ===============================================

_TYPES = ("idea", "task", "reminder", "note", "question", "link")
_PRIORITIES = ("low", "med", "high")


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


def _normalize(data, text, root_folders=None, default_root_folder=None) -> dict:
    note_type = str(data.get("type", "note")).lower()
    if note_type not in _TYPES:
        note_type = "note"
    title = (data.get("title") or text.strip()[:80]).strip() or text.strip()[:80]
    tags = [str(g).strip().lower() for g in (data.get("tags") or []) if str(g).strip()][:5]
    priority = str(data.get("priority", "low")).lower()
    if priority not in _PRIORITIES:
        priority = "low"
    path = _clean_path(data.get("path")) or default_root_folder
    return {"type": note_type, "title": title,
            "path": _enforce_root(path, root_folders, default_root_folder),
            "tags": tags, "priority": priority}


def _root_block(root_folders, default_root_folder) -> str:
    if not root_folders:
        return ""
    names = ", ".join(root_folders)
    meanings = "; ".join(f"{name} — {desc}" for name, desc in root_folders.items())
    return (f" The path is core to the vault: any path starts with exactly one of these "
            f"root folders — {names} — followed by at most one sub-folder, so a path is "
            f"one or two levels total. Never nest deeper than two levels. Root folder "
            f"meanings: {meanings}. Pick the root folder matching the note's purpose, and "
            f"reuse an existing path when one fits. If you cannot determine a path, use "
            f"{default_root_folder}.")


def _fmt_vocab(items) -> str:
    out = []
    for it in items:
        if isinstance(it, (list, tuple)) and len(it) == 2:
            out.append(f"{it[0]} ({it[1]})")
        else:
            out.append(str(it))
    return ", ".join(out)


def _vocabulary(known, tags) -> str:
    lines = []
    if known:
        lines.append(f"Existing paths (with note use counts): {_fmt_vocab(known)}.")
    if tags:
        lines.append(f"Existing tags (with use counts): {_fmt_vocab(tags)}.")
    if not lines:
        return ""
    return (" Reuse an existing path/tag verbatim when it genuinely fits (extend a path "
            "rather than inventing a parallel one); only create a new one if none apply. "
            + " ".join(lines))


def _neighbour_hint(neighbours) -> str:
    paths, tags = Counter(), Counter()
    for n in neighbours:
        if n.get("path"):
            paths[n["path"]] += 1
        for tg in (n.get("tags") or []):
            tags[tg] += 1
    if not paths and not tags:
        return ""
    parts = []
    if paths:
        parts.append("filed under: " + ", ".join(f"{p} ({c})" for p, c in paths.most_common(5)))
    if tags:
        parts.append("commonly tagged: " + ", ".join(f"{t} ({c})" for t, c in tags.most_common(8)))
    return " Notes most similar to this one are " + "; ".join(parts) + ". Prefer these when they fit."


def _similar_block(similar) -> str:
    if not similar:
        return ""
    lines = [f"- \"{n['title']}\" -> type={n['note_type']}, path={n.get('path')}, "
             f"tags={n.get('tags') or []}" for n in similar]
    return (" Similar past notes and how they were classified (reuse their type / "
            "path / tags when appropriate):\n" + "\n".join(lines))


def _enrich(text, known_paths_list, known_tags, similar_notes, root_folders, default_root) -> dict:
    try:
        neighbours = similar_notes or []
        threshold = config.ENRICH_SIMILAR_MAX_DISTANCE
        has_dist = any(n.get("distance") is not None for n in neighbours)
        strong = ([n for n in neighbours if n.get("distance") is not None and n["distance"] <= threshold]
                  if has_dist else neighbours)
        if strong:
            neighbour_block = _neighbour_hint(strong) + _similar_block(strong)
        elif neighbours:
            neighbour_block = (" None of the user's existing notes are closely related to this one, "
                               "so do not force-fit an existing path — prefer a default folder, and "
                               "create a new path only if clearly warranted.")
        else:
            neighbour_block = ""
        system = (
            "You organize a person's brain-dump notes (Ukrainian or English) into "
            "an PARA-style vault (i.e. Obsidian-style)."
            "Classify the note and extract metadata. Return strict JSON with keys: "
            "reasoning (1-2 short sentences), "
            "type (one of: idea, task, reminder, note, question, link), "
            "title (a concise summary, <=8 words, in the note's own language), "
            "path (a single vault folder path: a root folder plus at most one "
            "sub-folder — two levels at most), "
            "tags (0-5 lowercase topic keywords), priority (one of: low, med, high)."
            + _root_block(root_folders, default_root) + _vocabulary(known_paths_list, known_tags)
            + neighbour_block)
        resp = get_client().chat.completions.create(
            model=config.ENRICH_LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        return _normalize(json.loads(resp.choices[0].message.content), text, root_folders, default_root)
    except Exception:
        logger.exception("Enrichment failed; storing as a plain note")
        return {"type": "note", "title": text.strip()[:80], "path": default_root,
                "tags": [], "priority": "low"}


def enrich_note(user_id: int, note_id: int) -> dict | None:
    text = db.get_text(note_id)
    if not text:
        return None
    embedding = _embed(text)
    similar = db.similar_notes(user_id, embedding, exclude_note_id=note_id,
                                  limit=config.ENRICH_SIMILAR_LIMIT)
    root_folders, default_root = _localized_roots(user_id)
    meta = _enrich(text, db.list_paths(user_id), db.list_tags(user_id),
                   similar, root_folders, default_root)
    db.set_metadata(note_id, meta["type"], meta["title"], meta["priority"],
                       meta["tags"], meta["path"])
    return meta


# ===== links ===============================================================

_PATH_BOOST = 0.10
_TAG_BOOST = 0.05


def _same_family(a, b) -> bool:
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def link_candidates(user_id: int, note_id: int, limit: int = 5) -> list[dict]:
    note = db.get_note(note_id)
    if not note:
        return []
    embedding = _embed(note["text"])
    rows = db.candidate_notes(user_id, embedding, [note_id], limit * 3)
    note_path = note["path"]
    note_tags = set(note["tags"] or [])

    def score(r):
        s = 1.0 - float(r["distance"])
        if _same_family(note_path, r["path"]):
            s += _PATH_BOOST
        s += _TAG_BOOST * len(note_tags & set(r["tags"] or []))
        return s

    for r in rows:
        r["score"] = round(score(r), 4)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:limit]


def is_linked(a: int, b: int) -> bool:
    return db.is_linked(a, b)


def toggle_link(a: int, b: int) -> bool:
    if db.is_linked(a, b):
        db.remove_link(a, b)
        return False
    db.add_link(a, b)
    return True


# ===== reminders ===========================================================

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

_SNOOZE_TOMORROW_HOUR = 9


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


def detect_reminder_info(note_id: int, user_id: int, text: str) -> dict | None:
    tz, _ = settings(user_id)
    remind_at = _extract_reminder(text, datetime.now(tz))
    if not remind_at:
        return None
    reminder_id = db.create_reminder(note_id, user_id, remind_at)
    return {"id": reminder_id, "remind_at": remind_at.isoformat()}


def upcoming(user_id: int):
    return db.upcoming_reminders(user_id)


def active_count(user_id: int) -> int:
    return db.count_active(user_id)


def claim_due(now, stale_before, limit: int = 50):
    return db.claim_due_reminders(now, stale_before, limit)


def reschedule(reminder_id: int) -> None:
    db.set_reminder_status(reminder_id, "scheduled")


def cancel(reminder_id: int) -> None:
    db.set_reminder_status(reminder_id, "canceled")


def mark_done(reminder_id: int) -> None:
    db.set_reminder_status(reminder_id, "done")


def snooze(reminder_id: int, user_id: int, mode: str) -> datetime:
    tz = timezone(user_id)
    now = datetime.now(tz)
    if mode == "tomorrow":
        new_time = (now + timedelta(days=1)).replace(
            hour=_SNOOZE_TOMORROW_HOUR, minute=0, second=0, microsecond=0)
    else:
        new_time = now + timedelta(minutes=int(mode))
    db.postpone(reminder_id, new_time)
    return new_time


# ===== user identity + settings ============================================

def resolve(chat_id: int, username: str | None = None) -> int:
    return db.get_or_create_user(chat_id, username)


def _resolve_tz(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            logger.warning("Invalid stored timezone %r; using default", name)
    return config.DEFAULT_TZ


def _resolve_locale(lang: str | None) -> str:
    return i18n.normalize(lang) or i18n.DEFAULT_LOCALE


def timezone(user_id: int) -> ZoneInfo:
    tz_name, _ = db.get_settings(user_id)
    return _resolve_tz(tz_name)


def language(user_id: int) -> str:
    _, lang = db.get_settings(user_id)
    return _resolve_locale(lang)


def settings(user_id: int) -> tuple[ZoneInfo, str]:
    tz_name, lang = db.get_settings(user_id)
    return _resolve_tz(tz_name), _resolve_locale(lang)


def settings_view(user_id: int) -> dict:
    tz_name, lang = db.get_settings(user_id)
    return {"timezone": tz_name, "language": lang,
            "tz_name": _resolve_tz(tz_name).key, "locale": _resolve_locale(lang)}


def set_timezone(user_id: int, name: str) -> bool:
    try:
        ZoneInfo(name)
    except Exception:
        return False
    db.set_user_timezone(user_id, name)
    return True


def set_language(user_id: int, code: str) -> str | None:
    lang = i18n.normalize(code)
    if lang not in i18n.SUPPORTED:
        return None
    db.set_user_language(user_id, lang)
    return lang


# ===== search (agenda-aware RAG) ===========================================

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


def _format_hits(hits, tz=None) -> str:
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


def search_answer(user_id: int, query: str, now: datetime,
                  language: str = "en", tz=None) -> str | None:
    rng = _parse_agenda(query, now)
    start, end = rng if rng else (None, None)
    hits = db.search_chunks(user_id, _embed(query), remind_start=start, remind_end=end)
    if not hits:
        return None
    system = (
        "You are the user's personal notes assistant. Answer the user's question "
        "using ONLY the notes provided below — do not invent facts. Choose the "
        "single most relevant note and base your answer on it; ignore the others. "
        "If a note has a reminder time, mention it naturally. If none of the notes "
        "actually answer the question, say you couldn't find anything about it. "
        f"Reply in this language: {language}. Keep it short, warm, and conversational.")
    user = f"Question: {query}\n\nNotes:\n{_format_hits(hits, tz)}"
    try:
        resp = get_client().chat.completions.create(
            model=config.ANSWER_LLM_MODEL, temperature=0.3,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content.strip()
    except Exception:
        logger.exception("Answer generation failed; falling back to top chunk")
        return hits[0]["content"]
