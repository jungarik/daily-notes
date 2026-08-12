"""
Client seam for calling the API service over Railway's private network.

Not yet wired into the bot handlers — the bot still calls the domain services
in-process. This exists so that migration is a swap at the adapter edge (call
`api_client` instead of the service) rather than a rewrite. Async to match the
bot's event loop.
"""

import logging

import httpx

import config

logger = logging.getLogger(__name__)


class ApiClient:
    """Thin async HTTP client for the internal API."""

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 timeout: float | None = None):
        self._base_url = (base_url or config.API_BASE_URL or "").rstrip("/")
        self._token = token or config.API_INTERNAL_TOKEN
        self._timeout = timeout or config.API_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def _headers(self) -> dict:
        return {"X-Internal-Token": self._token} if self._token else {}

    async def health(self) -> bool:
        """True if the API answers its liveness probe."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except Exception:
            logger.exception("API health check failed")
            return False

    async def ping(self) -> bool:
        """True if the token-guarded /internal/ping succeeds (connectivity + auth)."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/internal/ping", headers=self._headers()
                )
                return resp.status_code == 200
        except Exception:
            logger.exception("API ping failed")
            return False

    async def resolve_user(self, chat_id: int) -> int | None:
        """Exchange a Telegram chat_id for the internal user_id (created on first
        sight). Thin clients call this before any domain endpoint. Returns None
        on error."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/users/resolve",
                    json={"chat_id": chat_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("user_id")
        except Exception:
            logger.exception("API resolve_user failed")
            return None

    async def known_paths(self, user_id: int) -> list[str]:
        """The user's existing vault paths (controlled vocabulary). Empty on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/internal/notes/paths",
                    params={"user_id": user_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("paths", [])
        except Exception:
            logger.exception("API known_paths failed")
            return []

    async def enrich_note(self, note_id: int, user_id: int) -> dict | None:
        """Run the deferred enrichment pass; returns the note's metadata, or None
        on failure / missing note."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/{note_id}/enrich",
                    json={"user_id": user_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API enrich_note failed")
            return None

    async def set_note_path(self, note_id: int, path: str) -> tuple[dict | None, str | None]:
        """Move a note to a path. Returns (meta, error):
        - (meta, None)        on success
        - (None, detail)      when the path is rejected (e.g. not under a root folder)
        - (None, None)        on any other failure / missing note
        """
        if not self.configured:
            return (None, None)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/{note_id}/path",
                    json={"path": path}, headers=self._headers(),
                )
            if resp.status_code == 422:
                try:
                    detail = resp.json().get("detail", "invalid path")
                except Exception:
                    detail = "invalid path"
                return (None, detail)
            resp.raise_for_status()
            return (resp.json(), None)
        except Exception:
            logger.exception("API set_note_path failed")
            return (None, None)

    async def _post_ok(self, path: str, json: dict | None = None) -> bool:
        """POST and return True on 2xx, False otherwise."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}{path}", json=json, headers=self._headers(),
                )
                return resp.status_code < 300
        except Exception:
            logger.exception("API POST %s failed", path)
            return False

    async def cancel_reminder(self, reminder_id: int) -> bool:
        return await self._post_ok(f"/internal/reminders/{reminder_id}/cancel")

    async def complete_reminder(self, reminder_id: int) -> bool:
        return await self._post_ok(f"/internal/reminders/{reminder_id}/done")

    async def snooze_reminder(self, reminder_id: int, user_id: int, mode: str) -> str | None:
        """Postpone a reminder; returns the new remind_at (ISO) or None on failure."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/reminders/{reminder_id}/snooze",
                    json={"user_id": user_id, "mode": mode}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("remind_at")
        except Exception:
            logger.exception("API snooze_reminder failed")
            return None

    async def search(self, user_id: int, query: str) -> str | None:
        """Agenda-aware RAG answer over the user's notes, via the API. Timezone
        and language are resolved server-side from user_id. Returns the answer
        text, or None on miss/error (so callers can fall back)."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/search",
                    json={"user_id": user_id, "query": query},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("answer")
        except Exception:
            logger.exception("API search failed")
            return None
