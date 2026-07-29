"""
Simple Telegram bot POC.

Captures incoming text messages and stores them in PostgreSQL with a timestamp.
Each message is split into chunks; every chunk is embedded with OpenAI and stored
in message_chunks (pgvector), which powers semantic search via /search.
"""

import os
import logging

import psycopg
from psycopg.types.json import Json
from openai import OpenAI
from dotenv import load_dotenv

from migrate import run_migrations
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

openai_client = OpenAI()  # reads OPENAI_API_KEY from the environment


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


def save_message(chat_id: int, username: str, text: str):
    """Store the message, then its embedded chunks linked by message_id."""
    chunks = chunk_text(text)
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (chat_id, username, text)
                VALUES (%s, %s, %s)
                RETURNING id;
                """,
                (chat_id, username, text),
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store every incoming text message and its chunks."""
    msg = update.message
    n = save_message(msg.chat_id, msg.from_user.username, msg.text)
    logger.info("Saved message from %s (%d chunk(s))", msg.from_user.username, n)
    await msg.reply_text("Saved ✅")


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
