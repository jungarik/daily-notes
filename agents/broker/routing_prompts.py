"""The prompt that asks a model which agent runs next.

Kept beside the router rather than in an agent folder: choosing between agents is
the farm's own decision, and no agent should be able to edit how it is described
relative to the others.
"""

SYSTEM = (
    "You route one hop of a turn in a personal notes assistant. You are given "
    "the user's message, the agents that have not yet run, and what has already "
    "happened this turn. Choose the one agent that should act next, or none if "
    "the turn has nothing left to do. Return strict JSON: "
    '{"agent": string|null}. The value must be one of the listed agent names '
    "exactly, or null. Prefer null over a poor fit — a turn that stops is "
    "better than a turn that runs the wrong agent. Do not pick an agent whose "
    "work is already reflected in what has happened."
)


def selection_request(candidates: list[dict], message: str, hops: list[dict]) -> str:
    """What the model is shown: who may run, what was asked, what is already done.

    `hops` is rendered from the turn history, so the model sees statuses and
    typed refs rather than any agent's own account of itself.
    """
    lines = [f"User asked: {message}", "", "Agents that have not run:"]

    for candidate in candidates:
        lines.append(f"- {candidate['name']}: {candidate['description']}")

    lines.append("")
    lines.append("Already this turn:" if hops else "Nothing has run yet this turn.")

    for hop in hops:
        made = ", ".join(f"{ref['kind']} {ref['id']}" for ref in hop["produced"]) or "nothing"
        line = f"- {hop['agent']}: {hop['status']}, produced {made}"

        if hop.get("error"):
            line += f", error: {hop['error']}"

        lines.append(line)

    return "\n".join(lines)
