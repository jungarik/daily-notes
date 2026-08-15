"""
Note polishing: clean up a brain-dump into natural, well-punctuated language.

One LLM call that fixes spelling, grammar, punctuation and phrasing so a hurried
dump (or a rough voice transcript) reads clearly — WITHOUT inventing, answering,
translating or otherwise changing the meaning. Text only; the caller persists the
result and re-embeds. Degrades gracefully: returns the original on any failure.
"""

import json
import logging

import config
from openai_client import get_client

logger = logging.getLogger(__name__)


def polish(text: str) -> str:
    """Return a cleaned-up version of the note. Never raises — returns the input
    unchanged on any error (or when there's nothing to clean)."""
    clean = (text or "").strip()
    if not clean:
        return clean
    try:
        system = (
            "You tidy up a person's brain-dump note (Ukrainian or English) so it "
            "reads as natural, clear language. Fix spelling, grammar, punctuation, "
            "capitalization and spacing, and lightly smooth awkward phrasing. STRICT "
            "rules: keep the SAME language as the input; preserve the meaning exactly; "
            "do NOT add, remove, invent, answer, explain, summarize or translate "
            "anything; never change names, numbers, dates or specific facts; keep it "
            "about the same length. If the text is already clean, return it "
            "unchanged. Return strict JSON: {\"text\": \"<cleaned note>\"}."
        )
        resp = get_client().chat.completions.create(
            model=config.POLISH_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": clean},
            ],
        )
        content = resp.choices[0].message.content
        logger.info("Polish | input=%r | response=%r", clean, content)
        result = str(json.loads(content).get("text", "")).strip()
        return result or clean
    except Exception:
        logger.exception("Polish failed; keeping the note unchanged")
        return clean
