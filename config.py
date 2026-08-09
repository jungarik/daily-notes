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
# Model that composes the natural-language answer over retrieved chunks (RAG).
ANSWER_LLM_MODEL = os.environ.get("ANSWER_LLM_MODEL", "gpt-4o-mini")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "500"))       # characters per chunk
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "50"))  # shared chars between chunks

# --- Voice transcription (OpenAI) ---
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_STT_LANGUAGE = os.environ.get("OPENAI_STT_LANGUAGE") or None
# Neutral transcription context: it's a personal note (uk or en). Kept generic
# on purpose — reminder/agenda detection is a separate step, so we don't bias the
# transcript toward those words. (An echo of this text is discarded downstream.)
OPENAI_STT_PROMPT = os.environ.get(
    "OPENAI_STT_PROMPT",
    "нагадай, завтра, через, в, годин, хвилин, пізніше, кілька, потім, купити, подзвонити, зустріч, надіслати, повідомлення, нагадування, нагадати, надіслати повідомлення, надіслати нагадування, надіслати нагадування завтра, надіслати нагадування через кілька хвилин, надіслати нагадування через кілька годин, надіслати нагадування через кілька днів, надіслати нагадування пізніше, надіслати нагадування в 10 ранку, надіслати нагадування в 3 години дня, надіслати нагадування в 5 вечора, надіслати нагадування в 7 вечора, надіслати нагадування в 9 вечора",
)

# --- Object storage for voice audio (S3-compatible: Railway bucket, R2, S3) ---
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")  # blank = AWS default
S3_BUCKET = os.environ.get("S3_BUCKET")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
# Real AWS region (e.g. us-east-1) for AWS S3; "auto" for Cloudflare R2.
S3_REGION = os.environ.get("S3_REGION") or None
# Addressing for custom endpoints: "path" (default), "virtual", or "auto".
S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", "path")

# --- Reminders ---
REMINDER_TZ = os.environ.get("REMINDER_TZ", "Europe/Kyiv")
DEFAULT_TZ = ZoneInfo(REMINDER_TZ)
REMINDER_LLM_MODEL = os.environ.get("REMINDER_LLM_MODEL", "gpt-4o-mini")
# Model that enriches each note (type/title/path/tags/priority).
ENRICH_LLM_MODEL = os.environ.get("ENRICH_LLM_MODEL", "gpt-4o")
# How many similar past notes to retrieve as classification context.
ENRICH_SIMILAR_LIMIT = int(os.environ.get("ENRICH_SIMILAR_LIMIT", "8"))
# Max cosine distance for a neighbour to count as "closely related" (0 = identical).
# Beyond this, the enricher is told not to force-fit an existing path.
ENRICH_SIMILAR_MAX_DISTANCE = float(os.environ.get("ENRICH_SIMILAR_MAX_DISTANCE", "0.6"))
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

# --- Vault root folders (default structure) ---
# The predefined top-level folders and what each is for — a single source of
# truth for both the enrichment vocabulary and the folder meanings shown to the
# model. Global for now; may become per-user later.
ROOT_FOLDERS: dict[str, str] = {
    "Inbox": "uncategorized / not yet sorted",
    "Daily_notes": "journal entries and daily logs",
    "Projects": "active efforts with a concrete outcome or deadline",
    "Areas": "ongoing responsibilities to maintain over time",
    "Knowledge": "evergreen reference notes, concepts, how-tos",
    "Resources": "reference material and topics of interest",
    "Archive": "inactive or completed items kept for reference",
}
# Where a note lands when the model can't determine any path.
DEFAULT_ROOT_FOLDER = os.environ.get("DEFAULT_ROOT_FOLDER", "Inbox")

# --- Localization ---
BOT_DEFAULT_LOCALE = os.environ.get("BOT_DEFAULT_LOCALE", "en")

# --- API service (separate Railway deployable) ---
API_TITLE = os.environ.get("API_TITLE", "daily-notes API")
API_VERSION = os.environ.get("API_VERSION", "0.1.0")
# OpenAPI/Swagger docs are off by default; enable for debugging only.
API_DOCS_ENABLED = os.environ.get("API_DOCS_ENABLED", "false").lower() == "true"
# Shared secret for /internal endpoints — defence in depth on top of the private
# network. Leave blank to disable the check (local dev).
API_INTERNAL_TOKEN = os.environ.get("API_INTERNAL_TOKEN")
# Base URL the bot uses to reach the API over Railway's private network, e.g.
# http://daily-notes-api.railway.internal:8080  (blank = bot calls in-process).
API_BASE_URL = os.environ.get("API_BASE_URL")
# Timeout (seconds) for outbound API calls from a client.
API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "10"))
