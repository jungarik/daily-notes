"""
Simple Telegram bot POC.

Captures incoming text and voice messages and stores them in PostgreSQL with a
timestamp. Voice notes are transcribed with OpenAI (whisper-1, with a
transcription-context prompt) and the raw audio is kept. Each message's text is
split into chunks; every chunk is embedded with OpenAI and stored in
message_chunks (pgvector), which powers semantic search via /search.
"""

import io
import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Json
from openai import OpenAI
from dotenv import load_dotenv

import i18n
import user_store
from i18n import t
from migrate import run_migrations
from reminders import extract_reminder, DEFAULT_TZ
from reminder_store import (
    create_reminder,
    claim_due_reminders,
    set_status,
    postpone,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

EMBED_MODEL = "text-embedding-3-small"  # 1536 dimensions
CHUNK_SIZE = 500       # characters per chunk
CHUNK_OVERLAP = 50     # characters shared between consecutive chunks
REMINDER_POLL_SECONDS = int(os.environ.get("REMINDER_POLL_SECONDS", "30"))
# A claimed reminder stuck in 'sending' this long is considered abandoned and reclaimed.
SENDING_STALE_SECONDS = int(os.environ.get("REMINDER_SENDING_STALE_SECONDS", "120"))
# Show a "(was due X ago)" note when a reminder fires later than this.
LATE_NOTE_SECONDS = 60

# OpenAI speech-to-text
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
# Optional forced language (ISO-639-1, e.g. "uk"). Empty = auto-detect uk/en.
OPENAI_STT_LANGUAGE = os.environ.get("OPENAI_STT_LANGUAGE") or None
# Transcription context: biases spelling of names/terms the model may mishear.
OPENAI_STT_PROMPT = os.environ.get(
    "OPENAI_STT_PROMPT",
    "Голосові нотатки українською та англійською: нагадування, завдання, "
    "зустрічі, плани. Voice notes in Ukrainian and English: reminders, tasks, "
    "meetings, plans.",
)

openai_client = OpenAI()  # reads OPENAI_API_KEY from the environment


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe Telegram OGG/Opus audio via OpenAI, with transcription context."""
    audio = io.BytesIO(audio_bytes)
    audio.name = "voice.ogg"  # the extension tells the API the input format
    kwargs = {
        "model": OPENAI_STT_MODEL,
        "file": audio,
        "response_format": "text",
    }
    if OPENAI_STT_PROMPT:
        kwargs["prompt"] = OPENAI_STT_PROMPT
    if OPENAI_STT_LANGUAGE:
        kwargs["language"] = OPENAI_STT_LANGUAGE
    result = openai_client.audio.transcriptions.create(**kwargs)
    # response_format="text" returns a plain string; be tolerant either way.
    text = result if isinstance(result, str) else getattr(result, "text", "")
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """Split text into overlapping character windows. Short text stays a single chunk."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def embed(text: str) -> str:
    """Return the embedding as a pgvector-compatible string, e.g. '[0.1, 0.2, ...]'."""
    resp = openai_client.embeddings.create(model=EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def save_message(
    chat_id: int,
    username: str,
    text: str,
    source_type: str = "text",
    audio: bytes | None = None,
    audio_mime: str | None = None,
):
    """Store the message, then its embedded chunks linked by message_id.

    For voice notes, pass source_type='voice' plus the raw audio bytes and MIME
    type; the transcript is what gets chunked and embedded.
    """
    chunks = chunk_text(text)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (chat_id, username, text, source_type, audio, audio_mime)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (chat_id, username, text, source_type, audio, audio_mime),
            )
            message_id = cur.fetchone()[0]
            for i, chunk in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO message_chunks
                        (message_id, chunk_index, content, token_count, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector);
                    """,
                    (message_id, i, chunk, len(chunk.split()),
                     Json({"char_len": len(chunk)}), embed(chunk)),
                )
    return message_id, len(chunks)


def search_messages(chat_id: int, query_embedding: str, limit: int = 5):
    """Return the notes whose closest chunk best matches the query."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.text, m.created_at, MIN(mc.embedding <=> %s::vector) AS distance
                FROM message_chunks mc
                JOIN messages m ON m.id = mc.message_id
                WHERE m.chat_id = %s
                GROUP BY m.id, m.text, m.created_at
                ORDER BY distance
                LIMIT %s;
                """,
                (query_embedding, chat_id, limit),
            )
            return cur.fetchall()


def user_tz(chat_id: int) -> ZoneInfo:
    """The chat's timezone, or the default if unset/invalid."""
    name = user_store.get_timezone(chat_id)
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            logger.warning("Invalid stored timezone %r for chat %s", name, chat_id)
    return DEFAULT_TZ


def user_locale(chat_id: int) -> str:
    """The chat's language code ('en'/'uk'), or the default."""
    return i18n.normalize(user_store.get_language(chat_id)) or i18n.DEFAULT_LOCALE


async def offer_reminder(msg, message_id: int, text: str):
    """If the text parses as a reminder, store it and send a confirmation with a
    Cancel button so the user can undo a misparse before it fires."""
    tz = user_tz(msg.chat_id)
    rem = extract_reminder(text, now=datetime.now(tz))
    if not (rem.is_reminder and rem.remind_at):
        return
    locale = user_locale(msg.chat_id)
    reminder_id = create_reminder(message_id, msg.chat_id, rem.remind_at, rem.text)
    when = rem.remind_at.astimezone(tz)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(locale, "btn_cancel"), callback_data=f"r:cancel:{reminder_id}")]]
    )
    await msg.reply_text(
        t(locale, "reminder_set", when=f"{when:%Y-%m-%d %H:%M}", tz=when.tzname()),
        reply_markup=keyboard,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store every incoming text message and its chunks."""
    msg = update.message
    message_id, n = save_message(msg.chat_id, msg.from_user.username, msg.text)
    logger.info("Saved message from %s (%d chunk(s))", msg.from_user.username, n)
    await msg.reply_text(t(user_locale(msg.chat_id), "saved"))
    await offer_reminder(msg, message_id, msg.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe a voice note, store the transcript + raw audio, and chunk it."""
    msg = update.message
    voice = msg.voice
    tg_file = await voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    locale = user_locale(msg.chat_id)
    try:
        text = transcribe(audio_bytes)
    except Exception:
        logger.exception("Transcription failed")
        await msg.reply_text(t(locale, "transcribe_failed"))
        return

    if not text:
        await msg.reply_text(t(locale, "transcribe_empty"))
        return

    message_id, n = save_message(
        msg.chat_id,
        msg.from_user.username,
        text,
        source_type="voice",
        audio=audio_bytes,
        audio_mime=voice.mime_type or "audio/ogg",
    )
    logger.info("Saved voice from %s (%d chunk(s))", msg.from_user.username, n)
    await msg.reply_text(t(locale, "transcribed_saved", text=text))
    await offer_reminder(msg, message_id, text)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/search <query> — return semantically similar stored notes."""
    locale = user_locale(update.message.chat_id)
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(t(locale, "search_usage"))
        return

    results = search_messages(update.message.chat_id, embed(query))
    if not results:
        await update.message.reply_text(t(locale, "search_none"))
        return

    lines = [
        f"• {text}  ({created.strftime('%Y-%m-%d %H:%M')})"
        for text, created, _distance in results
    ]
    await update.message.reply_text(t(locale, "search_header") + "\n" + "\n".join(lines))


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/timezone [IANA name] — show or set the chat's timezone."""
    chat_id = update.message.chat_id
    locale = user_locale(chat_id)
    if not context.args:
        current = user_store.get_timezone(chat_id) or f"{DEFAULT_TZ} (default)"
        await update.message.reply_text(t(locale, "tz_current", tz=current))
        return
    name = context.args[0]
    try:
        ZoneInfo(name)
    except Exception:
        await update.message.reply_text(t(locale, "tz_unknown"))
        return
    user_store.set_timezone(chat_id, name)
    await update.message.reply_text(t(locale, "tz_set", tz=name))


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/language [uk|en] — show or set the chat's language."""
    chat_id = update.message.chat_id
    if not context.args:
        current = user_locale(chat_id)
        await update.message.reply_text(t(current, "lang_current", lang=current))
        return
    lang = i18n.normalize(context.args[0])
    if lang not in i18n.SUPPORTED:
        await update.message.reply_text(t(user_locale(chat_id), "lang_unknown"))
        return
    user_store.set_language(chat_id, lang)
    await update.message.reply_text(t(lang, "lang_set", lang=lang))


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
    locale = user_locale(query.message.chat_id)
    base = query.message.text or "Reminder"

    if action == "cancel":
        set_status(reminder_id, "canceled")
        await query.edit_message_text(base + "\n\n" + t(locale, "canceled"))
    elif action == "done":
        set_status(reminder_id, "done")
        await query.edit_message_text(base + "\n\n" + t(locale, "done"))
    elif action == "snz":
        tz = user_tz(query.message.chat_id)
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
    for reminder_id, chat_id, text, remind_at in claim_due_reminders(now, stale_before):
        locale = user_locale(chat_id)
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


async def _post_init(app):
    app.create_task(_reminder_loop(app))
    logger.info("Reminder dispatcher started (every %ss).", REMINDER_POLL_SECONDS)


def main():
    run_migrations()
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("timezone", timezone_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^r:"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
