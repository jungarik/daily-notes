"""
User identity domain service.

Resolves an external client identity (today: a Telegram chat_id) to the internal
surrogate user_id that the rest of the domain keys on. Thin clients never touch
the users table directly — they obtain their user_id through this service (called
in-process today, and over the API gateway once the bot is cut over).
"""

import logging
from zoneinfo import ZoneInfo

import i18n
import config
from stores import user_store

logger = logging.getLogger(__name__)


def resolve(chat_id: int) -> int:
    """Return the internal user_id for an external chat identity, creating the
    user on first sight."""
    user_id = user_store.get_or_create_user(chat_id)
    logger.debug("Resolved chat_id=%s -> user_id=%s", chat_id, user_id)
    return user_id


def _resolve_tz(name: str | None) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            logger.warning("Invalid stored timezone %r; using default", name)
    return config.DEFAULT_TZ


def _resolve_locale(language: str | None) -> str:
    return i18n.normalize(language) or i18n.DEFAULT_LOCALE


def timezone(user_id: int) -> ZoneInfo:
    """The user's timezone, or the default if unset/invalid."""
    tz_name, _ = user_store.get_settings(user_id)
    return _resolve_tz(tz_name)


def language(user_id: int) -> str:
    """The user's UI language code ('en'/'uk'), or the default."""
    _, lang = user_store.get_settings(user_id)
    return _resolve_locale(lang)


def settings(user_id: int) -> tuple[ZoneInfo, str]:
    """Resolve (timezone, language) for a user in one query, with defaults applied.
    Clients pass only a user_id — all user attributes are resolved here."""
    tz_name, lang = user_store.get_settings(user_id)
    return _resolve_tz(tz_name), _resolve_locale(lang)


def settings_view(user_id: int) -> dict:
    """Both the raw stored settings (or None) and the effective values with
    defaults applied — so a client can format without knowing the defaults."""
    tz_name, lang = user_store.get_settings(user_id)
    return {
        "timezone": tz_name,
        "language": lang,
        "tz_name": _resolve_tz(tz_name).key,
        "locale": _resolve_locale(lang),
    }


def set_timezone(user_id: int, name: str) -> bool:
    """Validate an IANA timezone name and store it. Returns False if invalid."""
    try:
        ZoneInfo(name)
    except Exception:
        logger.info("Rejected invalid timezone %r for user %s", name, user_id)
        return False
    user_store.set_timezone(user_id, name)
    logger.info("User %s timezone set to %s", user_id, name)
    return True


def set_language(user_id: int, code: str) -> str | None:
    """Validate/normalize a language code and store it. Returns the normalized
    code ('en'/'uk'), or None if unsupported."""
    lang = i18n.normalize(code)
    if lang not in i18n.SUPPORTED:
        logger.info("Rejected unsupported language %r for user %s", code, user_id)
        return None
    user_store.set_language(user_id, lang)
    logger.info("User %s language set to %s", user_id, lang)
    return lang
