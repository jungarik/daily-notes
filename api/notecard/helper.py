"""Notecard section service: verify the signed token and stream the bytes.

Returns a (status, payload) result the endpoint maps to HTTP:
  ("forbidden", None)      — bad/expired token
  ("not_found", None)      — no such attachment, or bytes unavailable
  ("ok", (data, ctype, mime)) — stream these bytes
Uses shared infra: media_token (auth) + object storage (bytes).
"""

from api import media_token
from api.notecard import store
# Object storage client is shared core infra (S3-compatible). Kept in `stores`
# until the core migration; this section imports no domain logic from it.
from stores import file_store


def fetch(attachment_id: int, token: str):
    if not media_token.verify(token, attachment_id):
        return ("forbidden", None)
    a = store.get_attachment(attachment_id)
    if a is None:
        return ("not_found", None)
    obj = file_store.fetch_object(a["storage_key"])
    if obj is None:
        return ("not_found", None)
    data, content_type = obj
    return ("ok", (data, content_type, a["mime"]))
