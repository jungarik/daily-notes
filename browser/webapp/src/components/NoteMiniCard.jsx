import { fmtDateShort } from "../lib/format.js";

// Line icons that inherit the surrounding text color (currentColor).
const ico = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", viewBox: "0 0 24 24" };
export const FolderIcon = () => (
  <svg {...ico}><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z" /></svg>
);
export const CalendarIcon = () => (
  <svg {...ico}><rect x="3" y="4.5" width="18" height="16" rx="2" /><path d="M3 9.5h18M8 3v3M16 3v3" /></svg>
);
export const LinkIcon = () => (
  <svg {...ico}><path d="M9.5 14.5l5-5M11 6.8l1.3-1.3a3.4 3.4 0 0 1 4.8 4.8L15.8 11.6M12.2 17.2 10.9 18.5a3.4 3.4 0 0 1-4.8-4.8L7.4 12.4" /></svg>
);
export const PaperclipIcon = () => (
  <svg {...ico}><path d="M20.5 11.5 12 20a5 5 0 0 1-7-7l8-8a3.3 3.3 0 0 1 4.7 4.7l-8 8a1.7 1.7 0 0 1-2.4-2.4l7.2-7.2" /></svg>
);

// A compact reference card for a note: title plus a meta line of folder, date,
// link count and attachment count. Shared by the chat tab (inline note
// references, clickable) and the map tab (graph nodes, where the canvas owns
// input and the card is inert). Omitting `onOpen` renders it non-interactive.
export default function NoteMiniCard({ id, note, onOpen }) {
  const title = (note && note.title) || ("Note #" + id);
  const path = note && note.path;
  const date = note && note.date ? fmtDateShort(note.date) : "";
  const links = note && Number.isFinite(note.links) ? note.links : 0;
  const attachments = note && Number.isFinite(note.attachments) ? note.attachments : 0;
  const hasMeta = path || date || links > 0 || attachments > 0;
  const Tag = onOpen ? "button" : "div";

  return (
    <Tag className="note-mini" {...(onOpen ? { onClick: () => onOpen(id) } : {})}>
      <span className="note-mini-title">{title}</span>
      {hasMeta && (
        <span className="note-mini-meta">
          {path && (
            <span className="note-mini-path" title={path}>
              <FolderIcon />
              <bdi className="note-mini-path-txt">{path}</bdi>
            </span>
          )}
          {date && <span className="note-mini-date" title="created"><CalendarIcon />{date}</span>}
          {links > 0 && <span className="note-mini-count" title="linked notes"><LinkIcon />{links}</span>}
          {attachments > 0 && <span className="note-mini-count" title="attachments"><PaperclipIcon />{attachments}</span>}
        </span>
      )}
    </Tag>
  );
}
