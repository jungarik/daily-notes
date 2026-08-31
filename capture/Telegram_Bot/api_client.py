"""
Client for calling the API service over Railway's private network.

This is the bot's sole path to the backend: it imports no services/stores and
never touches the database — every domain operation goes through a method here.
The API is a single `/api` surface shared with the web app; the bot authenticates
with the internal token and passes its resolved `user_id` in the `X-User-Id`
header for user-scoped calls (the identity exchange + reminder dispatcher are
token-only). Async to match the bot's event loop; each method degrades gracefully
on failure so a transient API problem surfaces as a friendly reply, never a crash.
"""

import logging

import httpx

import config

logger = logging.getLogger(__name__)


class ApiClient:
    """Thin async HTTP client for the API."""

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 timeout: float | None = None):
        self._base_url = (base_url or config.API_BASE_URL or "").rstrip("/")
        self._token = token or config.API_INTERNAL_TOKEN
        self._timeout = timeout or config.API_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def _headers(self, user_id: int | None = None) -> dict:
        """Internal token always; the caller's user_id for user-scoped endpoints."""
        h = {}
        if self._token:
            h["X-Internal-Token"] = self._token
        if user_id is not None:
            h["X-User-Id"] = str(user_id)
        return h

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
        """True if the token-guarded /api/telegram_bot/ping succeeds (connectivity + auth)."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/api/telegram_bot/ping", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            logger.exception("API ping failed")
            return False

    async def resolve_user(self, chat_id: int, username: str | None = None) -> int | None:
        """Exchange a Telegram chat_id for the internal user_id (token-only). Thin
        clients call this before any user-scoped endpoint. None on error."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/users/resolve",
                    json={"chat_id": chat_id, "username": username},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("user_id")
        except Exception:
            logger.exception("API resolve_user failed")
            return None

    async def get_settings(self, user_id: int) -> dict | None:
        """The user's settings context (raw + effective tz/language + reminder count)."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/telegram_bot/users/settings", headers=self._headers(user_id))
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API get_settings failed")
            return None

    async def set_timezone(self, user_id: int, name: str) -> tuple[bool, str | None]:
        """Set the user's timezone. (True, None) ok; (False, 'invalid') rejected;
        (False, None) other failure."""
        if not self.configured:
            return (False, None)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/users/timezone",
                    json={"timezone": name}, headers=self._headers(user_id),
                )
            if resp.status_code == 422:
                return (False, "invalid")
            resp.raise_for_status()
            return (True, None)
        except Exception:
            logger.exception("API set_timezone failed")
            return (False, None)

    async def set_language(self, user_id: int, code: str) -> tuple[str | None, str | None]:
        """Set the user's language. (lang, None) ok; (None, 'invalid') unsupported;
        (None, None) other error."""
        if not self.configured:
            return (None, None)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/users/language",
                    json={"language": code}, headers=self._headers(user_id),
                )
            if resp.status_code == 422:
                return (None, "invalid")
            resp.raise_for_status()
            return (resp.json().get("language"), None)
        except Exception:
            logger.exception("API set_language failed")
            return (None, None)

    async def capture_text(self, user_id: int, text: str) -> dict | None:
        """Capture a text note (+ reminder detection). {note_id, text, reminder} or None."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes",
                    json={"text": text}, headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API capture_text failed")
            return None

    async def capture_voice(self, user_id: int, audio_bytes: bytes, mime: str) -> dict | None:
        """Transcribe + capture a voice note. {note_id, text, reminder}; note_id None
        with text='' when nothing was heard. None on failure."""
        if not self.configured:
            return None
        try:
            data = {"mime": mime}
            files = {"audio": ("voice.ogg", audio_bytes, mime)}
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/voice",
                    data=data, files=files, headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API capture_voice failed")
            return None

    async def capture_media(
        self, user_id: int, text: str, images: list[tuple[str, bytes, str]],
    ) -> dict | None:
        """Capture a note with image attachments (+ optional caption). `images` is
        (filename, bytes, mime) tuples. {note_id, text, reminder} or None."""
        if not self.configured:
            return None
        try:
            data = {"text": text or ""}
            files = [("files", (name, blob, mime)) for name, blob, mime in images]
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/media",
                    data=data, files=files, headers=self._headers(user_id),
                )
            if resp.status_code >= 400:
                logger.error("capture_media HTTP %s: %s", resp.status_code, resp.text[:300])
                return None
            return resp.json()
        except Exception:
            logger.exception("API capture_media failed")
            return None

    async def atomize_note(self, note_id: int, user_id: int) -> list[dict]:
        """Split a note into atomic notes. [{note_id, text}] or [] (already atomic / error)."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/{note_id}/atomize",
                    headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json().get("atoms", [])
        except Exception:
            logger.exception("API atomize_note failed")
            return []

    async def delete_note(self, note_id: int, user_id: int) -> tuple[bool, bool]:
        """Delete a note if it's bare. (ok, deleted); ok=False on transport error."""
        if not self.configured:
            return (False, False)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/{note_id}/delete",
                    headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return (True, bool(resp.json().get("deleted")))
        except Exception:
            logger.exception("API delete_note failed")
            return (False, False)

    async def polish_note(self, note_id: int, user_id: int) -> str | None:
        """Clean up a note's wording/punctuation. The (possibly unchanged) text, or None."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/{note_id}/polish",
                    headers=self._headers(user_id),
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
                    f"{self._base_url}/api/telegram_bot/notes/{note_id}/link-candidates",
                    headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json().get("candidates", [])
        except Exception:
            logger.exception("API link_candidates failed")
            return []

    async def toggle_link(self, from_note_id: int, to_note_id: int, user_id: int) -> bool:
        """Toggle a directed link; returns the new linked state (False on error)."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/{from_note_id}/links/{to_note_id}/toggle",
                    headers=self._headers(user_id),
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
                    f"{self._base_url}/api/telegram_bot/reminders", headers=self._headers(user_id))
                resp.raise_for_status()
                return resp.json().get("reminders", [])
        except Exception:
            logger.exception("API list_reminders failed")
            return []

    async def claim_due_reminders(self, limit: int = 50) -> list[dict]:
        """Claim due reminders for delivery (token-only dispatcher). Empty on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/reminders/claim-due",
                    json={"limit": limit}, headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json().get("reminders", [])
        except Exception:
            logger.exception("API claim_due_reminders failed")
            return []

    async def retry_reminder(self, reminder_id: int) -> bool:
        """Return a claimed reminder to 'scheduled' so the next poll retries it."""
        return await self._post_ok(f"/api/telegram_bot/reminders/{reminder_id}/retry")

    async def known_paths(self, user_id: int) -> list[str]:
        """The user's existing vault paths (controlled vocabulary). Empty on error."""
        if not self.configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/telegram_bot/notes/paths", headers=self._headers(user_id))
                resp.raise_for_status()
                return resp.json().get("paths", [])
        except Exception:
            logger.exception("API known_paths failed")
            return []

    async def enrich_note(self, note_id: int, user_id: int) -> dict | None:
        """Run the deferred enrichment pass; returns the note's metadata, or None."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/{note_id}/enrich",
                    headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API enrich_note failed")
            return None

    async def set_note_path(self, note_id: int, path: str, user_id: int) -> tuple[dict | None, str | None]:
        """Move a note to a path. (meta, None) ok; (None, detail) rejected; (None, None) other."""
        if not self.configured:
            return (None, None)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/notes/{note_id}/path",
                    json={"path": path}, headers=self._headers(user_id),
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

    async def _post_ok(self, path: str, json: dict | None = None, user_id: int | None = None) -> bool:
        """POST and return True on 2xx, False otherwise."""
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}{path}", json=json, headers=self._headers(user_id))
                return resp.status_code < 300
        except Exception:
            logger.exception("API POST %s failed", path)
            return False

    async def cancel_reminder(self, reminder_id: int) -> bool:
        return await self._post_ok(f"/api/telegram_bot/reminders/{reminder_id}/cancel")

    async def complete_reminder(self, reminder_id: int) -> bool:
        return await self._post_ok(f"/api/telegram_bot/reminders/{reminder_id}/done")

    async def snooze_reminder(self, reminder_id: int, user_id: int, mode: str) -> str | None:
        """Postpone a reminder; returns the new remind_at (ISO) or None on failure."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/reminders/{reminder_id}/snooze",
                    json={"mode": mode}, headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json().get("remind_at")
        except Exception:
            logger.exception("API snooze_reminder failed")
            return None

    async def search(self, user_id: int, query: str) -> str | None:
        """Agenda-aware RAG answer over the user's notes. Answer text or None."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/telegram_bot/search",
                    json={"query": query}, headers=self._headers(user_id),
                )
                resp.raise_for_status()
                return resp.json().get("answer")
        except Exception:
            logger.exception("API search failed")
            return None

    async def run_evaluations(self, user_id: int, thread_id: int,
                              expected_behavior: str, agent: str = "chat",
                              turn_index: int | None = None) -> dict | None:
        """Replay and evaluate one owned conversation turn."""
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(
                    timeout=config.AGENT_EVAL_API_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    f"{self._base_url}/api/evals/run",
                    json={"thread_id": thread_id, "turn_index": turn_index,
                          "agent": agent, "expected_behavior": expected_behavior},
                    headers=self._headers(user_id))
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API run_evaluations failed")
            return None

    async def evaluation_metrics(self, user_id: int, run_id: int | None = None,
                                 agent: str | None = None) -> dict | None:
        """Return metrics for one (or the latest) evaluation run."""
        if not self.configured:
            return None
        try:
            params = {}
            if run_id is not None:
                params["run_id"] = run_id
            if agent is not None:
                params["agent"] = agent
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    f"{self._base_url}/api/evals/metrics", params=params,
                    headers=self._headers(user_id))
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("API evaluation_metrics failed")
            return None
