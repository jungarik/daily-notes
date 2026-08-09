"""
Telegram bot layer — a thin client adapter.

Translates Telegram updates into domain-service calls and formats the replies.
It holds no business logic: capture, reminder detection, enrichment, link
selection and search/answer all live in the service layer (`note_service`,
`search_service`, `links`), so every client (bot, web, iOS, future API) shares
the same behaviour. Only Telegram specifics live here — keyboards, message
formatting, command wiring, reminder delivery.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import i18n
from api_client import ApiClient
from services import links
from stores import link_store
import storage
from services import reminders
from services import transcription
from stores import user_store
from stores import reminder_store
from services import note_service
from services import search_service
from i18n import t
from config import (
    DEFAULT_TZ,
    REMINDER_POLL_SECONDS,
    SENDING_STALE_SECONDS,
    LATE_NOTE_SECONDS,
)
from stores.reminder_store import (
    claim_due_reminders,
    set_status,
    postpone,
)
from telegram import (
    Update,
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

# Client for the API service (used for the change-path flow; other handlers still
# call services in-process during the transition to the API gateway).
api = ApiClient()

# Pending "New path…" prompts: ForceReply prompt message_id -> the note + the
# original enriched message to refresh once the user replies with a path.
pending_new_path: dict[int, dict] = {}


def user_id_of(update: Update) -> int:
    """Resolve the internal user id for a Telegram update (create on first sight)."""
    return user_store.get_or_create_user(update.effective_chat.id)


def user_tz(user_id: int) -> ZoneInfo:
    """The user's timezone, or the default if unset/invalid."""
    name = user_store.get_timezone(user_id)
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            logger.warning("Invalid stored timezone %r for user %s", name, user_id)
    return DEFAULT_TZ


def user_locale(user_id: int) -> str:
    """The user's language code ('en'/'uk'), or the default."""
    return i18n.normalize(user_store.get_language(user_id)) or i18n.DEFAULT_LOCALE


NOTE_ICONS = {
    "idea": "💡", "task": "✅", "reminder": "⏰",
    "note": "📝", "question": "❓", "link": "🔗",
}


def _enrich_keyboard(note_id: int, locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(locale, "btn_enrich"), callback_data=f"e:{note_id}")]]
    )


def _meta_line(meta: dict) -> str:
    icon = NOTE_ICONS.get(meta["type"], "📝")
    parts = [f"{icon} {meta['title']}"]
    if meta["path"]:
        parts.append("📁 " + meta["path"])
    if meta["tags"]:
        parts.append("🏷 " + ", ".join(meta["tags"]))
    parts.append("⚡ " + meta["priority"])
    return "\n".join(parts)


async def _offer_reminder(msg, user_id: int, note_id: int, text: str, tz, locale: str):
    """If the note is time-bearing, ask the service to store a reminder and
    confirm it to the user. Formatting only — detection lives in the service."""
    result = reminders.detect_reminder(note_id, user_id, text, datetime.now(tz))
    if not result:
        return
    reminder_id, remind_at = result
    when = remind_at.astimezone(tz)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"r:cancel:{reminder_id}")]]
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
    locale = user_locale(user_id_of(update))
    meta, err = await api.set_note_path(info["note_id"], msg.text.strip())
    if err:
        await msg.reply_text(t(locale, "path_invalid", roots=", ".join(config.ROOT_FOLDERS)))
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
    user_id = user_id_of(update)
    tz, locale = user_tz(user_id), user_locale(user_id)
    note_id = note_service.capture_note(user_id, msg.from_user.username, msg.text)
    await msg.reply_text(t(locale, "saved"), reply_markup=_enrich_keyboard(note_id, locale))
    await _offer_reminder(msg, user_id, note_id, msg.text, tz, locale)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe a voice note, then capture it like a text note."""
    msg = update.message
    voice = msg.voice
    user_id = user_id_of(update)
    tz, locale = user_tz(user_id), user_locale(user_id)
    tg_file = await voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    try:
        text = transcription.transcribe(audio_bytes)
    except Exception:
        logger.exception("Transcription failed")
        await msg.reply_text(t(locale, "transcribe_failed"))
        return

    if not text:
        await msg.reply_text(t(locale, "transcribe_empty"))
        return

    mime = voice.mime_type or "audio/ogg"
    note_id = note_service.capture_note(
        user_id, msg.from_user.username, text,
        source_type="voice", audio_bytes=audio_bytes, mime=mime,
    )
    await msg.reply_text(
        t(locale, "transcribed_saved", text=text),
        reply_markup=_enrich_keyboard(note_id, locale),
    )
    await _offer_reminder(msg, user_id, note_id, text, tz, locale)


async def on_enrich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🧠 Enrich button — run the deferred metadata pass with similar-notes context."""
    query = update.callback_query
    await query.answer()
    user_id = user_id_of(update)
    note_id = int(query.data.split(":")[1])

    meta = note_service.enrich_note(user_id, note_id)
    if not meta:
        return

    locale = user_locale(user_id)
    await query.edit_message_text(
        f"{query.message.text}\n\n{_meta_line(meta)}",
        reply_markup=_enriched_keyboard(note_id, locale),
    )


async def on_path(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📁 Change-path picker — list the user's known paths (via the API) and move
    the note to the tapped one."""
    query = update.callback_query
    parts = query.data.split(":")  # p:<action>:<note_id>[:<idx>]
    action = parts[1]
    note_id = int(parts[2])
    user_id = user_id_of(update)
    locale = user_locale(user_id)

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
        mark = "✅ " if link_store.is_linked(from_note_id, c["note_id"]) else "◻️ "
        title = (c["title"] or "note")[:40]
        rows.append([InlineKeyboardButton(
            mark + title, callback_data=f"l:tog:{from_note_id}:{c['note_id']}"
        )])
    rows.append([InlineKeyboardButton(t(locale, "btn_close"), callback_data=f"l:close:{from_note_id}")])
    return InlineKeyboardMarkup(rows)


def _toggle_keyboard(markup: InlineKeyboardMarkup, tapped_cb: str, linked: bool) -> InlineKeyboardMarkup:
    """Rebuild the picker keyboard, flipping only the tapped candidate's mark."""
    mark = "✅ " if linked else "◻️ "
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
    user_id = user_id_of(update)
    locale = user_locale(user_id)

    if action == "open":
        from_id = int(parts[2])
        cands = links.candidates(user_id, from_id)
        if not cands:
            await query.answer(t(locale, "link_none"), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(_link_picker_keyboard(from_id, cands, locale))
    elif action == "tog":
        await query.answer()
        from_id, cand_id = int(parts[2]), int(parts[3])
        linked = links.toggle_link(from_id, cand_id)
        await query.edit_message_reply_markup(
            _toggle_keyboard(query.message.reply_markup, query.data, linked)
        )
    elif action == "close":
        await query.answer()
        from_id = int(parts[2])
        await query.edit_message_reply_markup(_enriched_keyboard(from_id, locale))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/search <query> — return semantically similar stored notes."""
    user_id = user_id_of(update)
    locale = user_locale(user_id)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(t(locale, "search_usage"))
        return

    tz = user_tz(user_id)
    reply = search_service.answer(
        user_id, query, datetime.now(tz), language=locale, tz=tz,
    )
    await update.message.reply_text(reply or t(locale, "search_none"))


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/timezone [IANA name] — show or set the user's timezone."""
    user_id = user_id_of(update)
    locale = user_locale(user_id)
    if not context.args:
        current = user_store.get_timezone(user_id) or f"{DEFAULT_TZ} (default)"
        await update.message.reply_text(t(locale, "tz_current", tz=current))
        return
    name = context.args[0]
    try:
        ZoneInfo(name)
    except Exception:
        await update.message.reply_text(t(locale, "tz_unknown"))
        return
    user_store.set_timezone(user_id, name)
    await update.message.reply_text(t(locale, "tz_set", tz=name))


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/language [uk|en] — show or set the user's language."""
    user_id = user_id_of(update)
    if not context.args:
        current = user_locale(user_id)
        await update.message.reply_text(t(current, "lang_current", lang=current))
        return
    lang = i18n.normalize(context.args[0])
    if lang not in i18n.SUPPORTED:
        await update.message.reply_text(t(user_locale(user_id), "lang_unknown"))
        return
    user_store.set_language(user_id, lang)
    await update.message.reply_text(t(lang, "lang_set", lang=lang))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start — welcome message."""
    await update.message.reply_text(t(user_locale(user_id_of(update)), "start"))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — overview of functionality."""
    await update.message.reply_text(t(user_locale(user_id_of(update)), "help"))


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/user — show the user's current settings."""
    user_id = user_id_of(update)
    locale = user_locale(user_id)
    tz = user_store.get_timezone(user_id) or f"{DEFAULT_TZ} (default)"
    count = reminder_store.count_active(user_id)
    await update.message.reply_text(
        t(locale, "user_settings", lang=locale, tz=tz, count=count)
    )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reminders — list the user's upcoming reminders."""
    user_id = user_id_of(update)
    locale = user_locale(user_id)
    tz = user_tz(user_id)
    rows = reminder_store.upcoming_reminders(user_id)
    if not rows:
        await update.message.reply_text(t(locale, "reminders_none"))
        return
    lines = [
        f"{i}. {remind_at.astimezone(tz):%Y-%m-%d %H:%M} — {text}"
        for i, (_id, remind_at, text, _status) in enumerate(rows, 1)
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


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Cancel / Snooze / Done inline buttons."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")  # r:<action>:...:<id>
    action, reminder_id = parts[1], int(parts[-1])
    user_id = user_id_of(update)
    locale = user_locale(user_id)
    base = query.message.text or "Reminder"

    if action == "cancel":
        set_status(reminder_id, "canceled")
        await query.edit_message_text(base + "\n\n" + t(locale, "canceled"))
    elif action == "done":
        set_status(reminder_id, "done")
        await query.edit_message_text(base + "\n\n" + t(locale, "done"))
    elif action == "snz":
        tz = user_tz(user_id)
        now = datetime.now(tz)
        if parts[2] == "tomorrow":
            new_time = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            new_time = now + timedelta(minutes=int(parts[2]))
        postpone(reminder_id, new_time)
        await query.edit_message_text(
            base + "\n\n" + t(locale, "snoozed", when=f"{new_time:%Y-%m-%d %H:%M}")
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
    """Claim and send due reminders, marking each 'done' only after it sends."""
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=SENDING_STALE_SECONDS)
    for reminder_id, user_id, chat_id, text, remind_at in claim_due_reminders(now, stale_before):
        locale = user_locale(user_id)
        ago = _humanize_ago(now - remind_at)
        note = t(locale, "reminder_late", ago=ago) if ago else ""
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=t(locale, "reminder_fire", note=note, text=text),
                reply_markup=_snooze_keyboard(reminder_id, locale),
            )
            set_status(reminder_id, "done")
        except Exception:
            # Revert so the next tick retries it (it's currently 'sending').
            logger.exception("Failed to send reminder %s", reminder_id)
            set_status(reminder_id, "scheduled")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Global safety net: log any unhandled handler exception with context and
    show the user a friendly message instead of failing silently."""
    logger.exception("Unhandled error while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            locale = user_locale(user_id_of(update))
        except Exception:
            locale = i18n.DEFAULT_LOCALE
        try:
            await update.effective_message.reply_text(t(locale, "error_generic"))
        except Exception:
            logger.exception("Failed to deliver error message to user")


async def _reminder_loop(app):
    """Poll the DB for due reminders every REMINDER_POLL_SECONDS."""
    while True:
        try:
            await _dispatch_due_reminders(app)
        except Exception:
            logger.exception("Reminder loop error")
        await asyncio.sleep(REMINDER_POLL_SECONDS)


# Commands shown in the Telegram menu (order matters), by key.
MENU_COMMANDS = ["start", "help", "search", "reminders", "timezone", "language", "user"]


def _menu(locale: str) -> list[BotCommand]:
    return [BotCommand(name, t(locale, f"cmd_{name}")) for name in MENU_COMMANDS]


async def _post_init(app):
    app.create_task(_reminder_loop(app))
    logger.info("Reminder dispatcher started (every %ss).", REMINDER_POLL_SECONDS)
    # Default menu (English) + a Ukrainian menu for uk Telegram clients.
    await app.bot.set_my_commands(_menu("en"))
    await app.bot.set_my_commands(_menu("uk"), language_code="uk")
    logger.info("Bot command menu set.")


def main():
    # Schema migrations are owned by the API service (run on its startup), not
    # by client adapters. The bot assumes the schema is already present.
    if storage.is_configured():
        logger.info("Audio storage: enabled (bucket %s).", config.S3_BUCKET)
    else:
        logger.warning(
            "Audio storage: DISABLED — voice audio won't be stored. Missing: %s",
            ", ".join(storage.missing_config()),
        )
    app = Application.builder().token(config.BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("user", user_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("timezone", timezone_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^r:"))
    app.add_handler(CallbackQueryHandler(on_enrich, pattern=r"^e:"))
    app.add_handler(CallbackQueryHandler(on_path, pattern=r"^p:"))
    app.add_handler(CallbackQueryHandler(on_link, pattern=r"^l:"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
