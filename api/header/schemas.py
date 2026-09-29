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


class HeaderStats(BaseModel):
    stats: list[RootStat] = []
