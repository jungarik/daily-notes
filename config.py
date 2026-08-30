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

# --- Note attachments (media files) ---
# Max number of files that can be attached to a single note.
ATTACHMENT_MAX_COUNT = int(os.environ.get("ATTACHMENT_MAX_COUNT", "10"))
# Max size per attached file, in bytes (default 20 MB).
ATTACHMENT_MAX_BYTES = int(os.environ.get("ATTACHMENT_MAX_BYTES", str(20 * 1024 * 1024)))
# Allowed image MIME types (only images are supported for now).
ATTACHMENT_IMAGE_MIME = {
    m.strip().lower()
    for m in os.environ.get(
        "ATTACHMENT_IMAGE_MIME",
        "image/jpeg,image/png,image/webp,image/gif,image/heic,image/heif",
    ).split(",")
    if m.strip()
}
# How long a presigned attachment URL stays valid (seconds; default 1 hour).
ATTACHMENT_URL_TTL_SECONDS = int(os.environ.get("ATTACHMENT_URL_TTL_SECONDS", "3600"))

# --- Reminders ---
REMINDER_TZ = os.environ.get("REMINDER_TZ", "Europe/Kyiv")
DEFAULT_TZ = ZoneInfo(REMINDER_TZ)
REMINDER_LLM_MODEL = os.environ.get("REMINDER_LLM_MODEL", "gpt-4o-mini")
# Model that splits a multi-idea dump into atomic notes (Zettelkasten).
ATOMIZE_LLM_MODEL = os.environ.get("ATOMIZE_LLM_MODEL", "gpt-4o-mini")
# Model that cleans up a note's wording/punctuation (no invention).
POLISH_LLM_MODEL = os.environ.get("POLISH_LLM_MODEL", "gpt-4o-mini")
# Model that enriches each note (type/title/path/tags/priority).
ENRICH_LLM_MODEL = os.environ.get("ENRICH_LLM_MODEL", "gpt-4o")
# How many similar past notes to retrieve as classification context.
ENRICH_SIMILAR_LIMIT = int(os.environ.get("ENRICH_SIMILAR_LIMIT", "8"))
# Max cosine distance for a neighbour to count as "closely related" (0 = identical).
# Beyond this, the enricher is told not to force-fit an existing path.
ENRICH_SIMILAR_MAX_DISTANCE = float(os.environ.get("ENRICH_SIMILAR_MAX_DISTANCE", "0.6"))

# --- Agentic chat (Web App chat tab) ---
# Model that runs the tool-calling agent loop.
AGENT_MODEL = os.environ.get("AGENT_MODEL", "gpt-4o-mini")
# Max tool-call iterations per user turn (a runaway-loop / cost watchdog).
AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "6"))

# --- Enrichment agent (runs at capture time) ---
# Model + step budget for the tool-using enrichment agent. Defaults to the same
# model as the one-shot enricher.
ENRICH_AGENT_MODEL = os.environ.get("ENRICH_AGENT_MODEL", ENRICH_LLM_MODEL)
ENRICH_AGENT_MAX_STEPS = int(os.environ.get("ENRICH_AGENT_MAX_STEPS", "4"))
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
# Root folders as {i18n key -> English definition}. The KEY is a locale key
# resolved via locales.json to the folder's display name in the user's language;
# that translated name is what the enrichment LLM writes into the note path and
# what gets stored. Definitions stay English (shared across all locales) and are
# the stable anchor + prompt vocabulary. Extend by adding a key here plus its
# translations under each locale in locales.json.
ROOT_FOLDERS: dict[str, str] = {
    "folder_inbox": "uncategorized / not yet sorted",
    "folder_projects": "active efforts with a concrete outcome or deadline",
    "folder_areas": "ongoing responsibilities to maintain over time",
    "folder_resources": "reference material and topics of interest",
    "folder_archive": "inactive or completed items kept for reference",
}
# i18n key of the folder a note lands in when the model can't determine a path.
DEFAULT_ROOT_FOLDER_KEY = os.environ.get("DEFAULT_ROOT_FOLDER_KEY", "folder_inbox")

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

# --- Telegram Mini App (note-browser web app) ---
# Public HTTPS URL of the Mini App's static host (frontend/webapp, deployed via
# Dockerfile.webapp). When set, the bot exposes a Menu Button that opens it.
# Blank = the button stays off.
WEBAPP_URL = os.environ.get("WEBAPP_URL")
# Reject Mini App initData older than this many seconds (replay protection);
# 0 disables the age check. The API validates initData with BOT_TOKEN, so that
# must be set on the API service too for the public /webapp endpoints.
WEBAPP_INITDATA_MAX_AGE_SECONDS = int(os.environ.get("WEBAPP_INITDATA_MAX_AGE_SECONDS", "86400"))
# CORS origins allowed to call the public /webapp endpoints (comma-separated;
# "*" allows any — fine here since auth is per-request via signed initData).
WEBAPP_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("WEBAPP_ALLOWED_ORIGINS", "*").split(",") if o.strip()
]
