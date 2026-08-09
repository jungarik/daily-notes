"""
Semantic layer: chunking, embeddings, semantic search, and RAG answers.

Isolated from Telegram and from raw persistence — it computes chunks/embeddings
and delegates storage/queries to chunk_store.
"""

import logging

import config
from stores import chunk_store
from openai_client import get_client

logger = logging.getLogger(__name__)


def chunk_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP):
    """Split text into overlapping character windows. Short text stays one chunk."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def embed(text: str) -> str:
    """Return the embedding as a pgvector-compatible string, e.g. '[0.1, 0.2, ...]'."""
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def build_chunks(text: str) -> list[dict]:
    """Chunk `text` and embed each chunk, ready for note_store.save_note."""
    return [
        {
            "index": i,
            "content": content,
            "token_count": len(content.split()),
            "metadata": {"char_len": len(content)},
            "embedding": embed(content),
        }
        for i, content in enumerate(chunk_text(text))
    ]


def search(user_id: int, query: str, remind_start=None, remind_end=None, limit: int = 5):
    """Semantic search over the user's chunks.

    If `remind_start`/`remind_end` are given, results are restricted to chunks
    whose note has an active reminder due in [remind_start, remind_end). The
    caller derives that range (e.g. via timeparser.parse_agenda).
    """
    return chunk_store.search_chunks(
        user_id, embed(query), limit,
        remind_start=remind_start, remind_end=remind_end,
    )


def _format_hits(hits: list[dict], tz=None) -> str:
    """Render retrieved chunks + their analysis as context for the LLM."""
    blocks = []
    for h in hits:
        meta = [f"similarity {h['similarity']:.2f}"]
        created = h["created_at"]
        remind_at = h.get("remind_at")
        if tz is not None:
            created = created.astimezone(tz)
            remind_at = remind_at.astimezone(tz) if remind_at else None
        meta.append(f"saved {created:%Y-%m-%d %H:%M}")
        if remind_at:
            meta.append(f"reminder {remind_at:%Y-%m-%d %H:%M}")
        meta.append(h["source_type"])
        blocks.append(f"[note {h['rank']}] ({', '.join(meta)})\n{h['content']}")
    return "\n\n".join(blocks)


def answer(
    user_id: int,
    query: str,
    remind_start=None,
    remind_end=None,
    language: str = "en",
    tz=None,
    limit: int = 5,
) -> str | None:
    """Retrieve relevant chunks and let an LLM compose a natural answer.

    Returns None when nothing was retrieved. On an LLM error, falls back to the
    top chunk's text so the user still gets the underlying note.
    """
    hits = search(user_id, query, remind_start, remind_end, limit)
    if not hits:
        return None

    system = (
        "You are the user's personal notes assistant. Answer the user's question "
        "using ONLY the notes provided below — do not invent facts. Choose the "
        "single most relevant note and base your answer on it; ignore the others. "
        "If a note has a reminder time, mention it naturally. If none of the notes "
        "actually answer the question, say you couldn't find anything about it. "
        f"Reply in this language: {language}. Keep it short, warm, and conversational."
    )
    user = f"Question: {query}\n\nNotes:\n{_format_hits(hits, tz)}"

    try:
        resp = get_client().chat.completions.create(
            model=config.ANSWER_LLM_MODEL,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        logger.exception("Answer generation failed; falling back to top chunk")
        return hits[0]["content"]
