import { useEffect, useRef, useState } from "react";
import { useApp } from "../store/AppContext.jsx";

const SearchGlyph = () => (
  <svg className="ic-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
);
const ChatGlyph = () => (
  <svg className="ic-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9A1.5 1.5 0 0 1 18.5 16H9l-4 3.5V16H5.5A1.5 1.5 0 0 1 4 14.5v-9Z" /></svg>
);
const CloseGlyph = () => (
  <svg className="ic-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
);

const TABS = [
  { view: "notes", label: "Notes", icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="4" y="4" width="16" height="6" rx="1.6" /><rect x="4" y="14" width="16" height="6" rx="1.6" /></svg> },
  { view: "map", label: "Map", icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="6" cy="18" r="2.3" /><circle cx="18.5" cy="15" r="2.3" /><circle cx="14" cy="5.5" r="2.3" /><path d="M7.9 16.6 12.4 7.4M16.3 13.4 8.1 17.1" /></svg> },
  { view: "browser", label: "Browser", icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z" /></svg> },
];

export default function Dock() {
  const { state, setView, toggleMode, closeMode, setSearchQuery, sendChat } = useApp();
  const { view, barMode } = state;
  const [text, setText] = useState("");
  const inputRef = useRef(null);

  useEffect(() => { setText(""); if (barMode) setTimeout(() => inputRef.current && inputRef.current.focus(), 60); }, [barMode]);

  const onInput = (e) => {
    setText(e.target.value);
    if (barMode === "search") setSearchQuery(e.target.value);
  };
  const submit = () => {
    if (barMode === "chat") { sendChat(text); setText(""); }
    else if (barMode === "search") setSearchQuery(text);
  };

  return (
    <div className={"dock" + (barMode ? " input" : "")}>
      <button className={"fab" + (view === "chat" ? " active" : "") + (view === "search" ? " hidden" : "")}
        aria-label="Chat" onClick={() => toggleMode("chat")}>
        <ChatGlyph /><CloseGlyph />
      </button>

      <nav className="tabbar">
        {!barMode ? (
          <div className="tab-icons">
            {TABS.map((t) => (
              <button key={t.view} className={"tab" + (view === t.view ? " active" : "")}
                aria-label={t.label} onClick={() => setView(t.view)}>{t.icon}</button>
            ))}
          </div>
        ) : (
          <div className="tab-input">
            {barMode === "chat"
              ? <svg className="ts-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9A1.5 1.5 0 0 1 18.5 16H9l-4 3.5V16H5.5A1.5 1.5 0 0 1 4 14.5v-9Z" /></svg>
              : <svg className="ts-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>}
            <input ref={inputRef} type="text" value={text}
              placeholder={barMode === "chat" ? "Ask about your notes…" : "Search notes…"}
              autoComplete="off" autoCapitalize="off" spellCheck={false}
              onChange={onInput}
              onKeyDown={(e) => { if (e.key === "Enter" && barMode === "chat") { e.preventDefault(); submit(); } }} />
            <button className="ts-send" aria-label="Send" onClick={submit}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M6 11l6-6 6 6" /></svg>
            </button>
          </div>
        )}
      </nav>

      <button className={"fab" + (view === "search" ? " active" : "") + (view === "chat" ? " hidden" : "")}
        aria-label="Search" onClick={() => toggleMode("search")}>
        <SearchGlyph /><CloseGlyph />
      </button>
    </div>
  );
}
