"""The prompt that turns a turn's history into one user-facing reply."""

import json

SYSTEM = (
    "You write the single reply a personal notes assistant gives its owner. "
    "You are told what the user asked and what each agent did this turn; you "
    "did none of it yourself. Report only what the record shows — never invent "
    "a note, a title, a time, or a count that is not listed. Write one or two "
    "short sentences in the user's language, in the first person, plainly and "
    "without pleasantries. If a step failed, say so and say what still "
    "succeeded. If the turn is waiting on the user, describe what you are about "
    "to ask them to confirm and nothing more."
)


def reply_request(message: str,
                  hops: list[dict],
                  locale: str,
                  awaiting: str | None,
                  states: dict[str, dict]) -> str:
    """What the model is shown: the ask, the record, and what each hop produced.

    `hops` is rendered from the turn history, so statuses and typed refs come
    from the loop rather than from any agent's account of itself. `states` is
    what those agents actually saved, read back through `read_state` — that is
    where an answer composed by another agent lives, and without it a Q&A turn
    could only be reported as "found 3 notes".
    """
    lines = [f"User asked: {message}", f"Reply language: {locale}", "This turn:"]

    for hop in hops:
        made = ", ".join(f"{ref['kind']} {ref['id']}" for ref in hop["produced"]) or "nothing"
        line = f"- {hop['agent']}: {hop['status']}, produced {made}"

        if hop.get("error"):
            line += f", error: {hop['error']}"

        lines.append(line)

    if awaiting is not None:
        lines.append(f"{awaiting} is waiting for the user to confirm its action.")

    for agent, state in (states or {}).items():
        lines.append("")
        lines.append(f"What {agent} produced:")
        lines.append(json.dumps(state, ensure_ascii=False, default=str))

    return "\n".join(lines)
