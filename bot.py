"""
Simple Telegram bot POC.
Captures incoming text messages and stores them in PostgreSQL with a timestamp.
"""

import os
import logging

import psycopg
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]


def init_db():
    """Create the messages table if it doesn't exist."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id          SERIAL PRIMARY KEY,
                    chat_id     BIGINT NOT NULL,
                    username    TEXT,
                    text        TEXT NOT NULL,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
    logger.info("Database ready.")


def save_message(chat_id: int, username: str, text: str):
    """Insert one text message into the database."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (chat_id, username, text) VALUES (%s, %s, %s);",
                (chat_id, username, text),
            )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle every incoming text message."""
    msg = update.message
    save_message(msg.chat_id, msg.from_user.username, msg.text)
    logger.info("Saved message from %s", msg.from_user.username)
    await msg.reply_text("Saved ✅")


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
