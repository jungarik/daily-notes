from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["chat", "enrich", "reminder"]


class EvalRunRequest(BaseModel):
    thread_id: int = Field(ge=1)
    expected_behavior: str = Field(min_length=1, max_length=4000)
    agent: AgentName = "chat"
    turn_index: int | None = Field(default=None, ge=1)


class EvalRunResponse(BaseModel):
    run_id: int
    status: str
    total_cases: int
    judge_enabled: bool
    metrics: dict


class EvalMetricsResponse(BaseModel):
    run_id: int | None = None
    agent: AgentName | None = None
    total_cases: int = 0
    judged_cases: int = 0
    success_yes: int = 0
    success_partial: int = 0
    success_no: int = 0
    success_rate: float | None = None
    partial_success_rate: float | None = None
    failure_rate: float | None = None
    groundedness_good: int = 0
    groundedness_partial: int = 0
    groundedness_bad: int = 0
    groundedness_good_rate: float | None = None
    average_latency_ms: int | None = None
    max_latency_ms: int | None = None
    top_error_types: list[dict] = Field(default_factory=list)
