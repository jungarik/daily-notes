"""
Tiny localization helper.

Translations live in locales.json, keyed by locale ('en', 'uk') then string key.
`t(locale, key, **kwargs)` returns the formatted string, falling back to the
default locale and finally the key itself so nothing ever crashes on a miss.
"""

import os
import json
import pathlib
import logging

logger = logging.getLogger(__name__)

_LOCALES = json.loads(
    (pathlib.Path(__file__).parent / "locales.json").read_text(encoding="utf-8")
)

# The locale every surface falls back to when a user has no stored language.
# `users.language` is written only by the bot's /lang command, so a Mini-App-only
# user has none — and each surface deciding that separately is how the header
# comes to label a folder «Вхідні» while enrichment writes "Inbox" into the path.
# `BOT_DEFAULT_LOCALE` is still read so an existing deployment keeps working; the
# name is legacy, since this is not the bot's setting any more.
DEFAULT_LOCALE = (os.environ.get("APP_DEFAULT_LOCALE")
                  or os.environ.get("BOT_DEFAULT_LOCALE")
                  or "uk")
if DEFAULT_LOCALE not in _LOCALES:
    DEFAULT_LOCALE = "uk"

SUPPORTED = tuple(_LOCALES.keys())  # ('en', 'uk')


def normalize(code: str | None) -> str | None:
    """Map inputs like 'uk-UA', 'EN_us', 'uk' to a supported code, else None."""
    if not code:
        return None
    c = code.lower().replace("_", "-")
    if c.startswith("uk"):
        return "uk"
    if c.startswith("en"):
        return "en"
    return None


def resolve_locale(code: str | None) -> str:
    """The locale to use for `code`, falling back to the app default.

    The one place that fallback is decided. `normalize(x) or DEFAULT_LOCALE`
    written out per vertical is the same decision made five times, which is a
    licence for two of them to differ.
    """
    return normalize(code) or DEFAULT_LOCALE


_MONTHS_ABBR = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uk": ["січ", "лют", "бер", "кві", "трав", "черв",
           "лип", "серп", "вер", "жовт", "лист", "груд"],
}
_WEEKDAYS_ABBR = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "uk": ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
}


def fmt_datetime(locale: str | None, dt) -> str:
    """A short, localized 'Wkd, D Mon YYYY, HH:MM' for a datetime."""
    loc = locale if locale in _LOCALES else DEFAULT_LOCALE
    months = _MONTHS_ABBR.get(loc, _MONTHS_ABBR["en"])
    weekdays = _WEEKDAYS_ABBR.get(loc, _WEEKDAYS_ABBR["en"])
    try:
        return "%s, %d %s %d, %02d:%02d" % (
            weekdays[dt.weekday()],
            dt.day,
            months[dt.month - 1],
            dt.year,
            dt.hour,
            dt.minute,
        )
    except Exception:
        logger.warning("Bad datetime for locale=%s", loc)
        return str(dt)


def t(locale: str | None, key: str, **kwargs) -> str:
    """Translate `key` for `locale`, formatting with kwargs."""
    loc = locale if locale in _LOCALES else DEFAULT_LOCALE
    template = (
        _LOCALES.get(loc, {}).get(key)
        or _LOCALES.get(DEFAULT_LOCALE, {}).get(key)
        or key
    )
    try:
        return template.format(**kwargs)
    except Exception:
        logger.warning("Bad format for locale=%s key=%s", loc, key)
        return template
