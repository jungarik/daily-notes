"""Response models for the mapview section."""

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: int
    title: str
    path: str | None = None
    degree: int = 0


class GraphEdge(BaseModel):
    source: int
    target: int


class Graph(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
