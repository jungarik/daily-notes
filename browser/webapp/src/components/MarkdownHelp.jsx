import { useEffect, useRef } from "react";

// The markdown cheat sheet, shown from the Add-note page's side bar.
//
// Ukrainian only, and hard-coded. The Mini App has no i18n layer — every other
// label it shows is either fixed English or translated server-side before being
// sent — and adding one for a single panel would put a second translation table
// beside `locales.json` for them to drift apart in. English gets written the
// day a second person needs it; until then this is one language's worth of
// strings in the language the vault is written in.
//
// Each row is `syntax` as typed and `sample` as it will look, styled directly
// rather than rendered: there is no markdown renderer yet, and hand-styling
// eight spans is both smaller and impossible to get wrong. The trade is that
// these samples can drift from the real renderer once one exists — worth a
// glance when it lands.
//
// No underline. Markdown has none: CommonMark has no syntax for it, and the
// only way to get one is raw HTML, which this app deliberately never renders.
const ROWS = [
  { syntax: "# Заголовок", sample: "Заголовок", style: "h1" },
  { syntax: "## Підзаголовок", sample: "Підзаголовок", style: "h2" },
  { syntax: "**жирний**", sample: "жирний", style: "bold" },
  { syntax: "*курсив*", sample: "курсив", style: "italic" },
  { syntax: "***жирний курсив***", sample: "жирний курсив", style: "bold-italic" },
  { syntax: "~~закреслений~~", sample: "закреслений", style: "strike" },
  { syntax: "- пункт", sample: "• пункт", style: "plain" },
  { syntax: "1. пункт", sample: "1. пункт", style: "plain" },
  { syntax: "> цитата", sample: "цитата", style: "quote" },
  { syntax: "`код`", sample: "код", style: "code" },
  { syntax: "```", sample: "блок коду", style: "code" },
  { syntax: "[текст](посилання)", sample: "текст", style: "link" },
  { syntax: "---", sample: "розділювач", style: "rule" },
];

export default function MarkdownHelp({ onClose }) {
  const panelRef = useRef(null);

  // Dismiss on any tap outside, deferred by a tick so the click that opened
  // the panel does not immediately close it again. Same pattern the ⋮ context
  // menu uses — a backdrop would be heavier than the panel itself.
  useEffect(() => {
    const onDocument = (event) => {
      if (panelRef.current && !panelRef.current.contains(event.target)) onClose();
    };
    const timer = setTimeout(() => document.addEventListener("click", onDocument), 0);

    return () => {
      clearTimeout(timer);
      document.removeEventListener("click", onDocument);
    };
  }, [onClose]);

  return (
    <div className="md-help" ref={panelRef} role="dialog" aria-label="Markdown">
      <div className="md-help-title">Markdown</div>
      {ROWS.map((row) => (
        <div className="md-help-row" key={row.syntax}>
          <code className="md-help-syntax">{row.syntax}</code>
          <span className={"md-help-sample s-" + row.style}>{row.sample}</span>
        </div>
      ))}
    </div>
  );
}
