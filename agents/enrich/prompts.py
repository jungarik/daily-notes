"""Prompts owned by the enrichment specialist."""

import json
from collections import Counter

import config

SYSTEM_PROMPT = (
    "You are the note-processing assistant for the user's personal notes app (a "
    "Zettelkasten-style vault). You TAKE ACTIONS on their notes: create notes, "
    "move notes to a vault path, add tags, link a note to related notes, and "
    "classify/enrich a note's metadata. Use "
    "list_paths/list_tags to stay consistent with the user's existing vault. "
    "For create_note, write one atomic Zettelkasten note: one idea, 1-3 "
    "sentences, no long description, no invented expansion. If the user gives "
    "several independent ideas, ask to split them instead of combining them. "
    "When you reference a specific note, put a marker `[[note:ID]]` alone on its "
    "own line (its id from the tools) — the app renders it as a clickable note "
    "card. The marker is the only thing you write to refer to a note: never write "
    "its title or describe its contents before or after the marker; the card "
    "already shows the title, path and date. "
    "Every action is confirmed with the user before it runs — do not claim "
    "something is done until it is. Be concise."
)


def with_system(messages: list[dict]) -> list[dict]:
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    return messages


def planning_messages(contract: dict) -> list[dict]:
    prompt = (SYSTEM_PROMPT + " You are planning from a typed Chat handoff. Use "
              "get_note_context for referenced notes and list_paths/list_tags when "
              "those reads are needed. Do not execute writes. Finish by choosing "
              "exactly one write tool only when its target and arguments are "
              "resolved; otherwise answer without a tool so Chat can ask for "
              "clarification. Handoff:\n" +
              json.dumps(contract, ensure_ascii=False, default=str))
    return [{"role": "system", "content": prompt},
            {"role": "user", "content": contract["instruction"]}]


def _fmt_vocab(items) -> str:
    return ", ".join(f"{item[0]} ({item[1]})"
                     if isinstance(item, (list, tuple)) and len(item) == 2
                     else str(item) for item in items)


def _vocabulary(known_paths, known_tags) -> str:
    lines = []
    if known_paths:
        lines.append(f"Existing paths (with note use counts): {_fmt_vocab(known_paths)}.")
    if known_tags:
        lines.append(f"Existing tags (with use counts): {_fmt_vocab(known_tags)}.")
    if not lines:
        return ""
    return (" Reuse an existing path/tag verbatim when it genuinely fits (extend a "
            "path rather than inventing a parallel one); only create a new one if "
            "none apply. " + " ".join(lines))


def _root_folders(root_folders, default_root) -> str:
    if not root_folders:
        return ""
    names = ", ".join(root_folders)
    meanings = "; ".join(f"{name} — {desc}" for name, desc in root_folders.items())
    return (f" The path is core to the vault: any path starts with exactly one of "
            f"these root folders — {names} — followed by at most one sub-folder. "
            f"Never nest deeper than two levels. Root folder meanings: {meanings}. "
            f"If you cannot determine a path, use {default_root}.")


def _neighbours(notes) -> str:
    paths, tags = Counter(), Counter()
    for note in notes:
        if note.get("path"):
            paths[note["path"]] += 1
        for tag in note.get("tags") or []:
            tags[tag] += 1
    parts = []
    if paths:
        parts.append("filed under: " + ", ".join(f"{p} ({c})" for p, c in paths.most_common(5)))
    if tags:
        parts.append("commonly tagged: " + ", ".join(f"{t} ({c})" for t, c in tags.most_common(8)))
    hint = " Notes most similar to this one are " + "; ".join(parts) + "." if parts else ""
    examples = "\n".join(f"- \"{n['title']}\" -> type={n['note_type']}, "
                         f"path={n.get('path')}, tags={n.get('tags') or []}" for n in notes)
    return hint + ((" Similar past notes and how they were classified:\n" + examples)
                   if examples else "")


def enrichment_prompt(known_paths, known_tags, similar_notes,
                      root_folders, default_root, max_distance) -> str:
    neighbours = similar_notes or []
    has_distance = any(n.get("distance") is not None for n in neighbours)
    strong = ([n for n in neighbours
               if n.get("distance") is not None and n["distance"] <= max_distance]
              if has_distance else neighbours)
    if strong:
        neighbour_block = _neighbours(strong)
    elif neighbours:
        neighbour_block = (" None of the user's existing notes are closely related "
                           "to this one, so do not force-fit an existing path.")
    else:
        neighbour_block = ""
    return ("You organize a person's brain-dump notes (Ukrainian or English) into "
            "a PARA-style vault. Classify the note and extract metadata. Return "
            "strict JSON with keys: reasoning, type, title, path, tags, priority. "
            "type is one of idea, task, reminder, note, question, link; priority is "
            "one of low, med, high; title is at most 8 words; tags contains at most "
            "5 lowercase topic keywords; path has at most two levels."
            + _root_folders(root_folders, default_root)
            + _vocabulary(known_paths, known_tags) + neighbour_block)


def reminder_extraction_prompt(now) -> str:
    return (
        "Extract a reminder from the user's message. Return strict JSON: "
        "{\"is_reminder\": bool, \"remind_at\": string|null}. remind_at is an "
        f"ISO-8601 local time. Current local time is "
        f"{now.strftime('%Y-%m-%dT%H:%M:%S')} ({now.tzname()}). Resolve relative "
        "expressions. Use 09:00 for a date without time; morning=09:00, noon=12:00, "
        "afternoon=15:00, evening=19:00, night=21:00. For an indefinite quantity "
        f"assume {config.REMINDER_FEW_COUNT}; for 'later' use "
        f"{config.REMINDER_LATER} from now."
    )
