"""A single lazily-created OpenAI client shared across the app."""

_client = None


def get_client():
    """Return a process-wide OpenAI client, creating it on first use.

    Imported lazily so modules that only *might* call OpenAI don't require the
    package (or an API key) at import time.
    """
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _client
