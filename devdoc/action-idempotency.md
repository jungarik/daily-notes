# Confirmed action idempotency

Every write an agent proposes receives a stable `action_id` before it is shown
for confirmation. The id is derived from the *write itself* — turn, agent, tool
name and sorted args (`broker.generate_action_id`) — never from the hop, so a
re-driven hop cannot run the same write twice. PostgreSQL stores that id in
`action_executions`, where the primary key allows only one request to claim it.

After approval, the broker follows this order:

1. atomically claim the action as `executing`;
2. run the agent's `resume` once;
3. store its encoded `AgentResult` as `completed`;
4. continue the turn so the responder can phrase the reply.

The approval boundary is the turn's: the agent returns `needs_input`, the
section stores the turn handle, and `POST /api/chat/v2/confirm` resumes it. The
ledger is still needed because a process can stop after an external side effect
commits but before the outcome is recorded.

If step 4 times out, a repeated confirmation decodes the completed result and
does not call the write tool again. Simultaneous confirmations see `executing`
and also do not repeat the write. A failed or uncertain execution is recorded
as `failed` and is never retried automatically, because retrying could duplicate
a write that committed just before a connection failure.
