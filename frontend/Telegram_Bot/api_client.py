"""
Client for calling the API service over Railway's private network.

This is the bot's sole path to the backend: the bot imports no services/stores
and never touches the database — every domain operation goes through a method
here. Method names mirror the API's `/internal/*` endpoints. Async to match the
bot's event loop. Each method degrades gracefully on failure (returns None / []
/ (…, error)) so a transient API problem surfaces as a friendly reply, never a
crash.
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

    async def resolve_user(self, chat_id: int, username: str | None = None) -> int | None:
        """Exchange a Telegram chat_id for the internal user_id (created on first
        sight, recording the username). Thin clients call this before any domain
        endpoint. Returns None on error."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/users/resolve",
                    json={"chat_id": chat_id, "username": username},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("user_id")
        except Exception:
            logger.exception("API resolve_user failed")
            return None

    async def get_settings(self, user_id: int) -> dict | None:
        """The user's settings context: raw + effective timezone/language and the
        active reminder count. None on error (caller applies its own fallback)."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/internal/users/settings",
                    params={"user_id": user_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API get_settings failed")
            return None

    async def set_timezone(self, user_id: int, name: str) -> tuple[bool, str | None]:
        """Set the user's timezone. Returns (ok, error): (True, None) on success,
        (False, "invalid") when rejected, (False, None) on any other failure."""
        if not self.configured:
            return (False, None)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/users/timezone",
                    json={"user_id": user_id, "timezone": name},
                    headers=self._headers(),
                )
            if resp.status_code == 422:
                return (False, "invalid")
            resp.raise_for_status()
            return (True, None)
        except Exception:
            logger.exception("API set_timezone failed")
            return (False, None)

    async def set_language(self, user_id: int, code: str) -> tuple[str | None, str | None]:
        """Set the user's language. Returns (language, error): (lang, None) on
        success, (None, "invalid") when unsupported, (None, None) on other error."""
        if not self.configured:
            return (None, None)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/users/language",
                    json={"user_id": user_id, "language": code},
                    headers=self._headers(),
                )
            if resp.status_code == 422:
                return (None, "invalid")
            resp.raise_for_status()
            return (resp.json().get("language"), None)
        except Exception:
            logger.exception("API set_language failed")
            return (None, None)

    async def capture_text(self, user_id: int, text: str) -> dict | None:
        """Capture a text note (+ reminder detection). Returns {note_id, text,
        reminder} or None on failure."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes",
                    json={"user_id": user_id, "text": text},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API capture_text failed")
            return None

    async def capture_voice(
        self, user_id: int, audio_bytes: bytes, mime: str,
    ) -> dict | None:
        """Transcribe + capture a voice note. Returns {note_id, text, reminder};
        note_id is None with text="" when nothing was heard. None when the
        transcription backend fails (502) or on any other error."""
        if not self.configured:
            return None
        try:
            data = {"user_id": str(user_id), "mime": mime}
            files = {"audio": ("voice.ogg", audio_bytes, mime)}
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/voice",
                    data=data, files=files, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API capture_voice failed")
            return None

    async def atomize_note(self, note_id: int, user_id: int) -> list[dict]:
        """Split a note into atomic notes. Returns [{note_id, text}] for the
        created atoms, or [] when the note was already a single idea / on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/{note_id}/atomize",
                    json={"user_id": user_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("atoms", [])
        except Exception:
            logger.exception("API atomize_note failed")
            return []

    async def delete_note(self, note_id: int) -> tuple[bool, bool]:
        """Delete a note if it's bare. Returns (ok, deleted): ok=False on a
        transport error; when ok, `deleted` reflects the server guard (False means
        it was blocked because the note has metadata, links, or an active reminder)."""
        if not self.configured:
            return (False, False)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/{note_id}/delete",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return (True, bool(resp.json().get("deleted")))
        except Exception:
            logger.exception("API delete_note failed")
            return (False, False)

    async def polish_note(self, note_id: int) -> str | None:
        """Clean up a note's wording/punctuation (no invention). Returns the
        (possibly unchanged) text, or None on failure / missing note."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/{note_id}/polish",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("text")
        except Exception:
            logger.exception("API polish_note failed")
            return None

    async def link_candidates(self, user_id: int, note_id: int) -> list[dict]:
        """Ranked link candidates (each with a `linked` flag). Empty on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/internal/notes/{note_id}/link-candidates",
                    params={"user_id": user_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("candidates", [])
        except Exception:
            logger.exception("API link_candidates failed")
            return []

    async def toggle_link(self, from_note_id: int, to_note_id: int) -> bool:
        """Toggle a directed link; returns the new linked state (False on error)."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/notes/{from_note_id}/links/{to_note_id}/toggle",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return bool(resp.json().get("linked"))
        except Exception:
            logger.exception("API toggle_link failed")
            return False

    async def list_reminders(self, user_id: int) -> list[dict]:
        """The user's upcoming reminders [{id, remind_at, text, status}]. Empty on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/internal/reminders",
                    params={"user_id": user_id}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("reminders", [])
        except Exception:
            logger.exception("API list_reminders failed")
            return []

    async def claim_due_reminders(self, limit: int = 50) -> list[dict]:
        """Claim due reminders for delivery [{reminder_id, user_id, chat_id,
        remind_at, text, locale}]. Empty on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/internal/reminders/claim-due",
                    json={"limit": limit}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("reminders", [])
        except Exception:
            logger.exception("API claim_due_reminders failed")
            return []

    async def retry_reminder(self, reminder_id: int) -> bool:
        """Return a claimed reminder to 'scheduled' so the next poll retries it."""
        return await self._post_ok(f"/internal/reminders/{reminder_id}/retry")

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
