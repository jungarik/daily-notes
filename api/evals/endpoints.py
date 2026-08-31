"""Internal-token-only evaluation run and observability endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import current_user, require_internal_token
from api.evals import helper
from api.evals import db
from api.evals.schemas import AgentName, EvalMetricsResponse, EvalRunRequest, EvalRunResponse

router = APIRouter(prefix="/api/evals", tags=["evals"],
                   dependencies=[Depends(require_internal_token)])


def eval_admin_user(user_id: int = Depends(current_user)) -> int:
    """Authorize evaluations by internal user id and its stored users.chat_id."""
    if not db.is_eval_admin(user_id):
        raise HTTPException(status_code=403, detail="evaluation admin required")
    return user_id


@router.post("/run", response_model=EvalRunResponse)
def run_evaluations(req: EvalRunRequest,
                    user_id: int = Depends(eval_admin_user)) -> EvalRunResponse:
    try:
        return EvalRunResponse(**helper.run(
            user_id, req.thread_id, req.expected_behavior, req.agent, req.turn_index))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/metrics", response_model=EvalMetricsResponse)
def evaluation_metrics(run_id: int | None = Query(default=None, ge=1),
                       agent: AgentName | None = None,
                       user_id: int = Depends(eval_admin_user)) -> EvalMetricsResponse:
    try:
        return EvalMetricsResponse(**helper.metrics(user_id, run_id, agent))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
