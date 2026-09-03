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

DEFAULT_LOCALE = os.environ.get("BOT_DEFAULT_LOCALE", "en")
if DEFAULT_LOCALE not in _LOCALES:
    DEFAULT_LOCALE = "en"

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
