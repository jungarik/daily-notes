// The small glyphs the Add-note and View-note pages share: the folder the path
// button and the path row draw, and the calendar and pencil of the info block's
// dates. They are shared, not duplicated, because they are one drawing of one
// thing — the two pages differ in behaviour, not in what a folder looks like.
//
// All decorative — the text beside each says what it is — hence `aria-hidden`,
// and sized by the CSS of whichever container they sit in. `ModifiedGlyph` and
// not `PencilGlyph`: that is a retired name a test forbids.
export function Glyph({ children }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

export function FolderGlyph() {
  return (
    <Glyph>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4L11 7.5h8.5A1.5 1.5 0 0 1 21 9v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-11Z" />
    </Glyph>
  );
}

export function CalendarGlyph() {
  return (
    <Glyph>
      <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </Glyph>
  );
}

export function ModifiedGlyph() {
  return (
    <Glyph>
      <path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19l-4 1Z" />
      <path d="M14.5 6.5l3 3" />
    </Glyph>
  );
}

