"""Voice transcription: audio bytes → text via OpenAI, with transcription context."""

import io
import logging

import config
from openai_client import get_client

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Lowercase, keep alphanumerics/spaces, collapse whitespace."""
    kept = "".join(c if (c.isalnum() or c.isspace()) else " " for c in text.lower())
    return " ".join(kept.split())


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe Telegram OGG/Opus audio via OpenAI, with a context prompt.

    Returns '' when nothing usable was heard — including the case where Whisper
    echoes the context prompt back (it does this on silent/short/noisy audio).
    """
    audio = io.BytesIO(audio_bytes)
    audio.name = "voice.ogg"  # the extension tells the API the input format
    kwargs = {
        "model": config.OPENAI_STT_MODEL,
        "file": audio,
        "response_format": "text",
    }
    if config.OPENAI_STT_PROMPT:
        kwargs["prompt"] = config.OPENAI_STT_PROMPT
    if config.OPENAI_STT_LANGUAGE:
        kwargs["language"] = config.OPENAI_STT_LANGUAGE

    result = get_client().audio.transcriptions.create(**kwargs)
    # response_format="text" returns a plain string; be tolerant either way.
    text = (result if isinstance(result, str) else getattr(result, "text", "")).strip()
    logger.info("Transcription: %r", text)

    # Whisper echoes the context prompt when there's nothing to transcribe.
    normalized = _normalize(text)
    if normalized and config.OPENAI_STT_PROMPT and normalized in _normalize(
        config.OPENAI_STT_PROMPT
    ):
        logger.info("Transcription matched the context prompt; treating as empty.")
        return ""
    return text
