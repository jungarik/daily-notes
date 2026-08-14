"""
Note atomization: split a multi-idea brain-dump into atomic notes.

Zettelkasten favours one idea per note. This makes a single LLM call that breaks
a dump into self-contained atoms (or returns it unchanged when it is already a
single idea). Text only — persisting and linking the atoms is the caller's job.
On any failure it degrades gracefully by keeping the note whole.
"""

import json
import logging

import config
from openai_client import get_client

logger = logging.getLogger(__name__)

# Below this length a note isn't worth splitting (saves an LLM call).
MIN_SPLIT_CHARS = 40


def split(text: str) -> list[str]:
    """Break a note into atomic, self-contained notes.

    Returns a list of atom texts — a single-element list when the note is already
    one idea (or too short to split). Never raises: returns the note whole on any
    error so capture/enrichment can carry on.
    """
    clean = (text or "").strip()
    if len(clean) < MIN_SPLIT_CHARS:
        return [clean] if clean else []
    try:
        system = (
            "You split a person's brain-dump note (Ukrainian or English) into ATOMIC "
            "notes — one self-contained idea, task, question or fact each "
            "(Zettelkasten style). Rules: keep each atom's original wording as much "
            "as possible; do NOT invent, summarise or add content; do NOT merge "
            "unrelated ideas; do NOT over-split a single coherent thought; preserve "
            "the note's language. If the note is already a single idea, return it "
            "unchanged as one atom. Return strict JSON: {\"atoms\": [\"...\", ...]}."
        )
        resp = get_client().chat.completions.create(
            model=config.ATOMIZE_LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": clean},
            ],
        )
        content = resp.choices[0].message.content
        logger.info("Atomize | input=%r | response=%r", clean, content)
        data = json.loads(content)
        atoms = [str(a).strip() for a in data.get("atoms", []) if str(a).strip()]
        return atoms or [clean]
    except Exception:
        logger.exception("Atomization failed; keeping the note whole")
        return [clean]
