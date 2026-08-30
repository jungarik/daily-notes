"""Mapview router — GET /api/mapview/graph. The connections graph."""

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.mapview import helper
from api.mapview.schemas import Graph

router = APIRouter(prefix="/api/mapview", tags=["mapview"])


@router.get("/graph", response_model=Graph)
def graph(user_id: int = Depends(current_user)) -> Graph:
    return Graph(**helper.graph(user_id))
