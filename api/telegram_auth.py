"""
Telegram Mini App (Web App) initData validation.

A Mini App running in the user's browser can't hold the internal API token, so
public endpoints authenticate the caller with the signed `initData` string
Telegram provides to the web app. This verifies that signature against the bot
token and returns the authenticated Telegram user — the only Telegram-specific
auth in the API, living at the edge like the bot's `chat_id`.

Ref: Telegram "Validating data received via the Mini App".
"""

import time
import json
import hmac
import hashlib
import logging
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 0) -> dict | None:
    """Verify Mini App `initData` and return the parsed `user` dict, or None.

    Steps (per Telegram spec):
      1. split into key=value pairs; pull out `hash`
      2. data_check_string = keys sorted, "key=value" joined by "\\n" (no hash)
      3. secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
      4. valid iff HMAC_SHA256(key=secret_key, msg=data_check_string) == hash
    Optionally rejects data older than `max_age_seconds` (0 = no age check).
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    if max_age_seconds > 0:
        try:
            auth_date = int(pairs.get("auth_date", "0"))
        except ValueError:
            return None
        if auth_date <= 0 or (time.time() - auth_date) > max_age_seconds:
            logger.info("initData rejected: stale (auth_date=%s)", auth_date)
            return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except Exception:
        return None
    return user if isinstance(user, dict) and "id" in user else None
