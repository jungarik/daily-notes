"""Mapview section service: build the connection graph (nodes + edges).

Only notes that participate in a link appear. Direction is preserved in the
edges (the client can render undirected for now, directed later)."""

from api.mapview import db


def _display_title(title: str | None, text: str | None, limit: int = 60) -> str:
    t = (title or "").strip()
    if t:
        return t
    snippet = " ".join((text or "").split())
    if not snippet:
        return "untitled"
    return snippet[:limit] + "…" if len(snippet) > limit else snippet


def graph(user_id: int) -> dict:
    """{nodes:[{id,title,path,degree}], edges:[{source,target}]}."""
    edges = db.all_links(user_id)
    ids = {i for e in edges for i in e}
    briefs = {b["id"]: b for b in db.notes_brief(user_id, ids)}

    degree: dict[int, int] = {}
    for f, t in edges:
        degree[f] = degree.get(f, 0) + 1
        degree[t] = degree.get(t, 0) + 1

    nodes = [
        {"id": nid, "title": _display_title(b["title"], b["text"]),
         "path": b["path"], "degree": degree.get(nid, 0)}
        for nid, b in briefs.items()
    ]
    out_edges = [
        {"source": f, "target": t}
        for f, t in edges if f in briefs and t in briefs
    ]
    return {"nodes": nodes, "edges": out_edges}
