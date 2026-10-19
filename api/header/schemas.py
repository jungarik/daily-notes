"""Response models for the header section."""

from pydantic import BaseModel


class RootStat(BaseModel):
    """One root folder's tally.

    `key` is the i18n key, so a client can tell the roots apart without parsing
    the label; `label` is that key already resolved into the user's language.
    """

    key: str
    label: str
    count: int = 0


class FavoriteGroup(BaseModel):
    """The favourite notes in one folder.

    `root` and `sub` are the stored (localised) names, `sub` empty for notes
    filed directly on a root. `label` is what the header prints under the
    circle: the sub-folder, or the root when there is none.
    """

    root: str
    sub: str = ""
    label: str
    count: int = 0


class HeaderStats(BaseModel):
    stats: list[RootStat] = []
    favorites: list[FavoriteGroup] = []
