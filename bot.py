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
import logging

import psycopg
from psycopg.types.json import Json
from openai import OpenAI
from dotenv import load_dotenv

from migrate import run_migrations
from reminders import extract_reminder
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
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
    return len(chunks)


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


def reminder_preview(text: str) -> str:
    """Detection-only preview line (nothing is scheduled yet)."""
    rem = extract_reminder(text)
    if rem.is_reminder and rem.remind_at:
        return f"\n\n📅 Looks like a reminder for {rem.remind_at:%Y-%m-%d %H:%M}"
    return ""


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store every incoming text message and its chunks."""
    msg = update.message
    n = save_message(msg.chat_id, msg.from_user.username, msg.text)
    logger.info("Saved message from %s (%d chunk(s))", msg.from_user.username, n)
    await msg.reply_text("Saved ✅" + reminder_preview(msg.text))


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe a voice note, store the transcript + raw audio, and chunk it."""
    msg = update.message
    voice = msg.voice
    tg_file = await voice.get_file()
    audio_bytes = bytes(await tg_file.download_as_bytearray())

    try:
        text = transcribe(audio_bytes)
    except Exception:
        logger.exception("Transcription failed")
        await msg.reply_text("Transcription failed — please try again later.")
        return

    if not text:
        await msg.reply_text("Couldn't transcribe that voice note 🤔")
        return

    n = save_message(
        msg.chat_id,
        msg.from_user.username,
        text,
        source_type="voice",
        audio=audio_bytes,
        audio_mime=voice.mime_type or "audio/ogg",
    )
    logger.info("Saved voice from %s (%d chunk(s))", msg.from_user.username, n)
    await msg.reply_text(f"Transcribed & saved ✅\n\n{text}" + reminder_preview(text))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/search <query> — return semantically similar stored notes."""
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /search your query here")
        return

    results = search_messages(update.message.chat_id, embed(query))
    if not results:
        await update.message.reply_text("No matching notes yet.")
        return

    lines = [
        f"• {text}  ({created.strftime('%Y-%m-%d %H:%M')})"
        for text, created, _distance in results
    ]
    await update.message.reply_text("Closest notes:\n" + "\n".join(lines))


def main():
    run_migrations()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
