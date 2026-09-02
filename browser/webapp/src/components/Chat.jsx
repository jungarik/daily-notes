import { useEffect, useState } from "react";
import { useApp } from "../store/AppContext.jsx";

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

function Message({ m, onConfirm, onCite }) {
  if (m.pending) {
    return <div className="msg bot"><span className="typing"><i /><i /><i /></span></div>;
  }
  if (m.action) {
    return m.action.kind === "select"
      ? <SelectMsg action={m.action} onConfirm={onConfirm} />
      : <ConfirmMsg action={m.action} onConfirm={onConfirm} />;
  }
  const cls = "msg " + (m.role === "user" ? "user" : "bot") + (m.muted ? " muted" : "");
  return (
    <div className={cls}>
      {m.text || ""}
      {m.citations && m.citations.length > 0 && (
        <div className="cite-row">
          {m.citations.map((c, i) => (
            <button key={i} className="cite-chip" onClick={() => onCite(c.note_id)}>
              {"📄 " + (c.title || "note")}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Agentic chat: renders the conversation. Answers are read-only; write requests
// are handed to the enrich agent and shown as a Confirm/Cancel card.
export default function Chat({ hidden }) {
  const { state, confirmChat, openNote } = useApp();
  const msgs = state.chat.messages;

  useEffect(() => {
    if (hidden) return;
    const main = document.querySelector("main");
    if (main) requestAnimationFrame(() => { main.scrollTop = main.scrollHeight; });
  }, [msgs, hidden]);

  return (
    <div id="chat" className={"view" + (hidden ? " hidden" : "")}>
      <div id="chatLog">
        {!msgs.length && (
          <div className="chat-empty">
            Ask anything about your notes.<br />The assistant can search, summarize, and act on them.
          </div>
        )}
        {msgs.map((m, i) => <Message key={i} m={m} onConfirm={confirmChat} onCite={openNote} />)}
      </div>
    </div>
  );
}
