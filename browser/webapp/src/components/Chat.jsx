import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";
import { fmtDate } from "../lib/format.js";
import * as api from "../lib/api.js";

const NOTE_MARKER = /\[\[note:(\d+)\]\]/g;

function ConfirmMsg({ action, onConfirm }) {
  const [done, setDone] = useState(false);
  const act = (approve) => { if (done) return; setDone(true); onConfirm(approve); };
  return (
    <div className="msg bot confirm">
      <div className="confirm-text">{action.summary}</div>
      {!done && (
        <div className="confirm-actions">
          <button className="confirm-btn yes" onClick={() => act(true)}>Confirm</button>
          <button className="confirm-btn no" onClick={() => act(false)}>Cancel</button>
        </div>
      )}
    </div>
  );
}

// A select action (link_notes): the user checks which candidate notes to link.
function SelectMsg({ action, onConfirm }) {
  const candidates = (action.args && action.args.candidates) || [];
  const [sel, setSel] = useState(() => new Set((action.args && action.args.linked_note_ids) || []));
  const [done, setDone] = useState(false);
  const toggle = (id) => setSel((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
  const act = (approve) => {
    if (done) return;
    setDone(true);
    onConfirm(approve, approve ? [...sel] : []);
  };
  return (
    <div className="msg bot confirm select">
      <div className="confirm-text">{action.summary}</div>
      <div className="link-picker">
        {candidates.map((c) => (
          <label key={c.note_id} className={"link-opt" + (sel.has(c.note_id) ? " on" : "")}>
            <input type="checkbox" checked={sel.has(c.note_id)} disabled={done}
              onChange={() => toggle(c.note_id)} />
            <span className="link-opt-body">
              <span className="link-opt-title">{c.title || "note"}</span>
              {c.path && <span className="link-opt-path">{c.path}</span>}
            </span>
          </label>
        ))}
      </div>
      {!done && (
        <div className="confirm-actions">
          <button className="confirm-btn yes" disabled={sel.size === 0} onClick={() => act(true)}>
            {sel.size ? "Link " + sel.size : "Link"}
          </button>
          <button className="confirm-btn no" onClick={() => act(false)}>Cancel</button>
        </div>
      )}
    </div>
  );
}

// A compact reference card for a note mentioned in a reply. Click to expand the
// full preview sheet.
function NoteMiniCard({ id, note, onOpen }) {
  const title = (note && note.title) || ("Note #" + id);
  const path = note && note.path;
  const date = note && note.date ? fmtDate(note.date) : "";
  return (
    <button className="note-mini" onClick={() => onOpen(id)}>
      <span className="note-mini-title">{title}</span>
      {(path || date) && (
        <span className="note-mini-meta">
          {path && <span className="note-mini-path">{path}</span>}
          {date && <span className="note-mini-date">{date}</span>}
        </span>
      )}
    </button>
  );
}

// Split a reply into text blocks and note cards at each [[note:ID]] marker. Each
// card is isolated onto its own line regardless of how the model spaced it: text
// hugging a marker is trimmed and wrapped in its own block, so a marker left
// mid-sentence ("see [[note:5]] for details") still renders as prose line, then
// card, then prose line.
function renderReply(text, resolve, onOpen) {
  const parts = [];
  let last = 0;
  let key = 0;
  let match;
  const pushText = (raw) => {
    const value = raw.trim();
    if (value) parts.push(<div key={key++} className="msg-text">{value}</div>);
  };
  NOTE_MARKER.lastIndex = 0;
  while ((match = NOTE_MARKER.exec(text))) {
    pushText(text.slice(last, match.index));
    const id = Number(match[1]);
    parts.push(<NoteMiniCard key={key++} id={id} note={resolve(id)} onOpen={onOpen} />);
    last = match.index + match[0].length;
  }
  pushText(text.slice(last));
  return parts;
}

function Message({ m, onConfirm, onCite, resolve }) {
  if (m.pending) {
    return <div className="msg bot"><span className="typing"><i /><i /><i /></span></div>;
  }
  if (m.action) {
    return m.action.kind === "select"
      ? <SelectMsg action={m.action} onConfirm={onConfirm} />
      : <ConfirmMsg action={m.action} onConfirm={onConfirm} />;
  }
  const cls = "msg " + (m.role === "user" ? "user" : "bot") + (m.muted ? " muted" : "");
  const text = m.text || "";
  const hasMarker = m.role !== "user" && NOTE_MARKER.test(text);
  NOTE_MARKER.lastIndex = 0;
  const citations = (m.citations && m.citations.length) ? m.citations : [];
  return (
    <div className={cls}>
      {hasMarker ? renderReply(text, resolve, onCite) : text}
      {/* Fallback: references the model didn't inline still show as cards. */}
      {!hasMarker && citations.length > 0 && (
        <div className="note-mini-list">
          {citations.map((c) => (
            <NoteMiniCard key={c.note_id} id={c.note_id} note={c} onOpen={onCite} />
          ))}
        </div>
      )}
    </div>
  );
}

// Agentic chat: renders the conversation. Answers are read-only; write requests
// are handed to the enrich agent and shown as a Confirm/Cancel card. Notes the
// answer references render as inline cards that open the full preview.
export default function Chat({ hidden }) {
  const { state, confirmChat, openNote } = useApp();
  const msgs = state.chat.messages;
  const [cache, setCache] = useState({});

  // Citations across the thread give title/path/date for referenced notes.
  const citeMap = {};
  for (const m of msgs) {
    for (const c of m.citations || []) citeMap[c.note_id] = c;
  }
  const resolve = (id) => citeMap[id] || cache[id] || null;

  // Any marker id the model emitted that isn't cited is fetched on demand.
  useEffect(() => {
    const ids = new Set();
    for (const m of msgs) {
      if (m.role === "user" || !m.text) continue;
      let match;
      NOTE_MARKER.lastIndex = 0;
      while ((match = NOTE_MARKER.exec(m.text))) ids.add(Number(match[1]));
    }
    const missing = [...ids].filter((id) => !citeMap[id] && !cache[id]);
    if (!missing.length) return;
    let alive = true;
    Promise.all(missing.map((id) =>
      api.fetchNote(id)
        .then((n) => (n ? { note_id: id, title: n.title, path: n.path, date: n.created_at } : null))
        .catch(() => null)
    )).then((rows) => {
      if (!alive) return;
      const add = {};
      for (const r of rows) if (r) add[r.note_id] = r;
      if (Object.keys(add).length) setCache((prev) => ({ ...prev, ...add }));
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [msgs]);

  useEffect(() => {
    if (hidden) return;
    const main = document.querySelector("main");
    if (main) requestAnimationFrame(() => { main.scrollTop = main.scrollHeight; });
  }, [msgs, hidden, cache]);

  return (
    <div id="chat" className={"view" + (hidden ? " hidden" : "")}>
      <div id="chatLog">
        {!msgs.length && (
          <div className="chat-empty">
            Ask anything about your notes.<br />The assistant can search, summarize, and act on them.
          </div>
        )}
        {msgs.map((m, i) => (
          <Message key={i} m={m} onConfirm={confirmChat} onCite={openNote} resolve={resolve} />
        ))}
      </div>
    </div>
  );
}
