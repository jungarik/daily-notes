"""
Semantic layer: chunking, embeddings, and semantic search.

Isolated from Telegram and from raw persistence — it computes chunks/embeddings
and delegates storage/queries to chunk_store.
"""

import config
import chunk_store
from openai_client import get_client


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
    """Chunk `text` and embed each chunk, ready for message_store.save_message."""
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


def search(chat_id: int, query: str, remind_start=None, remind_end=None, limit: int = 5):
    """Semantic search over the chat's chunks.

    If `remind_start`/`remind_end` are given, results are restricted to chunks
    whose note has an active reminder due in [remind_start, remind_end). The
    caller derives that range (e.g. via timeparser.parse_agenda).
    """
    return chunk_store.search_chunks(
        chat_id, embed(query), limit,
        remind_start=remind_start, remind_end=remind_end,
    )
