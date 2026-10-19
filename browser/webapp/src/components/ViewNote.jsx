import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { fmtDateTime } from "../lib/format.js";
import {
  fetchViewNote,
  listViewNoteChildren,
  listViewNoteRoots,
} from "../lib/api.js";
import PathWheel from "./PathWheel.jsx";
import { CalendarGlyph, FolderGlyph, ModifiedGlyph } from "./glyphs.jsx";

// The three capture kinds the bar offers alongside typing — the same three the
// bot already accepts (text, voice, photo), plus the one piece of metadata
// worth setting while the thought is still fresh.
//
// NONE OF THEM DO ANYTHING, deliberately: this page reads and does not save.
// They are `disabled` rather than inert with a live look: a dimmed button
// reads as not-yet, where one that depresses and does nothing reads as a bug.
const CAPTURE_KINDS = [
  {
    kind: "photo",
    label: "Add a photo",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M3 8.5A1.5 1.5 0 0 1 4.5 7h2.2l1.2-2h8.2l1.2 2h2.2A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5v-9Z" />
        <circle cx="12" cy="12.5" r="3.4" />
      </svg>
    ),
  },
  {
    kind: "voice",
    label: "Record a voice note",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3" />
      </svg>
    ),
  },
  {
    kind: "reminder",
    label: "Set a reminder",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <circle cx="12" cy="13" r="8" />
        <path d="M12 9v4.3l2.8 1.7M9 2.5 5.5 5M15 2.5 18.5 5" />
      </svg>
    ),
  },
];

// What the note *is*, as opposed to what it says: where it is filed (the root
// folder, then the folder one level below it), what it is about. They sit below the view toggle as plain
// circles rather than in a capsule — every control on this edge is one `.fab`,
// the same circle as the ✕ and ✓.
//
// Two of them are live wheels; `tags` is still inert; the favourite star is a
// placeholder (see the state below). The reminder button
// stays in the bottom pill — it is metadata too, but moving it would churn a
// bar that is already settled.
const METADATA_FIELDS = [
  {
    field: "path",
    label: "Set the folder",
    icon: <FolderGlyph />,
  },
  {
    field: "subpath",
    label: "Set the sub-folder",
    // "/.." — the path one level on, drawn as strokes like every other glyph
    // (a slash and two dots; the dots are zero-length round-capped segments).
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9.5 4.5 5 19.5" />
        <path d="M14.5 18.5h.01M19.5 18.5h.01" />
      </svg>
    ),
  },
  {
    field: "tags",
    label: "Add tags",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9.5 4 8 20M16 4l-1.5 16M4.5 9h15M4 15h15" />
      </svg>
    ),
  },
  // No `icon` here: the star is drawn filled or outlined by whether it is on,
  // which a static element cannot know, so the button below renders it itself.
  { field: "favorite", label: "Mark as favorite" },
];

// The View note page.
//
// Born as a copy of the Add note page opened on an existing note, and kept as
// its own component so the two can grow apart: its reads, its styles
// (`.viewnote*`) and its tests are its own. Only `PathWheel` and the small
// glyphs are shared.
//
// **Reads only for now.** There is no save endpoint behind it, so the text is
// `readOnly`, the tick is dimmed ("not yet" rather than a button that does
// nothing), and the path wheels, the star and the info block are local to the
// page and reset on every open. Opened by a long press on an Explorer row.
//
// Always mounted and hidden with `opacity: 0` + `pointer-events: none`, like the
// Add note page, but with none of its keyboard machinery: nothing here is typed
// into, so no focus gesture, no visual-viewport sizing.
export default function ViewNote({ note_id = null }) {
  const { state, closeViewNote } = useApp();
  // "loading" | "ready" | "failed".
  const [status, setStatus] = useState("loading");
  const [note, setNote] = useState(null);
  const [path, setPath] = useState("");
  // Which wheel is open: "" | "path" (the root) | "subpath" (the level below).
  const [openWheel, setOpenWheel] = useState("");
  // PLACEHOLDER, as on the Add note page: fills the star here, stores nothing.
  const [favorite, setFavorite] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [defaultDestination, setDefaultDestination] = useState("");
  const open = state.viewNoteOpen;

  useEffect(() => {
    if (!open) return;

    // Reset on every open, and when a different note replaces the shown one.
    setNote(null);
    setPath("");
    setOpenWheel("");
    setFavorite(false);
    setCaptureOpen(false);
    setInfoOpen(false);
  }, [open, note_id]);

  useEffect(() => {
    if (!open || note_id == null) return;

    let live = true;
    setStatus("loading");
    fetchViewNote(note_id).then(
      (loaded) => {
        if (!live) return;
        setNote(loaded);
        setPath(loaded.path || "");
        setStatus("ready");
      },
      () => { if (live) setStatus("failed"); },
    );

    return () => { live = false; };
  }, [open, note_id]);

  // `path` is "" | "Root" | "Root/child"; the two buttons are views of its
  // first two segments. A deeper loaded path is kept until a wheel changes it.
  const [root, child = ""] = path.split("/");
  useEffect(() => {
    if (!infoOpen || path || defaultDestination) return;
    let live = true;
    listViewNoteRoots().then((roster) => { if (live) setDefaultDestination(roster.initial); });

    return () => { live = false; };
  }, [infoOpen, path, defaultDestination]);

  const dated = note !== null && !!note.created_at;
  const infoRows = [
    ...(dated ? [
      { key: "created", icon: <CalendarGlyph />, value: fmtDateTime(note.created_at, note.timezone) },
      { key: "modified", icon: <ModifiedGlyph />, value: fmtDateTime(note.updated_at, note.timezone) },
    ] : []),
    { key: "path", icon: <FolderGlyph />, value: path || defaultDestination, isDefault: !path },
  ];

  return (
    <div
      className={"viewnote" + (open ? " show" : "")}
      role="dialog"
      aria-modal="true"
      aria-label="View note"
      aria-hidden={open ? undefined : true}
    >
      {infoOpen && (
        <div className="viewnote-info">
          {infoRows.map((row) => (
            <div className="viewnote-info-row" key={row.key}>
              <span className="viewnote-info-icon">{row.icon}</span>
              <span className={"viewnote-info-value" + (row.isDefault ? " is-default" : "")}>
                {row.value || "—"}
              </span>
            </div>
          ))}
        </div>
      )}
      <textarea
        className="viewnote-body"
        value={note ? note.text : ""}
        placeholder={status === "loading" ? "Loading…" : ""}
        readOnly
        spellCheck={false}
        tabIndex={open ? 0 : -1}
        onClick={() => setCaptureOpen(false)}
      />
      {/* Stays open on a failed read: being dropped back mid-gesture reads as a
          crash, and a blank page would look like a note with an empty body. */}
      {status === "failed" && (
        <div className="viewnote-error">Couldn’t load this note.</div>
      )}
      <button
        className={"viewnote-info-btn" + (infoOpen ? " active" : "")}
        aria-label="Note info"
        title="Note info"
        aria-expanded={infoOpen}
        onClick={() => setInfoOpen((on) => !on)}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5.5" />
          <path d="M12 7.7h.01" />
        </svg>
      </button>

      <div className="viewnote-side">
        <button className="fab viewnote-ai" aria-label="Ask AI" title="Ask AI" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3.2l1.9 4.9 4.9 1.9-4.9 1.9L12 16.8l-1.9-4.9L5.2 10l4.9-1.9L12 3.2Z" />
            <path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" />
          </svg>
        </button>

        {METADATA_FIELDS.map((meta) => {
          if (meta.field === "tags") {
            return (
              <button key={meta.field} className="fab" aria-label={meta.label} title={meta.label} disabled>
                {meta.icon}
              </button>
            );
          }

          if (meta.field === "favorite") {
            return (
              <button
                key={meta.field}
                className={"fab" + (favorite ? " set" : "")}
                aria-label={meta.label}
                title={meta.label}
                aria-pressed={favorite}
                onClick={() => setFavorite((on) => !on)}
              >
                <svg viewBox="0 0 24 24" fill={favorite ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.7L12 16.6l-5.1 2.7 1-5.7-4.1-4 5.7-.8L12 3.6Z" />
                </svg>
              </button>
            );
          }

          const isRoot = meta.field === "path";
          const chosen = isRoot ? root : child;

          return (
            <div className="path-anchor" key={meta.field}>
              <button
                className={"fab" + (chosen ? " set" : "")}
                aria-label={chosen ? meta.label + ": " + chosen : meta.label}
                title={chosen || meta.label}
                aria-expanded={openWheel === meta.field}
                disabled={!isRoot && !root}
                onClick={() => setOpenWheel((current) => (current === meta.field ? "" : meta.field))}
              >
                {meta.icon}
              </button>

              {openWheel === meta.field && (isRoot ? (
                <PathWheel
                  value={root}
                  load={listViewNoteRoots}
                  onPick={(picked) => {
                    setPath((current) => (picked === root ? current : picked));
                    setOpenWheel("");
                  }}
                  onClose={() => setOpenWheel("")}
                />
              ) : (
                <PathWheel
                  value={child}
                  load={() => listViewNoteChildren(root)}
                  allowNew
                  placeholder="Filter or new sub-folder…"
                  onPick={(picked) => { setPath(root + "/" + picked); setOpenWheel(""); }}
                  onClose={() => setOpenWheel("")}
                />
              ))}
            </div>
          );
        })}
      </div>

      <div className="viewnote-bar">
        <button className="fab" aria-label="Close" onClick={closeViewNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>

        {captureOpen ? (
          <nav className="tabbar" aria-label="Capture">
            <div className="tab-icons">
              {CAPTURE_KINDS.map((capture) => (
                <button key={capture.kind} className="tab" aria-label={capture.label} title={capture.label} disabled>
                  {capture.icon}
                </button>
              ))}
            </div>
          </nav>
        ) : (
          <button
            className="fab"
            aria-label="Add photo, voice or reminder"
            title="Add photo, voice or reminder"
            aria-expanded={false}
            onClick={() => setCaptureOpen(true)}
          >
            <ModifiedGlyph />
          </button>
        )}

        {/* Dimmed: there is nothing to save yet. */}
        <button className="fab commit" aria-label="Save" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 13l4 4L19 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
