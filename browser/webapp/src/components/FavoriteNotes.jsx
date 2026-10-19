import CountRing from "./CountRing.jsx";

// The favourite notes, one circle per folder, scrolling sideways when there are
// more than fit. Each is the Inbox's disc-and-dashes drawing a little smaller,
// with the folder's name under it, clipped with an ellipsis.
//
// A readout for now — nothing here is tappable. The key is the stored path, the
// one thing that tells `Projects/api` from `Areas/api` apart.
export default function FavoriteNotes({ groups }) {
  return (
    <div className="hdr-stories" role="list" aria-label="Favorite folders">
      {groups.map((group) => (
        <div
          className="story"
          role="listitem"
          key={group.root + "/" + group.sub}
          title={group.root + (group.sub ? "/" + group.sub : "")}
        >
          <CountRing count={group.count} />
          <span className="story-name">{group.label}</span>
        </div>
      ))}
    </div>
  );
}
