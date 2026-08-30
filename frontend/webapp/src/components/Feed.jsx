import { useApp } from "../store/AppContext.jsx";
import { notePathKey } from "../lib/format.js";
import NoteCard from "./NoteCard.jsx";

// Feed of full note-preview posts (newest first), filtered by the folder filter.
export default function Feed({ hidden }) {
  const { state } = useApp();
  const { feed, filterSel } = state;

  let body;
  if (feed === null) {
    body = <div className="empty">Loading…</div>;
  } else if (!feed.length) {
    body = <div className="empty">No notes yet.<br />Send one to the bot to get started.</div>;
  } else {
    const items = filterSel ? feed.filter((d) => filterSel.has(notePathKey(d))) : feed;
    body = items.length
      ? items.map((d) => <NoteCard key={d.id} detail={d} />)
      : <div className="empty">No notes match the folder filter.</div>;
  }
  return <div id="notes" className={"view" + (hidden ? " hidden" : "")}>{body}</div>;
}
