"""Mapview router — GET /api/mapview/graph. The connections graph."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import current_user
from api.mapview import helper

router = APIRouter(prefix="/api/mapview", tags=["mapview"])


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


@router.get("/graph", response_model=Graph)
def graph(user_id: int = Depends(current_user)) -> Graph:
    return Graph(**helper.graph(user_id))
