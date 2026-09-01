"""Shared embedding and chunk-building helpers."""

import config
from openai_client import get_client


def chunk_text(text: str, size: int = config.CHUNK_SIZE,
               overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def embed(text: str) -> str:
    resp = get_client().embeddings.create(model=config.EMBED_MODEL, input=text)
    return str(resp.data[0].embedding)


def build_chunks(text: str) -> list[dict]:
    return [{
      "index": i, 
      "content": c, 
      "token_count": len(c.split()),
      "metadata": {"char_len": len(c)}, 
      "embedding": embed(c)} for i, c in enumerate(chunk_text(text))]
