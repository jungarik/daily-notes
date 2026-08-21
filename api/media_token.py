"""Short-lived signed tokens for media (image) URLs.

An <img> tag can't send the Telegram initData header, so the web-app carousel
loads attachments through a token in the URL instead. We mint an HMAC over the
attachment id + an expiry (secret = BOT_TOKEN, the same secret initData is
verified against). The token is unforgeable and expires, so only URLs we handed
to the authenticated owner work — and only for a while.
"""

import base64
import hashlib
import hmac
import time

import config

_SECRET = (config.BOT_TOKEN or "media-fallback-secret").encode()
_SIG_LEN = 32   # truncated hex digest is plenty for a short-lived token


def _sig(msg: str) -> str:
    return hmac.new(_SECRET, msg.encode(), hashlib.sha256).hexdigest()[:_SIG_LEN]


def sign(attachment_id: int, ttl: int | None = None) -> str:
    """A URL-safe token authorizing access to one attachment until it expires."""
    exp = int(time.time()) + int(ttl or config.ATTACHMENT_URL_TTL_SECONDS)
    msg = f"{attachment_id}.{exp}"
    raw = f"{msg}.{_sig(msg)}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def verify(token: str, attachment_id: int) -> bool:
    """True iff `token` is a valid, unexpired signature for `attachment_id`."""
    if not token:
        return False
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode()
        aid, exp, sig = raw.split(".")
        if int(aid) != int(attachment_id) or int(exp) < int(time.time()):
            return False
        return hmac.compare_digest(sig, _sig(f"{aid}.{exp}"))
    except Exception:
        return False
