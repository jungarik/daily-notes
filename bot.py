"""
Telegram bot layer.

Wires Telegram handlers to the service modules: transcription (voice → text),
semantic (chunking / embeddings / search), note_store (persistence), and the
reminders parser + store. Keeps no business logic of its own beyond formatting
and dispatch.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import i18n
import enrichment
import reminders
import semantic
import storage
import timeparser
import note_store
import chunk_store
import transcription
import user_store
import reminder_store
from i18n import t
from config import (
    DEFAULT_TZ,
    REMINDER_POLL_SECONDS,
    SENDING_STALE_SECONDS,
    LATE_NOTE_SECONDS,
)
from migrate import run_migrations
from reminder_store import (
    create_reminder,
    claim_due_reminders,
    set_status,
    postpone,
)
from telegram import (
    Update,
    BotCommand,
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


def _capture(user_id: int, username: str, text: str,
             source_type: str = "text", audio_key: str | None = None,
             audio_mime: str | None = None) -> int:
    """Fast path: chunk + embed + save the note (no metadata yet). Returns id."""
    chunks = semantic.build_chunks(text)
    note_id = note_store.save_note(
        user_id, username, text,
        source_type=source_type, audio_key=audio_key, audio_mime=audio_mime,
    )
    chunk_store.save_chunks(note_id, chunks)
    logger.info("Captured note %s (%d chunk(s))", note_id, len(chunks))
    return note_id


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
    """Fast path: if the note is time-bearing, store a reminder and confirm."""
    remind_at = reminders.extract_reminder(text, datetime.now(tz))
    if not remind_at:
        return
    reminder_id = create_reminder(note_id, user_id, remind_at)
    when = remind_at.astimezone(tz)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"r:cancel:{reminder_id}")]]
    )
    await msg.reply_text(
        t(locale, "reminder_set", when=f"{when:%Y-%m-%d %H:%M}", tz=when.tzname()),
        reply_markup=keyboard,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture a text note immediately; offer on-demand enrichment."""
    msg = update.message
    user_id = user_id_of(update)
    tz, locale = user_tz(user_id), user_locale(user_id)
    note_id = _capture(user_id, msg.from_user.username, msg.text)
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
    audio_key = storage.upload_audio(audio_bytes, content_type=mime)
    note_id = _capture(
        user_id, msg.from_user.username, text,
        source_type="voice", audio_key=audio_key, audio_mime=mime,
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

    text = note_store.get_text(note_id)
    if not text:
        return

    embedding = semantic.embed(text)
    similar = chunk_store.similar_notes(user_id, embedding, exclude_note_id=note_id)
    meta = enrichment.enrich(
        text,
        known_paths=note_store.list_paths(user_id),
        known_tags=note_store.list_tags(user_id),
        similar_notes=similar,
    )
    note_store.set_metadata(
        note_id, meta["type"], meta["title"], meta["priority"],
        meta["tags"], meta["path"],
    )
    logger.info("Enriched note %s -> %s '%s'", note_id, meta["type"], meta["title"])
    await query.edit_message_text(f"{query.message.text}\n\n{_meta_line(meta)}")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/search <query> — return semantically similar stored notes."""
    user_id = user_id_of(update)
    locale = user_locale(user_id)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(t(locale, "search_usage"))
        return

    tz = user_tz(user_id)
    agenda_range = timeparser.parse_agenda(query, datetime.now(tz))
    agenda_start, agenda_end = agenda_range[:2] if agenda_range else (None, None)
    reply = semantic.answer(
        user_id, query,
        remind_start=agenda_start, remind_end=agenda_end,
        language=locale, tz=tz,
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
    run_migrations()
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
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
