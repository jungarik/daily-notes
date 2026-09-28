"""Prompt for extracting a reminder datetime from an instruction."""

import config


def extraction_prompt(now) -> str:
    return (
        "Extract a reminder from the user's message. Return strict JSON: "
        "{\"is_reminder\": bool, \"remind_at\": string|null}. remind_at is an "
        f"ISO-8601 local time. Current local time is "
        f"{now.strftime('%Y-%m-%dT%H:%M:%S')} ({now.tzname()}). Resolve relative "
        "expressions. Use 09:00 for a date without time; morning=09:00, noon=12:00, "
        "afternoon=15:00, evening=19:00, night=21:00. For an indefinite quantity "
        f"assume {config.REMINDER_FEW_COUNT}; for 'later' use "
        f"{config.REMINDER_LATER} from now."
    )
