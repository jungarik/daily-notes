# Confirmed action idempotency

Every write proposed by the Chat or Enrich workflow receives a stable
`action_id` before it is shown for confirmation. PostgreSQL stores that id in
`action_executions`, where the primary key allows only one request to claim it.

After approval, the workflow follows this order:

1. atomically claim the action as `executing`;
2. run the specialist write once;
3. store its result as `completed`;
4. continue to the model to phrase the final reply.

The approval itself is a LangGraph `interrupt()` persisted by `PostgresSaver`.
The confirmation endpoint resumes it with `Command(resume=...)`. The separate
execution ledger remains necessary because a process can still stop after an
external side effect commits but before the approval node writes its checkpoint.

If step 4 times out, a repeated confirmation loads the completed result and
does not call the write tool again. Simultaneous confirmations see `executing`
and also do not repeat the write. A failed or uncertain execution is recorded
as `failed` and is never retried automatically, because retrying could duplicate
a write that committed just before a connection failure.

Pending actions created before this change get a deterministic id that is saved
to their thread before confirmation is executed.
