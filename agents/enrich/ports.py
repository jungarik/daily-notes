from typing import Protocol


class EnrichRepository(Protocol):
    def get_note_for_user(self, user_id: int, note_id: int) -> dict | None: ...
