import { useState } from "react";
import { mediaUrl } from "../lib/api.js";
import { dateText, tagsText, linkedItems } from "../lib/format.js";
import { useApp } from "../store/AppContext.jsx";

// Instagram-style image carousel with a position counter + dots.
function Carousel({ atts }) {
  const [idx, setIdx] = useState(0);
  if (!atts || !atts.length) return null;
  const onScroll = (e) => {
    const t = e.currentTarget;
    setIdx(Math.round(t.scrollLeft / Math.max(1, t.clientWidth)));
  };
  return (
    <div className="carousel">
      <div className="track" onScroll={onScroll}>
        {atts.map((a, i) => (
          <div className="slide" key={a.id != null ? a.id : i}>
            <img loading="lazy" decoding="async" alt="" src={mediaUrl(a.url)} />
          </div>
        ))}
      </div>
      {atts.length > 1 && <div className="count">{idx + 1 + "/" + atts.length}</div>}
      {atts.length > 1 && (
        <div className="dots">{atts.map((_, i) => <i key={i} className={i === idx ? "on" : ""} />)}</div>
      )}
    </div>
  );
}

// THE note card — shared by the feed and the browser's preview sheet.
export default function NoteCard({ detail }) {
  const { openNote, openCtx } = useApp();
  const text = (detail.text || "").trim();
  const hasImages = detail.attachments && detail.attachments.length;
  const tags = tagsText(detail);
  const dt = dateText(detail);
  const links = linkedItems(detail);

  return (
    <div className="post">
      <Carousel atts={detail.attachments} />
      <div className="post-head">
        <div className="card-title">
          {(detail.title || "untitled") + ".md"}
          {dt && <span className="card-date">{dt}</span>}
        </div>
        <span
          className="post-dots"
          role="button"
          onClick={(e) => {
            e.stopPropagation();
            openCtx(
              { type: "note", id: detail.id, path: detail.path, name: detail.title || "untitled" },
              e.currentTarget.getBoundingClientRect()
            );
          }}
        >⋮</span>
      </div>
      <div className="card-path">{"📁 " + (detail.path || "Inbox")}</div>
      {tags && <div className="card-meta">{tags}</div>}
      {(text || !hasImages) && (
        <div className={"card-body" + (text ? "" : " muted")}>{text || "(empty note)"}</div>
      )}
      <div className="card-links">
        <div className="links-label">{links.length ? "🔗 Linked notes" : "No linked notes yet"}</div>
        {links.length > 0 && (
          <div className="links-row">
            {links.map((it) => (
              <button key={it.id} className="link-chip" onClick={() => openNote(it.id)}>
                {"🔗 " + (it.title || "untitled")}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
