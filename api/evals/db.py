"""PostgreSQL persistence and metric aggregation for agent evaluations."""

from psycopg.types.json import Json

import config
from db import cursor


def is_eval_admin(user_id: int) -> bool:
    """Resolve configured Telegram chat ids to users.id, then authorize using
    the already-authenticated internal user id."""
    allowed_user_ids = list(config.EVAL_ADMIN_USER_IDS)
    if not allowed_user_ids:
        return False
    with cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE id = ANY(%s);", (allowed_user_ids,))
        admin_user_ids = {row[0] for row in cur.fetchall()}
        return user_id in admin_user_ids


def get_settings(user_id: int) -> tuple[str | None, str | None]:
    with cursor() as cur:
        cur.execute("SELECT timezone, language FROM users WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def get_thread(user_id: int, thread_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, messages, pending FROM chat_threads WHERE id = %s AND user_id = %s;",
            (thread_id, user_id))
        row = cur.fetchone()
        return {"id": row[0], "messages": row[1] or [], "pending": row[2]} if row else None


def create_run(user_id: int, thread_id: int, turn_index: int, agent: str,
               expected_behavior: str, judge_enabled: bool) -> int:
    with cursor() as cur:
        cur.execute(
            """INSERT INTO eval_runs
               (requested_by_user_id, agent_filter, status, judge_enabled,
                total_cases, thread_id, turn_index, expected_behavior)
               VALUES (%s, %s, 'running', %s, 1, %s, %s, %s) RETURNING id;""",
            (user_id, agent, judge_enabled, thread_id, turn_index, expected_behavior))
        return cur.fetchone()[0]


def save_result(run_id: int, result: dict) -> int:
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO eval_results
                (run_id, agent, question, expected_behavior, answer,
                 retrieved_chunks, route_or_mode, tools_used, task_success,
                 groundedness, answer_quality, latency_ms, errors, notes, trace,
                 thread_id, turn_index)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s) RETURNING id;
            """,
            (run_id, result["agent"], result["question"],
             result["expected_behavior"], result["answer"],
             result["retrieved_chunks"], result["route_or_mode"],
             result["tools_used"], result.get("task_success"),
             result.get("groundedness"), result.get("answer_quality"),
             result["latency_ms"], result["errors"], result["notes"],
             Json(result["trace"]), result["thread_id"], result["turn_index"]))
        return cur.fetchone()[0]


def finish_run(run_id: int, status: str, error: str | None = None) -> None:
    with cursor() as cur:
        cur.execute(
            """UPDATE eval_runs SET status = %s, error = %s,
               completed_at = now() WHERE id = %s;""", (status, error, run_id))


def latest_run_id(user_id: int, agent: str | None = None) -> int | None:
    with cursor() as cur:
        if agent is None:
            cur.execute(
                """SELECT id FROM eval_runs
                   WHERE requested_by_user_id = %s
                   ORDER BY started_at DESC LIMIT 1;""", (user_id,))
        else:
            cur.execute(
                """SELECT id FROM eval_runs
                   WHERE requested_by_user_id = %s AND agent_filter = %s
                   ORDER BY started_at DESC LIMIT 1;""", (user_id, agent))
        row = cur.fetchone()
        return row[0] if row else None


def metric_rows(user_id: int, run_id: int, agent: str | None = None) -> list[dict] | None:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM eval_runs WHERE id = %s AND requested_by_user_id = %s;",
            (run_id, user_id))
        if not cur.fetchone():
            return None
        if agent is None:
            cur.execute(
                """SELECT task_success, groundedness, latency_ms, errors
                   FROM eval_results WHERE run_id = %s;""", (run_id,))
        else:
            cur.execute(
                """SELECT task_success, groundedness, latency_ms, errors
                   FROM eval_results WHERE run_id = %s AND agent = %s;""",
                (run_id, agent))
        return [{"task_success": r[0], "groundedness": r[1],
                 "latency_ms": r[2], "errors": r[3]} for r in cur.fetchall()]
