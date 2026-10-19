"""Header section service: the vault's root-folder counts, localised.

Folder names are written into note paths in the user's language, so the name is
data rather than presentation — which is why the label is resolved here, beside
the query that matches on it, and shipped to the client already translated. The
Mini App has no i18n layer, and giving it one for four words would put the root
names in a second place to drift.
"""

import i18n
from api.header import db
from common import helper

# How many of the vault's roots the header reports. The order and the keys come
# from `config.ROOT_FOLDERS` rather than being restated here — two lists
# declaring root order is how the Explorer and the header drift apart.
#
# All four are returned; the Mini App renders `folder_inbox` as the ring around
# its add-note button (see browser/webapp/src/components/Header.jsx) and picks it
# out by key, so changing the order here cannot drop it. The other three counts
# are no longer shown — the row beside the ring is favourites now.
REPORTED_ROOTS = 4


def order_favorites(rows: list[tuple[str, str, int]],
                    root_names: list[str]) -> list[dict]:
    """Favourite groups in header order: root order, then name.

    `root_names` is the localised roster in canonical order. A root not on it —
    one left behind by a language switch — sorts after every known root,
    alphabetically, rather than being dropped: its favourites are still the
    user's. Within a root a loose note (empty `sub`) comes before the
    sub-folders, then sub-folders alphabetically.
    """
    rank = {name: index for index, name in enumerate(root_names)}
    keyed = sorted(
        (rank.get(root, len(rank)), root, sub != "", sub.casefold(), sub, count)
        for root, sub, count in rows
    )

    return [{
        "root": root,
        "sub": sub,
        "label": sub or root,
        "count": count,
    } for _, root, _, _, sub, count in keyed]


def stats(user_id: int) -> dict:
    """`{stats, favorites}` — `stats` is one `{key, label, count}` per reported root
    folder (the header uses only Inbox's), `favorites` the favourite notes
    grouped by folder, in header order.

    Counting matches the *stored* folder name, which is localised. A vault
    written in another language therefore counts as empty rather than wrong:
    the label says one thing and the paths say another, and no amount of
    guessing here would make those agree.
    """
    locale = i18n.resolve_locale(db.get_language(user_id))
    labelled = [(key, i18n.t(locale, key))
                for key in helper.order_root_keys()[:REPORTED_ROOTS]]
    counts = db.count_root_entries(user_id, [name for _, name in labelled])

    favorites = db.count_favorites_by_folder(user_id)

    return {
        "stats": [{
            "key": key,
            "label": name,
            "count": counts.get(name, 0),
        } for key, name in labelled],
        "favorites": order_favorites(favorites, [name for _, name in labelled]),
    }
