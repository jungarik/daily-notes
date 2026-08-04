"""Central configuration — every environment variable is read here, once."""

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# --- Telegram / database ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

# --- Embeddings & chunking (semantic search) ---
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")  # 1536 dims
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "500"))       # characters per chunk
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "50"))  # shared chars between chunks

# --- Voice transcription (OpenAI) ---
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_STT_LANGUAGE = os.environ.get("OPENAI_STT_LANGUAGE") or None
OPENAI_STT_PROMPT = os.environ.get(
    "OPENAI_STT_PROMPT",
    "Голосові нотатки українською та англійською: нагадування, завдання, "
    "зустрічі, плани. Voice notes in Ukrainian and English: reminders, tasks, "
    "meetings, plans.",
)

# --- Reminders ---
REMINDER_TZ = os.environ.get("REMINDER_TZ", "Europe/Kyiv")
DEFAULT_TZ = ZoneInfo(REMINDER_TZ)
REMINDER_LLM_MODEL = os.environ.get("REMINDER_LLM_MODEL", "gpt-4o-mini")
# How many units an indefinite quantity ("кілька"/"a few") means, e.g. "через
# кілька хвилин" → in REMINDER_FEW_COUNT minutes.
REMINDER_FEW_COUNT = int(os.environ.get("REMINDER_FEW_COUNT", "5"))
# What a vague "later"/"пізніше" resolves to. Duration like 10m / 2h / 1d.
REMINDER_LATER = os.environ.get("REMINDER_LATER", "10m")
REMINDER_POLL_SECONDS = int(os.environ.get("REMINDER_POLL_SECONDS", "30"))
# A reminder stuck mid-send (crash) is reclaimed after this many seconds.
SENDING_STALE_SECONDS = int(os.environ.get("REMINDER_SENDING_STALE_SECONDS", "120"))
# Show a "(was due X ago)" note when a reminder fires later than this.
LATE_NOTE_SECONDS = 60

# --- Localization ---
BOT_DEFAULT_LOCALE = os.environ.get("BOT_DEFAULT_LOCALE", "en")
