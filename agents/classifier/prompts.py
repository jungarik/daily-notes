"""The prompt that classifies one note into vault metadata.

Moved here with the nodes that use it. It never had anything to do with the
enricher's planning prompt above it — that one chooses a write tool, this one
fills in type, title, path, tags and priority for a note already chosen.

`enrichment_prompt` became `classification_prompt`: the agent is the classifier
and the word it produces is a classification, so the old name only survived
because the code lived in a package called enrichment.
"""

from collections import Counter


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


def classification_prompt(known_paths, known_tags, similar_notes,
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
