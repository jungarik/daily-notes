import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { keyboardInset } from "../lib/format.js";

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
  const open = state.addNoteOpen;

  useEffect(() => {
    if (!open) return;

    setText("");
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
      <div
        className="addnote-bar"
        style={{ bottom: `calc(30px + env(safe-area-inset-bottom, 0px) + ${inset}px)` }}
      >
        <button className="fab" aria-label="Cancel" onClick={closeAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
        <button className="fab commit" aria-label="Done" onClick={closeAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 13l4 4L19 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
