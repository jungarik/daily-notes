import { useState } from "react";
import { mediaUrl } from "../lib/api.js";
import { dateText, tagsText, linkedItems, clampText } from "../lib/format.js";
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

// The note's own words, clamped with an inline "… more".
//
// Inline text rather than a button: the control belongs to the sentence it
// interrupts, and a button here would read as an action on the note (enrich,
// open, link) rather than as more of the same paragraph. Collapsing back is
// offered too — a feed of expanded notes is a feed you cannot skim.
function Body({ text }) {
  const [expanded, setExpanded] = useState(false);
  const { head, rest } = clampText(text);

  // `rest` empty means the note is short enough to show whole, so there is no
  // control — the component never compares lengths itself.
  if (!rest) return <div className="card-body">{text}</div>;

  // Expanded renders the original string, not `head + rest`: the split trims
  // the whitespace at the seam, so re-joining them would eat the space between
  // two words.
  return (
    <div className="card-body">
      {expanded ? text : head}
      <span className="card-more" role="button" onClick={() => setExpanded(!expanded)}>
        {expanded ? " less" : "… more"}
      </span>
    </div>
  );
}

// THE note card — shared by the feed and the explorer's preview sheet.
//
// The note's own text comes first, under the images: it is what the user
// wrote, and the metadata around it (date, path, tags) is machine-written
// description of it. Reading order follows that.
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
      {text ? <Body text={text} /> : (
        // A note with neither text nor images is not a blank card — say so.
        // With images it needs no placeholder: the pictures are the note.
        !hasImages && <div className="card-body muted">(empty note)</div>
      )}
      <div className="post-head">
        <div className="card-date">{dt}</div>
        <span
          className="post-dots"
          role="button"
          onClick={(e) => {
            e.stopPropagation();
            openCtx(
              // The sheet quotes this back ("Delete “…”?"), so it gets the
              // same label the rest of the app shows — the note's own opening
              // words rather than an enriched title nothing else displays.
              { type: "note", id: detail.id, path: detail.path, name: detail.label },
              e.currentTarget.getBoundingClientRect()
            );
          }}
        >⋮</span>
      </div>
      <div className="card-path">{"📁 " + detail.path}</div>
      {tags && <div className="card-meta">{tags}</div>}
      {/* No heading. A row of 🔗-prefixed chips is self-describing, and
          "No linked notes yet" was a line of text to report the absence of
          something the user had not asked about. Nothing renders when there
          is nothing to show. */}
      {links.length > 0 && (
        <div className="card-links">
          <div className="links-row">
            {links.map((it) => (
              <button key={it.id} className="link-chip" onClick={() => openNote(it.id)}>
                {"🔗 " + it.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
