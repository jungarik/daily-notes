"""Shared OpenAI model gateway with bounded retries and typed failures."""

import logging
import time

import config
import openai_client

logger = logging.getLogger(__name__)


class ModelGatewayError(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _kind(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if status == 429 or "ratelimit" in name or "rate limit" in text or "429" in text:
        return "model_rate_limited"
    if status and int(status) >= 500:
        return "model_provider_error"
    if "timeout" in name or "timeout" in text:
        return "model_timeout"
    return "model_error"


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def chat_completion(**kwargs):
    attempts = max(1, config.OPENAI_GATEWAY_MAX_ATTEMPTS)
    last_error = None
    for attempt in range(attempts):
        try:
            return openai_client.get_client().chat.completions.create(**kwargs)
        except Exception as exc:
            last_error = exc
            kind = _kind(exc)
            if kind not in {"model_rate_limited", "model_provider_error",
                            "model_timeout"} or attempt + 1 >= attempts:
                logger.warning("OpenAI chat completion failed: %s", kind)
                raise ModelGatewayError(kind, str(exc)[:1000]) from exc
            delay = _retry_after(exc)
            if delay is None:
                delay = min(config.OPENAI_GATEWAY_MAX_BACKOFF_SECONDS,
                            config.OPENAI_GATEWAY_BASE_BACKOFF_SECONDS * (2 ** attempt))
            logger.info("OpenAI chat completion retry %s/%s after %.2fs: %s",
                        attempt + 1, attempts, delay, kind)
            time.sleep(delay)
    raise ModelGatewayError(_kind(last_error), str(last_error)[:1000])
