"""search_notes conversation tool."""

from common import embedings, helper
from agents.contracts import ToolResult
from tools.conversation import db


def invoke(
    context: dict,
    args: dict,
) -> ToolResult:
    error = helper.required_values_error(
        context,
        "context",
        ["user_id"],
    )

    if error:
        return ToolResult({"error": error})

    error = helper.required_values_error(
        args,
        "args",
        ["query"],
    )

    if error:
        return ToolResult({"error": error})

    user_id = context["user_id"]
    query = (args.get("query") or "").strip()

    hits = db.search_chunks(user_id, embedings.embed(query))

    if not hits:
        return ToolResult({"message": "No relevant notes found."})

    retrieved_chunks = []
    for hit in hits:
        retrieved_chunks.append({
            "chunk_id": hit["chunk_id"],
            "note_id": hit["note_id"],
            "rank": hit["rank"],
            "similarity": hit["similarity"],
            "content": hit["content"][:1000],
        })

    source_ids = list(dict.fromkeys(hit["note_id"] for hit in hits))
    briefs = {b["id"]: b for b in db.notes_brief(user_id, source_ids[:4])}
    citations = []

    for note_id in source_ids[:4]:
        brief = briefs.get(note_id)

        if brief:
            citations.append({
                "note_id": note_id,
                "title": helper.note_label(
                    brief.get("title"),
                    brief.get("text"),
                ),
            })

    evidence = []

    for hit in hits:
        brief = briefs.get(hit["note_id"], {})
        evidence.append({
            "chunk_id": hit["chunk_id"],
            "note_id": hit["note_id"],
            "title": brief.get("title"),
            "path": brief.get("path"),
            "content": hit["content"],
            "rank": hit["rank"],
            "similarity": hit["similarity"],
            "created_at": hit["created_at"],
            "remind_at": hit.get("remind_at"),
            "source_type": hit["source_type"],
        })

    return ToolResult(
        {
            "query": query,
            "evidence": evidence,
        },
        citations=citations,
        retrieved_chunks=retrieved_chunks,
    )
