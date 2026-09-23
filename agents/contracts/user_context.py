"""Who a turn belongs to, and the clock to resolve it against."""

from typing import TypedDict


class UserContext(TypedDict, total=False):
    """Who the turn belongs to, and the clock to resolve it against.

    Plain JSON by design: `now` and `tz` travel as strings so the envelope stays
    serialisable, and each agent restores them against its own clock. A confirm
    arriving ten minutes later carries a *different* context, which is the point.

    `user_id` is the one key an agent can count on — it is the turn's owner, and
    the only place that owner is written down. Everything else is optional, so an
    agent reading a key it was not given falls back rather than failing.

    Every key is optional to the type checker (`total=False`), so `user_id` is
    enforced at runtime instead: the loop subscripts it, and a context without
    one raises rather than writing a row for nobody.
    """

    user_id: int
    now: str
    tz: str | None
    locale: str
