"""Voice transcription: audio bytes → text via OpenAI, with transcription context."""

import io

import config
from openai_client import get_client


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe Telegram OGG/Opus audio via OpenAI, with a context prompt."""
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
    text = result if isinstance(result, str) else getattr(result, "text", "")
    return text.strip()
