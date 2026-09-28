import { useApp } from "../store/AppContext.jsx";

// The Add note page.
//
// A full-screen overlay rather than a `view`: it covers the header and the
// dock, which is what puts its two buttons in the screen's real top corners.
// Nothing is captured yet — the Mini App has no note-create endpoint (capture
// lives behind the bot's `/api/telegram_bot/notes`), so both the tick and the
// cross simply close. The tick is where the save call goes once there is one.
export default function AddNote() {
  const { state, closeAddNote } = useApp();

  if (!state.addNoteOpen) return null;

  return (
    <div className="addnote" role="dialog" aria-modal="true" aria-label="Add note">
      <div className="addnote-bar">
        <button className="addnote-btn" aria-label="Done" onClick={closeAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 13l4 4L19 7" />
          </svg>
        </button>
        <button className="addnote-btn" aria-label="Cancel" onClick={closeAddNote}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <div className="addnote-body" />
    </div>
  );
}
