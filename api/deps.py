"""Shared FastAPI dependencies (auth).

Two access paths reach the single `/api` surface:
- Browsers (the Mini App) send a signed Telegram `initData` header; identity is
  derived from it server-side.
- Trusted server clients (the bot, over the private network) send the internal
  token plus an explicit `X-User-Id` header.

`current_user` resolves the caller's internal user_id from whichever applies. A
client-supplied user_id is ONLY honoured on the token path — never from a
browser. `require_internal_token` guards privileged, cross-user endpoints
(identity resolve, the reminder dispatcher) that no browser should call.
"""

from fastapi import Header, HTTPException, status

import config
from db import cursor
from api.telegram_auth import validate_init_data


def _resolve_user(chat_id: int, username: str | None = None) -> int:
    """Identity is shared auth infra: exchange an external chat_id for the internal
    user_id, creating the user on first sight (and refreshing a new username). Kept
    here rather than in a domain layer so every section's auth is self-contained."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (chat_id, username) VALUES (%s, %s)
            ON CONFLICT (chat_id) DO UPDATE
              SET updated_at = now(),
                  username = COALESCE(EXCLUDED.username, users.username)
            RETURNING id;
            """,
            (chat_id, username),
        )
        return cur.fetchone()[0]


def _token_ok(token: str | None) -> bool:
    """True if the internal token matches, or if none is configured (local dev)."""
    expected = config.API_INTERNAL_TOKEN
    return (not expected) or (token == expected)


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """Guard privileged endpoints with the shared secret. If `API_INTERNAL_TOKEN`
    is unset the check is skipped (local dev); set it in production."""
    if not _token_ok(x_internal_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def current_user(
    x_telegram_init_data: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
    x_user_id: int | None = Header(default=None),
) -> int:
    """Resolve the caller's internal user_id.

    - Browser path: a valid Telegram `initData` header → the Telegram user is
      resolved to a user_id server-side (any client-supplied id is ignored).
    - Trusted path: the internal token + an explicit `X-User-Id` header.
    401 if neither authenticates.
    """
    if x_telegram_init_data:
        user = validate_init_data(
            x_telegram_init_data, config.BOT_TOKEN or "",
            config.WEBAPP_INITDATA_MAX_AGE_SECONDS)
        if not user:
            raise HTTPException(status_code=401, detail="invalid init data")
        return _resolve_user(int(user["id"]), user.get("username"))
    if x_user_id is not None and _token_ok(x_internal_token):
        return int(x_user_id)
    raise HTTPException(status_code=401, detail="authentication required")
