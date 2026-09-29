"""Header section service: the vault's root-folder counts, localised.

Folder names are written into note paths in the user's language, so the name is
data rather than presentation — which is why the label is resolved here, beside
the query that matches on it, and shipped to the client already translated. The
Mini App has no i18n layer, and giving it one for four words would put the root
names in a second place to drift.
"""

import i18n
from api.header import db

# The roots the header reports, in display order. All four are returned; the
# Mini App shows the first three (see browser/webapp/src/components/Header.jsx).
STAT_ROOT_KEYS = (
    "folder_inbox",
    "folder_projects",
    "folder_areas",
    "folder_resources",
)

# Only the bot ever writes `users.language`, so a Mini-App-only user has none.
# The fallback lives here rather than in `i18n.DEFAULT_LOCALE` because that one
# is the bot's default too, and these are not the same decision.
FALLBACK_LOCALE = "uk"


def stats(user_id: int) -> dict:
    """`{stats: [{key, label, count}]}` — one entry per reported root folder.

    Counting matches the *stored* folder name, which is localised. A vault
    written in another language therefore counts as empty rather than wrong:
    the label says one thing and the paths say another, and no amount of
    guessing here would make those agree.
    """
    locale = i18n.normalize(db.get_language(user_id)) or FALLBACK_LOCALE
    labelled = [(key, i18n.t(locale, key)) for key in STAT_ROOT_KEYS]
    counts = db.count_root_entries(user_id, [name for _, name in labelled])

    return {
        "stats": [{
            "key": key,
            "label": name,
            "count": counts.get(name, 0),
        } for key, name in labelled],
    }
