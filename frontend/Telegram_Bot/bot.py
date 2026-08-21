"""
Telegram bot layer — a thin client adapter.

Translates Telegram updates into API calls and formats the replies. It holds no
business logic and no database access: capture, reminder detection/creation,
enrichment, link selection, search/answer and user settings all live behind the
API service and are reached through `api_client.ApiClient`. Only Telegram
specifics live here — keyboards, message formatting, command wiring, and
reminder delivery (the bot owns the transport, so the dispatcher sends messages;
claiming/completing reminders happens over the API).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import i18n
from frontend.Telegram_Bot.api_client import ApiClient
from i18n import t
from config import (
    DEFAULT_TZ,
    REMINDER_POLL_SECONDS,
    LATE_NOTE_SECONDS,
)
from telegram import (
    Update,
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# The one gateway to the backend: every domain call goes through here. The bot
# never imports services/stores or touches the database.
api = ApiClient()

# chat_id -> user_id. The mapping is stable, so cache it to avoid a resolve
# round trip on every update.
_uid_cache: dict[int, int] = {}

# Pending "New path…" prompts: ForceReply prompt message_id -> the note + the
# original enriched message to refresh once the user replies with a path.
pending_new_path: dict[int, dict] = {}

# Telegram delivers an album (media group) as several separate photo updates that
# share a media_group_id. We buffer them and flush once, a short debounce after
# the last one arrives, into a single note with all images.
pending_albums: dict[str, dict] = {}
ALBUM_DEBOUNCE_SECONDS = 1.5


async def resolve_uid(update: Update) -> int | None:
    """Resolve the internal user_id for a Telegram update (cached). None if the
    API can't be reached."""
    chat_id = update.effective_chat.id
    uid = _uid_cache.get(chat_id)
    if uid is None:
        username = update.effective_user.username if update.effective_user else None
        uid = await api.resolve_user(chat_id, username)
        if uid is not None:
            _uid_cache[chat_id] = uid
    return uid


def _tz_from(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            logger.warning("Invalid timezone %r from API; using default", name)
    return DEFAULT_TZ


async def load_ctx(update: Update) -> tuple[int | None, ZoneInfo, str, dict]:
    """Resolve (user_id, timezone, locale, settings) for an update in one shot.

    Falls back to defaults for formatting when the API is unreachable, so error
    replies still render. `user_id` is None when identity can't be resolved.
    """
    user_id = await resolve_uid(update)
    if user_id is None:
        return None, DEFAULT_TZ, i18n.DEFAULT_LOCALE, {}
    settings = await api.get_settings(user_id) or {}
    tz = _tz_from(settings.get("tz_name"))
    locale = settings.get("locale") or i18n.DEFAULT_LOCALE
    return user_id, tz, locale, settings


NOTE_ICONS = {
    "idea": "💡", "task": "✅", "reminder": "⏰",
    "note": "📝", "question": "❓", "link": "🔗",
}


def _capture_keyboard(note_id: int, locale: str) -> InlineKeyboardMarkup:
    """Actions on a freshly captured (not yet enriched) note — two per row:
    enrich, atomize, polish (tidy the wording), or cancel (delete)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(locale, "btn_enrich"), callback_data=f"e:{note_id}"),
            InlineKeyboardButton(t(locale, "btn_atomize"), callback_data=f"a:{note_id}"),
        ],
        [
            InlineKeyboardButton(t(locale, "btn_polish"), callback_data=f"f:{note_id}"),
            InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"c:{note_id}"),
        ],
    ])


def _meta_line(meta: dict) -> str:
    icon = NOTE_ICONS.get(meta["type"], "📝")
    parts = [f"{icon} {meta['title']}"]
    if meta["path"]:
        parts.append("📁 " + meta["path"])
    if meta["tags"]:
        parts.append("🏷 " + ", ".join(meta["tags"]))
    parts.append("⚡ " + meta["priority"])
    return "\n".join(parts)


async def _offer_reminder(msg, reminder: dict | None, tz: ZoneInfo, locale: str):
    """Confirm a reminder the API created during capture. Formatting only —
    detection/creation happened server-side."""
    if not reminder:
        return
    when = datetime.fromisoformat(reminder["remind_at"]).astimezone(tz)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"r:cancel:{reminder['id']}")]]
    )
    await msg.reply_text(
        t(locale, "reminder_set", when=f"{when:%Y-%m-%d %H:%M}", tz=when.tzname()),
        reply_markup=keyboard,
    )


async def _apply_new_path(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A user replied to a 'New path…' prompt: validate + set it via the API and
    refresh the original enriched note."""
    msg = update.message
    info = pending_new_path.pop(msg.reply_to_message.message_id, None)
    if not info:
        return
    _, _, locale, _ = await load_ctx(update)
    meta, err = await api.set_note_path(info["note_id"], msg.text.strip())
    if err:
        await msg.reply_text(t(locale, "path_invalid", roots=", ".join(t(locale, k) for k in config.ROOT_FOLDERS)))
        return
    if not meta:
        await msg.reply_text(t(locale, "error_generic"))
        return
    try:
        await context.bot.edit_message_text(
            chat_id=info["chat_id"], message_id=info["msg_id"],
            text=f"{info['base']}\n\n{_meta_line(meta)}",
            reply_markup=_enriched_keyboard(info["note_id"], locale),
        )
    except Exception:
        logger.exception("Failed to refresh note message after new path")
    await msg.reply_text(t(locale, "path_set", path=meta.get("path", "")))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture a text note immediately; offer on-demand enrichment."""
    msg = update.message
    # A reply to a pending 'New path…' prompt is a path, not a new note.
    if msg.reply_to_message and msg.reply_to_message.message_id in pending_new_path:
        await _apply_new_path(update, context)
        return
    text = msg.text
    if not text:      # non-text messages never reach this handler, but be safe
        return
    user_id, tz, locale, _ = await load_ctx(update)
    if user_id is None:
        await msg.reply_text(t(locale, "error_generic"))
        return
    res = await api.capture_text(user_id, text)
    if not res or not res.get("note_id"):
        await msg.reply_text(t(locale, "error_generic"))
        return
    note_id = res["note_id"]
    await msg.reply_text(t(locale, "saved"), reply_markup=_capture_keyboard(note_id, locale))
    await _offer_reminder(msg, res.get("reminder"), tz, locale)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download a voice note and hand it to the API to transcribe + capture."""
    msg = update.message
    voice = msg.voice
    user_id, tz, locale, _ = await load_ctx(update)
    if user_id is None:
        await msg.reply_text(t(locale, "error_generic"))
        return
    tg_file = await voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())
    mime = voice.mime_type or "audio/ogg"

    res = await api.capture_voice(user_id, audio_bytes, mime)
    if res is None:
        await msg.reply_text(t(locale, "transcribe_failed"))
        return
    if not res.get("note_id"):
        await msg.reply_text(t(locale, "transcribe_empty"))
        return

    note_id = res["note_id"]
    await msg.reply_text(
        t(locale, "transcribed_saved", text=res.get("text") or ""),
        reply_markup=_capture_keyboard(note_id, locale),
    )
    await _offer_reminder(msg, res.get("reminder"), tz, locale)


async def _download_photo(msg) -> tuple[str, bytes, str]:
    """Download a photo message's largest size. Returns (filename, bytes, mime).

    Handles both compressed photos (message.photo) and images sent as an
    uncompressed document (message.document with an image/* MIME)."""
    if msg.photo:
        photo = msg.photo[-1]            # last entry is the highest resolution
        tg_file = await photo.get_file()
        blob = bytes(await tg_file.download_as_bytearray())
        return (f"{photo.file_unique_id}.jpg", blob, "image/jpeg")
    doc = msg.document
    tg_file = await doc.get_file()
    blob = bytes(await tg_file.download_as_bytearray())
    mime = doc.mime_type or "image/jpeg"
    name = doc.file_name or f"{doc.file_unique_id}.jpg"
    return (name, blob, mime)


async def _save_media_note(msg, user_id, tz, locale, caption, images):
    """Capture a media note (caption + images) and reply, or report failure."""
    logger.info(
        "Capturing media note: user=%s images=%d bytes=%s caption=%r",
        user_id, len(images), [len(b) for _, b, _ in images], caption[:40],
    )
    res = await api.capture_media(user_id, caption, images)
    if not res or not res.get("note_id"):
        await msg.reply_text(t(locale, "error_generic"))
        return
    note_id = res["note_id"]
    await msg.reply_text(
        t(locale, "media_saved", count=len(images)),
        reply_markup=_capture_keyboard(note_id, locale),
    )
    await _offer_reminder(msg, res.get("reminder"), tz, locale)


async def _flush_album(group_id: str):
    """After the debounce, capture a buffered album as one note with all images."""
    await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
    album = pending_albums.pop(group_id, None)
    if not album:
        return
    await _save_media_note(
        album["msg"], album["user_id"], album["tz"], album["locale"],
        album["caption"], album["images"],
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture a photo (or image document) as a note. A caption becomes the note
    text (and can carry a reminder). Albums are buffered and saved as one note."""
    msg = update.message
    user_id, tz, locale, _ = await load_ctx(update)
    if user_id is None:
        await msg.reply_text(t(locale, "error_generic"))
        return

    try:
        image = await _download_photo(msg)
    except Exception:
        logger.exception("Photo download failed")
        await msg.reply_text(t(locale, "error_generic"))
        return
    caption = (msg.caption or "").strip()

    group_id = msg.media_group_id
    if not group_id:                     # a single photo — capture immediately
        await _save_media_note(msg, user_id, tz, locale, caption, [image])
        return

    # Part of an album: buffer, then (re)arm the debounced flush. The caption
    # rides on one item of the group; keep the first non-empty one we see.
    album = pending_albums.get(group_id)
    if album is None:
        album = pending_albums[group_id] = {
            "msg": msg, "user_id": user_id, "tz": tz, "locale": locale,
            "caption": caption, "images": [], "task": None,
        }
    album["images"].append(image)
    if caption and not album["caption"]:
        album["caption"] = caption
    if album["task"]:
        album["task"].cancel()
    album["task"] = asyncio.create_task(_flush_album(group_id))


async def on_enrich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🧠 Enrich button — run the deferred metadata pass via the API service."""
    query = update.callback_query
    await query.answer()
    user_id, tz, locale, _ = await load_ctx(update)
    note_id = int(query.data.split(":")[1])
    base = query.message.text or ""

    if user_id is None:
        await query.edit_message_text(base, reply_markup=_capture_keyboard(note_id, locale))
        return

    # Show a friendly in-progress state and drop the button (enrichment does an
    # embedding + LLM call, so it isn't instant; this also prevents double taps).
    try:
        await query.edit_message_text(f"{base}\n\n{t(locale, 'enriching')}")
    except Exception:
        pass

    meta = await api.enrich_note(note_id, user_id)
    if not meta:
        # Restore the original message + Enrich button so the user can retry.
        await query.edit_message_text(base, reply_markup=_capture_keyboard(note_id, locale))
        return

    await query.edit_message_text(
        f"{base}\n\n{_meta_line(meta)}",
        reply_markup=_enriched_keyboard(note_id, locale),
    )


async def on_atomize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✂️ Atomize — split a note into atomic notes, each posted as its own note
    with the same actions. Non-destructive: the original note is left as-is."""
    query = update.callback_query
    await query.answer()      # dismiss the spinner up front (the split LLM call isn't instant)
    user_id, tz, locale, _ = await load_ctx(update)
    note_id = int(query.data.split(":")[1])
    if user_id is None:
        await query.message.reply_text(t(locale, "error_generic"))
        return
    atoms = await api.atomize_note(note_id, user_id)
    if not atoms:
        await query.message.reply_text(t(locale, "atomize_single"))
        return
    for a in atoms:
        await query.message.reply_text(
            t(locale, "saved") + "\n\n" + a["text"],
            reply_markup=_capture_keyboard(a["note_id"], locale),
        )


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✖️ Cancel — delete a freshly captured/atomized note. Guarded server-side:
    only notes with no metadata and no links are removed, so an accidental tap on
    an enriched or linked note is refused."""
    query = update.callback_query
    note_id = int(query.data.split(":")[1])
    _, _, locale, _ = await load_ctx(update)
    ok, deleted = await api.delete_note(note_id)
    if deleted:
        await query.answer()
        try:
            await query.edit_message_text(t(locale, "note_deleted"))
        except Exception:
            logger.exception("Failed to update message after delete")
    elif ok:
        await query.answer(t(locale, "cancel_blocked"), show_alert=True)
    else:
        await query.answer(t(locale, "error_generic"), show_alert=True)


async def on_polish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✨ Polish — clean up the note's wording and punctuation via the LLM (no
    invention), then show the result (chunks are re-embedded server-side)."""
    query = update.callback_query
    await query.answer()      # the LLM call isn't instant; dismiss the spinner
    _, _, locale, _ = await load_ctx(update)
    note_id = int(query.data.split(":")[1])
    text = await api.polish_note(note_id)
    if not text:
        await query.message.reply_text(t(locale, "error_generic"))
        return
    try:
        await query.edit_message_text(
            t(locale, "polished") + "\n\n" + text,
            reply_markup=_capture_keyboard(note_id, locale),
        )
    except Exception:
        # e.g. "message is not modified" when the note was already clean.
        logger.info("Polish: message unchanged for note %s", note_id)


async def on_path(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📁 Change-path picker — list the user's known paths (via the API) and move
    the note to the tapped one."""
    query = update.callback_query
    parts = query.data.split(":")  # p:<action>:<note_id>[:<idx>]
    action = parts[1]
    note_id = int(parts[2])
    user_id, tz, locale, _ = await load_ctx(update)
    if user_id is None:
        await query.answer(t(locale, "error_generic"), show_alert=True)
        return

    if action == "open":
        paths = await api.known_paths(user_id)
        if not paths:
            await query.answer(t(locale, "path_none"), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(_path_picker_keyboard(note_id, paths, locale))
    elif action == "set":
        idx = int(parts[3])
        paths = await api.known_paths(user_id)  # re-fetch: stable order → idx maps back
        if idx >= len(paths):
            await query.answer()
            await query.edit_message_reply_markup(_enriched_keyboard(note_id, locale))
            return
        path = paths[idx]
        meta, _ = await api.set_note_path(note_id, path)
        await query.answer(t(locale, "path_set", path=path))
        if meta:
            base = (query.message.text or "").rsplit("\n\n", 1)[0]
            await query.edit_message_text(
                f"{base}\n\n{_meta_line(meta)}",
                reply_markup=_enriched_keyboard(note_id, locale),
            )
        else:
            await query.edit_message_reply_markup(_enriched_keyboard(note_id, locale))
    elif action == "new":
        # Ask the user to type a brand-new path (ForceReply); the reply is picked
        # up in handle_message via the pending_new_path map.
        await query.answer()
        base = (query.message.text or "").rsplit("\n\n", 1)[0]
        prompt = await query.message.reply_text(
            t(locale, "path_new_prompt"), reply_markup=ForceReply(selective=True),
        )
        if len(pending_new_path) > 200:      # bound the map (unanswered prompts)
            pending_new_path.clear()
        pending_new_path[prompt.message_id] = {
            "note_id": note_id,
            "chat_id": query.message.chat_id,
            "msg_id": query.message.message_id,
            "base": base,
        }
    elif action == "back":
        await query.answer()
        await query.edit_message_reply_markup(_enriched_keyboard(note_id, locale))


def _enriched_keyboard(note_id: int, locale: str) -> InlineKeyboardMarkup:
    """Buttons shown on an enriched note: change its path, or link it to others."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(locale, "btn_change_path"), callback_data=f"p:open:{note_id}")],
        [InlineKeyboardButton(t(locale, "btn_link"), callback_data=f"l:open:{note_id}")],
    ])


def _path_picker_keyboard(note_id: int, paths: list[str], locale: str) -> InlineKeyboardMarkup:
    """A row per known path (tap to move the note there), plus Back."""
    rows = [
        [InlineKeyboardButton(("📁 " + p)[:60], callback_data=f"p:set:{note_id}:{i}")]
        for i, p in enumerate(paths)
    ]
    rows.append([InlineKeyboardButton(t(locale, "btn_new_path"), callback_data=f"p:new:{note_id}")])
    rows.append([InlineKeyboardButton(t(locale, "btn_back"), callback_data=f"p:back:{note_id}")])
    return InlineKeyboardMarkup(rows)


def _link_picker_keyboard(from_note_id: int, cands: list[dict], locale: str) -> InlineKeyboardMarkup:
    rows = []
    for c in cands:
        mark = "🔗 " if c.get("linked") else "• "
        title = (c.get("title") or "note")[:40]
        rows.append([InlineKeyboardButton(
            mark + title, callback_data=f"l:tog:{from_note_id}:{c['note_id']}"
        )])
    rows.append([InlineKeyboardButton(t(locale, "btn_close"), callback_data=f"l:close:{from_note_id}")])
    return InlineKeyboardMarkup(rows)


def _toggle_keyboard(markup: InlineKeyboardMarkup, tapped_cb: str, linked: bool) -> InlineKeyboardMarkup:
    """Rebuild the picker keyboard, flipping only the tapped candidate's mark."""
    mark = "🔗 " if linked else "• "
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for b in row:
            if b.callback_data == tapped_cb:
                title = b.text.split(" ", 1)[1] if " " in b.text else b.text
                new_row.append(InlineKeyboardButton(mark + title, callback_data=b.callback_data))
            else:
                new_row.append(InlineKeyboardButton(b.text, callback_data=b.callback_data))
        rows.append(new_row)
    return InlineKeyboardMarkup(rows)


async def on_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔗 Link picker — open a candidate list; tap a note to connect/disconnect."""
    query = update.callback_query
    parts = query.data.split(":")  # l:<action>:<from>[:<cand>]
    action = parts[1]
    user_id, tz, locale, _ = await load_ctx(update)
    if user_id is None:
        await query.answer(t(locale, "error_generic"), show_alert=True)
        return

    if action == "open":
        from_id = int(parts[2])
        cands = await api.link_candidates(user_id, from_id)
        if not cands:
            await query.answer(t(locale, "link_none"), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(_link_picker_keyboard(from_id, cands, locale))
    elif action == "tog":
        await query.answer()
        from_id, cand_id = int(parts[2]), int(parts[3])
        linked = await api.toggle_link(from_id, cand_id)
        await query.edit_message_reply_markup(
            _toggle_keyboard(query.message.reply_markup, query.data, linked)
        )
    elif action == "close":
        await query.answer()
        from_id = int(parts[2])
        await query.edit_message_reply_markup(_enriched_keyboard(from_id, locale))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/search <query> — return the agenda-aware RAG answer over stored notes."""
    user_id, tz, locale, _ = await load_ctx(update)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(t(locale, "search_usage"))
        return
    if user_id is None:
        await update.message.reply_text(t(locale, "error_generic"))
        return
    # Timezone and language are resolved server-side from user_id.
    reply = await api.search(user_id, query)
    await update.message.reply_text(reply or t(locale, "search_none"))


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/timezone [IANA name] — show or set the user's timezone."""
    user_id, tz, locale, settings = await load_ctx(update)
    if not context.args:
        current = settings.get("timezone") or f"{DEFAULT_TZ} (default)"
        await update.message.reply_text(t(locale, "tz_current", tz=current))
        return
    if user_id is None:
        await update.message.reply_text(t(locale, "error_generic"))
        return
    ok, err = await api.set_timezone(user_id, context.args[0])
    if not ok:
        key = "tz_unknown" if err == "invalid" else "error_generic"
        await update.message.reply_text(t(locale, key))
        return
    await update.message.reply_text(t(locale, "tz_set", tz=context.args[0]))


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/language [uk|en] — show or set the user's language."""
    user_id, tz, locale, _ = await load_ctx(update)
    if not context.args:
        await update.message.reply_text(t(locale, "lang_current", lang=locale))
        return
    if user_id is None:
        await update.message.reply_text(t(locale, "error_generic"))
        return
    lang, err = await api.set_language(user_id, context.args[0])
    if lang is None:
        key = "lang_unknown" if err == "invalid" else "error_generic"
        await update.message.reply_text(t(locale, key))
        return
    await update.message.reply_text(t(lang, "lang_set", lang=lang))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — welcome message."""
    _, _, locale, _ = await load_ctx(update)
    await update.message.reply_text(t(locale, "start"))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — overview of functionality."""
    _, _, locale, _ = await load_ctx(update)
    await update.message.reply_text(t(locale, "help"))


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/info — a primer on the PARA folders and the Zettelkasten method, with the
    button that achieves each principle. Assembled from two localized parts."""
    _, _, locale, _ = await load_ctx(update)
    await update.message.reply_text(
        t(locale, "info_para") + "\n\n" + t(locale, "info_zettel")
    )


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/user — show the user's current settings."""
    _, tz, locale, settings = await load_ctx(update)
    tz_disp = settings.get("timezone") or f"{DEFAULT_TZ} (default)"
    count = settings.get("active_reminders", 0)
    await update.message.reply_text(
        t(locale, "user_settings", lang=locale, tz=tz_disp, count=count)
    )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reminders — list the user's upcoming reminders."""
    user_id, tz, locale, _ = await load_ctx(update)
    if user_id is None:
        await update.message.reply_text(t(locale, "error_generic"))
        return
    rows = await api.list_reminders(user_id)
    if not rows:
        await update.message.reply_text(t(locale, "reminders_none"))
        return
    lines = [
        f"{i}. {datetime.fromisoformat(r['remind_at']).astimezone(tz):%Y-%m-%d %H:%M} — {r['text']}"
        for i, r in enumerate(rows, 1)
    ]
    await update.message.reply_text(t(locale, "reminders_header") + "\n" + "\n".join(lines))


def _snooze_keyboard(reminder_id: int, locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(locale, "btn_snooze_10m"), callback_data=f"r:snz:10:{reminder_id}"),
                InlineKeyboardButton(t(locale, "btn_snooze_1h"), callback_data=f"r:snz:60:{reminder_id}"),
                InlineKeyboardButton(t(locale, "btn_snooze_tomorrow"), callback_data=f"r:snz:tomorrow:{reminder_id}"),
            ],
            [InlineKeyboardButton(t(locale, "btn_done"), callback_data=f"r:done:{reminder_id}")],
        ]
    )


async def on_button_handle_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Cancel / Snooze / Done inline buttons (all via the API)."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")  # r:<action>:...:<id>
    action, reminder_id = parts[1], int(parts[-1])
    user_id, tz, locale, _ = await load_ctx(update)
    base = query.message.text or "Reminder"

    if action == "cancel":
        await api.cancel_reminder(reminder_id)
        await query.edit_message_text(base + "\n\n" + t(locale, "canceled"))
    elif action == "done":
        await api.complete_reminder(reminder_id)
        await query.edit_message_text(base + "\n\n" + t(locale, "done"))
    elif action == "snz":
        remind_at = await api.snooze_reminder(reminder_id, user_id, parts[2])
        if not remind_at:
            await query.edit_message_text(base + "\n\n" + t(locale, "error_generic"))
            return
        when = datetime.fromisoformat(remind_at).astimezone(tz)
        await query.edit_message_text(
            base + "\n\n" + t(locale, "snoozed", when=f"{when:%Y-%m-%d %H:%M}")
        )


def _humanize_ago(delay: timedelta) -> str:
    """Compact 'X ago' magnitude (m/h/d), or '' if not past the late threshold."""
    seconds = int(delay.total_seconds())
    if seconds < LATE_NOTE_SECONDS:
        return ""
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


async def _dispatch_due_reminders(app):
    """Claim due reminders via the API and deliver them; mark each 'done' only
    after it sends, otherwise hand it back for retry. Delivery is the bot's job;
    claiming/state lives behind the API."""
    now = datetime.now(timezone.utc)
    for r in await api.claim_due_reminders():
        reminder_id = r["reminder_id"]
        chat_id = r.get("chat_id")
        locale = r.get("locale") or i18n.DEFAULT_LOCALE
        if chat_id is None:
            logger.warning("Reminder %s has no chat_id; deferring", reminder_id)
            await api.retry_reminder(reminder_id)
            continue
        ago = _humanize_ago(now - datetime.fromisoformat(r["remind_at"]))
        note = t(locale, "reminder_late", ago=ago) if ago else ""
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=t(locale, "reminder_fire", note=note, text=r["text"]),
                reply_markup=_snooze_keyboard(reminder_id, locale),
            )
            await api.complete_reminder(reminder_id)
        except Exception:
            # Hand it back so the next tick retries it (it's currently 'sending').
            logger.exception("Failed to send reminder %s", reminder_id)
            await api.retry_reminder(reminder_id)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global safety net: log any unhandled handler exception with context and
    show the user a friendly message instead of failing silently."""
    logger.exception("Unhandled error while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        locale = i18n.DEFAULT_LOCALE
        try:
            _, _, locale, _ = await load_ctx(update)
        except Exception:
            pass
        try:
            await update.effective_message.reply_text(t(locale, "error_generic"))
        except Exception:
            logger.exception("Failed to deliver error message to user")


async def _reminder_loop(app):
    """Poll for due reminders every REMINDER_POLL_SECONDS."""
    while True:
        try:
            await _dispatch_due_reminders(app)
        except Exception:
            logger.exception("Reminder loop error")
        await asyncio.sleep(REMINDER_POLL_SECONDS)


# Commands shown in the Telegram menu (order matters), by key.
MENU_COMMANDS = ["start", "help", "info", "search", "reminders", "timezone", "language", "user"]


def _menu(locale: str) -> list[BotCommand]:
    return [BotCommand(name, t(locale, f"cmd_{name}")) for name in MENU_COMMANDS]


async def _post_init(app):
    app.create_task(_reminder_loop(app))
    logger.info("Reminder dispatcher started (every %ss).", REMINDER_POLL_SECONDS)
    # Default menu (English) + a Ukrainian menu for uk Telegram clients.
    await app.bot.set_my_commands(_menu("en"))
    await app.bot.set_my_commands(_menu("uk"), language_code="uk")
    logger.info("Bot command menu set.")
    # Menu button that opens the note-browser mini app (when a URL is configured).
    if config.WEBAPP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Browse", web_app=WebAppInfo(url=config.WEBAPP_URL)
                )
            )
            logger.info("Web app menu button set -> %s", config.WEBAPP_URL)
        except Exception:
            logger.exception("Failed to set web app menu button")
    else:
        logger.info("WEBAPP_URL not set — web app menu button disabled.")


def main():
    # The bot is a thin client: no schema migrations (owned by the API service)
    # and no database/storage access — everything goes through the API gateway.
    if not api.configured:
        logger.warning(
            "API_BASE_URL is not set — the bot cannot reach the API gateway; "
            "all domain calls will fail until it is configured."
        )
    else:
        logger.info("API gateway: %s", config.API_BASE_URL)
    app = Application.builder().token(config.BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("user", user_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("timezone", timezone_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CallbackQueryHandler(on_button_handle_reminder, pattern=r"^r:"))
    app.add_handler(CallbackQueryHandler(on_enrich, pattern=r"^e:"))
    app.add_handler(CallbackQueryHandler(on_atomize, pattern=r"^a:"))
    app.add_handler(CallbackQueryHandler(on_cancel, pattern=r"^c:"))
    app.add_handler(CallbackQueryHandler(on_polish, pattern=r"^f:"))
    app.add_handler(CallbackQueryHandler(on_path, pattern=r"^p:"))
    app.add_handler(CallbackQueryHandler(on_link, pattern=r"^l:"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
