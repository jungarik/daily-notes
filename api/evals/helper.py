"""Dry-run agent evaluation, optional LLM grading, and metrics."""

import json
import logging
import re
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import i18n
import openai_client
from agents.chat import loop as chat_loop
from agents.chat import service as chat_service
from agents.chat.tools import Ctx
from agents.enrich import service as enrich_service
from agents.reminder import service as reminder_service
from api.evals import db

logger = logging.getLogger(__name__)

_SUCCESS = {"yes", "partial", "no"}
_QUALITY = {"good", "partial", "bad"}


def _settings(user_id: int):
    tz_name, lang = db.get_settings(user_id)
    try:
        tz = ZoneInfo(tz_name) if tz_name else config.DEFAULT_TZ
    except Exception:
        tz = config.DEFAULT_TZ
    return tz, i18n.normalize(lang) or i18n.DEFAULT_LOCALE


def _chat_case(user_id: int, messages: list[dict], now, tz, locale) -> dict:
    ctx = Ctx(user_id, now, tz=tz, locale=locale)
    result = chat_loop.run_loop(ctx, messages)
    if result["status"] == "confirm":
        answer = json.dumps(result["action"], ensure_ascii=False, default=str)
    else:
        answer = result.get("reply") or ""
    routes = ctx.trace["routes"]
    if "rag" in routes:
        mode = "RAG"
    elif ctx.trace["tools"]:
        mode = "tool" if result["status"] == "confirm" else "clarification"
    else:
        mode = "fallback"
    return {"answer": answer, "route_or_mode": mode, "trace": ctx.trace}


def _planner_case(agent: str, user_id: int, question: str, now, tz, locale) -> dict:
    service = enrich_service if agent == "enrich" else reminder_service
    action = service.plan_action(user_id, question, now, tz, locale)
    trace = {"tools": [], "retrieved_chunks": [], "routes": [agent]}
    if action:
        trace["tools"].append({"name": action["name"], "args": action.get("args") or {}})
        return {"answer": json.dumps(action, ensure_ascii=False, default=str),
                "route_or_mode": "tool", "trace": trace}
    return {"answer": "No concrete action could be determined.",
            "route_or_mode": "clarification", "trace": trace}


def _judge(case: dict, observed: dict) -> dict:
    prompt = (
        "Evaluate one agent test case. Use only the expected behavior, actual answer, "
        "and trace. Return strict JSON with: task_success (yes|partial|no), "
        "groundedness (good|partial|bad), answer_quality (good|partial|bad), "
        "errors (one short snake_case error type or none), notes (brief reason). "
        "For planning agents, a correct non-executed action proposal counts as success. "
        "Do not require retrieved chunks for reminder or action-planning cases.\n" +
        json.dumps({"agent": case["agent"], "question": case["question"],
                    "expected_behavior": case["expected_behavior"],
                    "answer": observed["answer"], "trace": observed["trace"]},
                   ensure_ascii=False, default=str))
    response = openai_client.get_client().chat.completions.create(
        model=config.AGENT_EVAL_JUDGE_MODEL, temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": "You are a strict software evaluation judge."},
                  {"role": "user", "content": prompt}])
    data = json.loads(response.choices[0].message.content)
    error_type = re.sub(r"[^a-z0-9_]+", "_", str(
        data.get("errors") or "none").lower()).strip("_") or "none"
    return {
        "task_success": data.get("task_success") if data.get("task_success") in _SUCCESS else "no",
        "groundedness": data.get("groundedness") if data.get("groundedness") in _QUALITY else "bad",
        "answer_quality": data.get("answer_quality") if data.get("answer_quality") in _QUALITY else "bad",
        "errors": error_type[:100],
        "notes": str(data.get("notes") or "")[:1000],
    }


def _completed_turn(messages: list[dict], requested_index: int | None) -> dict:
    """Select a completed user turn; indices are one-based among user messages."""
    positions = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    turns = []
    for index, start in enumerate(positions, 1):
        end = positions[index] if index < len(positions) else len(messages)
        segment = messages[start:end]
        completed = any(
            message.get("role") == "assistant" and message.get("content")
            and not message.get("tool_calls") for message in segment[1:])
        turns.append({"turn_index": index, "start": start, "end": end,
                      "question": str(messages[start].get("content") or ""),
                      "segment": segment, "completed": completed})
    if requested_index is not None:
        selected = next((turn for turn in turns if turn["turn_index"] == requested_index), None)
        if selected is None:
            raise LookupError("turn index not found")
        if not selected["completed"]:
            raise LookupError("selected turn is not completed")
        return selected
    selected = next((turn for turn in reversed(turns) if turn["completed"]), None)
    if selected is None:
        raise LookupError("thread has no completed user turn")
    return selected


def _handoff_instruction(turn: dict, agent: str) -> str:
    expected_tool = "perform_action" if agent == "enrich" else "set_reminder"
    for message in turn["segment"]:
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            if function.get("name") != expected_tool:
                continue
            try:
                raw_args = function.get("arguments") or {}
                args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
            except Exception:
                args = {}
            instruction = str(args.get("instruction") or "").strip()
            if instruction:
                return instruction
    raise LookupError("selected turn has no %s handoff" % agent)


def _replay_messages(messages: list[dict], turn: dict) -> list[dict]:
    prior = [message for message in messages[:turn["start"]]
             if message.get("role") != "system"]
    return [{"role": "system", "content": chat_service.SYSTEM_PROMPT},
            *prior, {"role": "user", "content": turn["question"]}]


def _run_case(case: dict, user_id: int, now, tz, locale,
              replay_messages: list[dict] | None = None) -> dict:
    started = time.perf_counter()
    try:
        observed = (_chat_case(user_id, replay_messages, now, tz, locale)
                    if case["agent"] == "chat" else
                    _planner_case(case["agent"], user_id, case["question"], now, tz, locale))
        latency_ms = round((time.perf_counter() - started) * 1000)
        grade = {"task_success": None, "groundedness": None,
                 "answer_quality": None, "errors": "none", "notes": "judge disabled"}
        if config.AGENT_EVAL_JUDGE_ENABLED:
            try:
                grade = _judge(case, observed)
            except Exception:
                logger.exception("Evaluation judge failed for thread %s turn %s",
                                 case["thread_id"], case["turn_index"])
                grade["errors"], grade["notes"] = "judge_error", "Automatic judge failed."
    except Exception as exc:
        logger.exception("Evaluation runtime failed for thread %s turn %s",
                         case["thread_id"], case["turn_index"])
        latency_ms = round((time.perf_counter() - started) * 1000)
        observed = {"answer": "", "route_or_mode": "fallback",
                    "trace": {"tools": [], "retrieved_chunks": [], "routes": [],
                              "exception": type(exc).__name__}}
        grade = {"task_success": "no", "groundedness": "bad",
                 "answer_quality": "bad", "errors": "runtime_error",
                 "notes": str(exc)[:1000]}
    chunks = observed["trace"].get("retrieved_chunks") or []
    tools = [item["name"] for item in observed["trace"].get("tools") or []]
    observed["trace"].update(source_thread_id=case["thread_id"],
                             source_turn_index=case["turn_index"])
    return {"thread_id": case["thread_id"], "turn_index": case["turn_index"],
            "agent": case["agent"],
            "question": case["question"], "expected_behavior": case["expected_behavior"],
            "answer": observed["answer"],
            "retrieved_chunks": json.dumps(chunks, ensure_ascii=False, default=str),
            "route_or_mode": observed["route_or_mode"], "tools_used": ",".join(tools),
            "latency_ms": latency_ms, "trace": observed["trace"], **grade}


def run(user_id: int, thread_id: int, expected_behavior: str,
        agent: str = "chat", turn_index: int | None = None) -> dict:
    thread = db.get_thread(user_id, thread_id)
    if thread is None:
        raise LookupError("conversation thread not found")
    turn = _completed_turn(list(thread["messages"]), turn_index)
    question = (turn["question"] if agent == "chat"
                else _handoff_instruction(turn, agent))
    case = {"thread_id": thread_id, "turn_index": turn["turn_index"],
            "agent": agent, "question": question,
            "expected_behavior": expected_behavior}
    replay_messages = _replay_messages(list(thread["messages"]), turn) if agent == "chat" else None
    run_id = db.create_run(user_id, thread_id, turn["turn_index"], agent,
                           expected_behavior, config.AGENT_EVAL_JUDGE_ENABLED)
    tz, locale = _settings(user_id)
    try:
        result = _run_case(case, user_id, datetime.now(tz), tz, locale, replay_messages)
        db.save_result(run_id, result)
        db.finish_run(run_id, "completed")
        return {"run_id": run_id, "status": "completed", "total_cases": 1,
                "judge_enabled": config.AGENT_EVAL_JUDGE_ENABLED,
                "metrics": metrics(user_id, run_id, agent)}
    except Exception as exc:
        db.finish_run(run_id, "failed", str(exc)[:1000])
        raise


def metrics(user_id: int, run_id: int | None = None, agent: str | None = None) -> dict:
    run_id = run_id or db.latest_run_id(user_id, agent)
    if run_id is None:
        return {"run_id": None, "agent": agent, "total_cases": 0}
    rows = db.metric_rows(user_id, run_id, agent)
    if rows is None:
        raise LookupError("evaluation run not found")
    total = len(rows)
    success = Counter(row["task_success"] for row in rows if row["task_success"])
    grounded = Counter(row["groundedness"] for row in rows if row["groundedness"])
    errors = Counter(row["errors"] for row in rows)
    latencies = [row["latency_ms"] for row in rows]
    judged = sum(success.values())
    grounded_judged = sum(grounded.values())
    rate = lambda count, denominator: round(count / denominator, 4) if denominator else None
    return {"run_id": run_id, "agent": agent, "total_cases": total,
            "judged_cases": judged,
            "success_yes": success["yes"], "success_partial": success["partial"],
            "success_no": success["no"],
            "success_rate": rate(success["yes"], total) if judged else None,
            "partial_success_rate": rate(success["partial"], total) if judged else None,
            "failure_rate": rate(success["no"], total) if judged else None,
            "groundedness_good": grounded["good"],
            "groundedness_partial": grounded["partial"],
            "groundedness_bad": grounded["bad"],
            "groundedness_good_rate": rate(grounded["good"], total) if grounded_judged else None,
            "average_latency_ms": round(sum(latencies) / total) if total else None,
            "max_latency_ms": max(latencies) if latencies else None,
            "top_error_types": [{"error": key, "count": value}
                                for key, value in errors.most_common(5)]}
