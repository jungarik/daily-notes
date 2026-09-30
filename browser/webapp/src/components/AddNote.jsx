import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { keyboardInset } from "../lib/format.js";
import MarkdownHelp from "./MarkdownHelp.jsx";

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

// The right-edge button's two faces. One control, not two: it shows the mode it
// will switch *to*, so an eye means "tap to read" and a pencil means "tap to
// write" — the pattern the dock's circles already use when their glyph becomes
// a ✕.
//
// Tapping swaps the glyph and nothing else. There is no markdown renderer yet,
// so switching the pane would show the same raw text twice; this is the control
// being designed, not the mode being built.
const EyeGlyph = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const PencilGlyph = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3Z" />
    <path d="M14.5 7.5 16.5 9.5" />
  </svg>
);

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
export default function AddNote() {
  const { state, closeAddNote, addNoteInputRef } = useApp();
  const [text, setText] = useState("");
  // How far the keyboard covers the window. Drives the bar's lift, so both
  // buttons stay reachable while typing instead of sitting under the keys.
  const [inset, setInset] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  // Which face the right-edge button shows. Nothing reads it but the glyph —
  // there is no renderer for it to drive yet.
  const [reading, setReading] = useState(false);
  const open = state.addNoteOpen;

  useEffect(() => {
    if (!open) return;

    setText("");
    // Both reset per visit rather than persisting: a capture screen should
    // open the same way every time, not in whatever state it was left.
    setHelpOpen(false);
    setReading(false);
  }, [open]);

  useEffect(() => {
    const viewport = window.visualViewport;

    if (!open || !viewport) return;

    const measure = () => setInset(keyboardInset(window.innerHeight, viewport));

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

  return (
    <div
      className={"addnote" + (open ? " show" : "")}
      role="dialog"
      aria-modal="true"
      aria-label="Add note"
      aria-hidden={open ? undefined : true}
    >
      <textarea
        ref={addNoteInputRef}
        className="addnote-body"
        value={text}
        placeholder="Write a note…"
        autoComplete="off"
        autoCapitalize="sentences"
        spellCheck={false}
        // Out of the tab order while closed — it is still in the DOM, and a
        // field nobody can see should not be reachable by keyboard. `focus()`
        // works on a tabIndex -1 element, which is all the plus button needs.
        tabIndex={open ? 0 : -1}
        onChange={(e) => setText(e.target.value)}
      />
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

      {/* One circle, same as the ✕ and ✓ below, centred on the right edge. It
          shows the mode it switches *to*. */}
      <button
        className="fab addnote-side"
        aria-label={reading ? "Write markdown" : "Rendered view"}
        title={reading ? "Write markdown" : "Rendered view"}
        aria-pressed={reading}
        onClick={() => setReading((on) => !on)}
      >
        {reading ? <PencilGlyph /> : <EyeGlyph />}
      </button>

      <div
        className="addnote-bar"
        style={{ bottom: `calc(30px + env(safe-area-inset-bottom, 0px) + ${inset}px)` }}
      >
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

        <button className="fab commit" aria-label="Done" onClick={closeAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 13l4 4L19 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
