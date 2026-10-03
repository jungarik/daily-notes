import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { visibleViewport } from "../lib/format.js";
import { createNote, fetchEditableNote, saveNote } from "../lib/api.js";
import MarkdownHelp from "./MarkdownHelp.jsx";
import PathWheel from "./PathWheel.jsx";

// The three capture kinds the bar offers alongside typing — the same three the
// bot already accepts (text, voice, photo), plus the one piece of metadata
// worth setting while the thought is still fresh.
//
// NONE OF THEM DO ANYTHING YET, deliberately. The Mini App has no note-create
// endpoint at all, so wiring these before the tick can save would build a photo
// picker whose result has nowhere to go. They are `disabled` rather than inert
// with a live look: a button that depresses and then does nothing reads as a
// bug, whereas a dimmed one reads as not-yet.
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

// What the note *is*, as opposed to what it says: where it is filed, what it
// connects to, what it is about. They sit below the view toggle as plain
// circles rather than in a capsule — every control on this edge is one `.fab`,
// the same circle as the ✕ and ✓.
//
// Inert, like the capture buttons: there is no note-create endpoint, so a path
// picker would set a field on a note that is never saved. The reminder button
// stays in the bottom pill — it is metadata too, but moving it would churn a
// bar that is already settled.
const METADATA_FIELDS = [
  {
    field: "path",
    label: "Set the folder",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4L11 7.5h8.5A1.5 1.5 0 0 1 21 9v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-11Z" />
      </svg>
    ),
  },
  {
    field: "link",
    label: "Link to another note",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.5 1.5" />
        <path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 0 0 5.7 5.7l1.5-1.5" />
      </svg>
    ),
  },
  {
    field: "tags",
    label: "Add tags",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M11.4 3.5H5a1.5 1.5 0 0 0-1.5 1.5v6.4a1.5 1.5 0 0 0 .44 1.06l7.6 7.6a1.5 1.5 0 0 0 2.12 0l6.4-6.4a1.5 1.5 0 0 0 0-2.12l-7.6-7.6a1.5 1.5 0 0 0-1.06-.44Z" />
        <path d="M7.8 7.8h.01" />
      </svg>
    ),
  },
];

// The Add note page.
//
// A full-screen overlay rather than a `view`: it covers the header and the
// dock, and carries its own floating bar in their place. Nothing is captured
// yet — the Mini App has no note-create endpoint (capture lives behind the
// bot's `/api/telegram_bot/notes`), so both the tick and the cross simply
// close. The tick is where the save call goes once there is one.
//
// **This component always renders.** Closed, it is transparent and inert; it is
// never unmounted and never `display: none`, because a textarea in either state
// cannot be focused — and focusing it is how the keyboard opens. iOS and
// Telegram's webview raise the keyboard only for a `focus()` that happens
// inside a real user gesture, so the plus button focuses this field
// synchronously in its own click handler (see `openAddNote` in AppContext)
// rather than anything here doing it after mount. A `setTimeout` after render,
// which is what this used to do, is past the gesture and gets a caret with no
// keyboard.
// `note_id` names an existing note to edit; null opens an empty editor. The
// note's text is read from `GET /api/addnote/{id}` after the page is already
// up — see the fetch below for why it cannot be awaited first. Saving has no
// endpoint yet, so both modes still close without persisting.
export default function AddNote({ note_id = null }) {
  const { state, closeAddNote, addNoteInputRef, reload } = useApp();
  const [text, setText] = useState("");
  // "loading" | "ready" | "failed" for an existing note; always "ready" for a
  // new one, which has nothing to wait for.
  const [status, setStatus] = useState("ready");
  // The rest of the loaded note — path, tags, attachments, linked ids. Held
  // but not yet rendered: the side buttons that own these fields are still
  // `disabled`, because each needs an editor of its own (a path picker in the
  // overlay, a tag input, a link chooser) and there is no update endpoint to
  // save any of them to. Keeping it in state is what makes those passes a UI
  // change rather than a UI change plus another round trip.
  const [note, setNote] = useState(null);
  // The note's folder. "" means the user has not chosen and the note has none
  // — it will be filed under the API's `default_root` on save, so the button
  // stays unlit rather than claiming a choice nobody made.
  const [path, setPath] = useState("");
  const [pathOpen, setPathOpen] = useState(false);
  // "" | "saving" | an error line. One value rather than a boolean plus a
  // string: the page is never saving *and* reporting a failure, and two flags
  // that cannot both be true are two chances to leave one of them stale.
  const [saveState, setSaveState] = useState("");
  // The visible area while the keyboard is up. The whole overlay is sized to
  // it, so everything anchored to the overlay's bottom or centre lands in the
  // part of the screen you can actually see.
  const [box, setBox] = useState(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const open = state.addNoteOpen;

  useEffect(() => {
    if (!open) return;

    // Cleared on every open, including when switching from an edited note to
    // a new one: the plus badge must give an empty editor, not the last note's
    // body. `note_id` is in the dependencies for the same reason — opening a
    // different note while the page is up has to reset too.
    setText("");
    setNote(null);
    setPath("");
    setPathOpen(false);
    setSaveState("");
    // Reset per visit rather than persisting: a capture screen should open the
    // same way every time, not in whatever state it was left.
    setHelpOpen(false);
  }, [open, note_id]);

  // The text arrives *after* the page is open, and that order is forced: the
  // keyboard only rises for a `focus()` inside the opening gesture, so
  // `openAddNote` focuses synchronously and nothing can be awaited before the
  // page exists. Hence a placeholder rather than a spinner — the field is
  // already focused and the user is already looking at it.
  useEffect(() => {
    if (!open || note_id == null) { setStatus("ready"); return; }

    let live = true;
    setStatus("loading");
    fetchEditableNote(note_id).then(
      (loaded) => {
        if (!live) return;
        // Never clobber what the user has typed in the gap. Their keystrokes
        // are newer than this response, and a textarea that erases itself a
        // second after opening is the worst failure available here.
        setText((typed) => (typed ? typed : loaded.text || ""));
        setNote(loaded);
        // The note's own folder, pre-selected: opening Edit on a filed note
        // should show where it already lives, not an empty field.
        setPath((chosen) => (chosen ? chosen : loaded.path || ""));
        setStatus("ready");
      },
      () => { if (live) setStatus("failed"); },
    );

    return () => { live = false; };
  }, [open, note_id]);

  useEffect(() => {
    const viewport = window.visualViewport;

    if (!open || !viewport) return;

    const measure = () => setBox(visibleViewport(viewport));

    measure();
    // `scroll` as well as `resize`: iOS scrolls the visual viewport when the
    // keyboard appears, and only the scroll event fires for that part.
    viewport.addEventListener("resize", measure);
    viewport.addEventListener("scroll", measure);

    return () => {
      viewport.removeEventListener("resize", measure);
      viewport.removeEventListener("scroll", measure);
    };
  }, [open]);

  const saving = saveState === "saving";
  // The API requires at least one character, so an empty save is a 422 the
  // user cannot act on. A dimmed tick says "not yet" where an error message
  // would say "something went wrong".
  const canSave = text.trim() !== "" && !saving;

  const save = async () => {
    if (!canSave) return;

    setSaveState("saving");
    // Tags go as an empty list: their button is still disabled, so there is
    // nothing to send. `path` empty is not a gap either — the API files the
    // note under the configured default root, which is why the button is only
    // lit for an actual choice.
    const body = { text: text.trim(), path, tags: [] };

    try {
      if (note_id == null) await createNote(body);
      else await saveNote(note_id, body);
    } catch (err) {
      // The page stays open with the text still in the field. Closing on a
      // failure would discard what the user wrote in order to report that it
      // was not saved.
      setSaveState(String(err).includes("422")
        ? "That folder isn’t valid. Pick another."
        : "Couldn’t save. Try again.");

      return;
    }

    // Close first, then refresh: the vault's own views (feed, explorer, map,
    // header counts) all derive from the boot fetch, so `reload` is the one
    // path that means "the vault changed" — the same one the ⋮ menu's path
    // change and delete already take. Awaiting it before closing would hold
    // the editor open over a round trip that has nothing to do with the save.
    closeAddNote();
    reload();
  };

  return (
    <div
      className={"addnote" + (open ? " show" : "")}
      role="dialog"
      aria-modal="true"
      aria-label={note_id == null ? "Add note" : "Edit note"}
      aria-hidden={open ? undefined : true}
      // Sized to the visible area rather than the whole screen, so the bar at
      // its bottom edge and the column at its centre both land where you can
      // see them once the keyboard is up. `bottom: auto` releases the `inset:
      // 0` in CSS, which would otherwise fight the explicit height.
      style={box ? { top: box.top, height: box.height, bottom: "auto" } : undefined}
    >
      <textarea
        ref={addNoteInputRef}
        className="addnote-body"
        value={text}
        placeholder={status === "loading" ? "Loading…" : "Write a note…"}
        autoComplete="off"
        autoCapitalize="sentences"
        spellCheck={false}
        // Out of the tab order while closed — it is still in the DOM, and a
        // field nobody can see should not be reachable by keyboard. `focus()`
        // works on a tabIndex -1 element, which is all the plus button needs.
        tabIndex={open ? 0 : -1}
        onChange={(e) => setText(e.target.value)}
      />
      {/* Stays open on a failed read rather than closing: being dropped back
          to the feed mid-gesture reads as a crash, and nothing is saved here
          anyway. An empty editor with no message would be indistinguishable
          from a note whose body really is empty. */}
      {(status === "failed" || (saveState && !saving)) && (
        <div className="addnote-error">
          {status === "failed" ? "Couldn’t load this note." : saveState}
        </div>
      )}
      {/* Help, in the top-right corner. No glass: the glyph is already a
          circled `?`, so out of the capsule it *is* "just a question icon and
          a circle" with nothing else drawn around it. */}
      <div className="addnote-help">
        <button
          className={"addnote-help-btn" + (helpOpen ? " active" : "")}
          aria-label="Markdown"
          title="Markdown"
          aria-expanded={helpOpen}
          onClick={() => setHelpOpen((open) => !open)}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M9.4 9.3a2.7 2.7 0 1 1 3.4 3.2c-.6.2-.8.7-.8 1.3v.4" />
            <path d="M12 17.3h.01" />
          </svg>
        </button>

        {/* Hangs below the button and grows leftward — anchored at `right: 0`
            so its right edge stays on the button's, rather than running off
            the screen it is pinned to the corner of. */}
        {helpOpen && <MarkdownHelp onClose={() => setHelpOpen(false)} />}
      </div>

      {/* The right edge: AI on its own, then the note's metadata. All the same
          `.fab` circle as the ✕ and ✓, stacked and centred as one group so the
          column stays balanced whatever it holds. */}
      <div className="addnote-side">
        {/* Set apart by a wider gap, not a different shape: it acts *on* the
            note rather than describing it, which is a different kind of thing
            from the three below. Inert — there is nothing for it to act on
            until the note can be saved. */}
        <button className="fab addnote-ai" aria-label="Ask AI" title="Ask AI" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3.2l1.9 4.9 4.9 1.9-4.9 1.9L12 16.8l-1.9-4.9L5.2 10l4.9-1.9L12 3.2Z" />
            <path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" />
          </svg>
        </button>

        {METADATA_FIELDS.map((meta) => (
          meta.field === "path" ? (
            // The one live metadata control. Its wheel is anchored here rather
            // than at the page level so it is positioned by the button it
            // belongs to — `right: 100%` on this wrapper is "just left of the
            // circle", which stays true wherever the column ends up.
            <div className="path-anchor" key={meta.field}>
              <button
                className={"fab" + (path ? " set" : "")}
                aria-label={path ? "Folder: " + path : meta.label}
                title={path || meta.label}
                aria-expanded={pathOpen}
                onClick={() => setPathOpen((wheel) => !wheel)}
              >
                {meta.icon}
              </button>

              {pathOpen && (
                <PathWheel
                  value={path}
                  onPick={(picked) => { setPath(picked); setPathOpen(false); }}
                  onClose={() => setPathOpen(false)}
                />
              )}
            </div>
          ) : (
            <button
              key={meta.field}
              className="fab"
              aria-label={meta.label}
              title={meta.label}
              disabled
            >
              {meta.icon}
            </button>
          )
        ))}
      </div>

      {/* No keyboard arithmetic here any more: the overlay itself ends where
          the keyboard begins, so an ordinary bottom offset is above it. */}
      <div className="addnote-bar">
        <button className="fab" aria-label="Cancel" onClick={closeAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>

        {/* Same glass capsule the dock's tab pill uses, between the two
            circles exactly as it is on the main page. */}
        <nav className="tabbar" aria-label="Capture">
          <div className="tab-icons">
            {CAPTURE_KINDS.map((capture) => (
              <button
                key={capture.kind}
                className="tab"
                aria-label={capture.label}
                title={capture.label}
                disabled
              >
                {capture.icon}
              </button>
            ))}
          </div>
        </nav>

        {/* Dimmed while the request is in flight *and* when there is nothing
            to save, and `canSave` guards the handler too: a second tap on a
            slow connection would otherwise create the same note twice. */}
        <button className="fab commit" aria-label={saving ? "Saving…" : "Save"}
          onClick={save} disabled={!canSave}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 13l4 4L19 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
