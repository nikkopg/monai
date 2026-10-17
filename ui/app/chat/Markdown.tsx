/** @jsxImportSource react */
// ---------------------------------------------------------------------------
// Safe markdown renderer for assistant answers (STRM-03, D-10 / D-10a).
//
// Model text is untrusted. Rules, all enforced here and by the CSP in
// next.config.js (second, independent layer):
//   - skipHtml and no raw-HTML plugin: HTML in the answer never becomes DOM.
//   - images never render: the alt text only, so no request can be made.
//   - urlTransform allow-list: http, https, mailto and relative URLs only; a
//     blanked href renders a <span>, not <a href="">.
// The model's text (IDR figures included) is never reformatted client-side.
//
// The pragma above keeps a node-only Playwright render test working
// (Playwright otherwise compiles .tsx with its own JSX runtime).
// ---------------------------------------------------------------------------

import { Children, cloneElement, isValidElement, memo } from "react";
import type { ComponentPropsWithoutRef, CSSProperties, ReactElement, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { tokens } from "../styles";

const { color: c, radius } = tokens;
const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

// Relative URLs pass; any URL with a scheme must be http(s) or mailto.
const SAFE_SCHEME = /^(https?:|mailto:)/i;
export function safeUrl(url: string): string {
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url) && !SAFE_SCHEME.test(url) ? "" : url;
}

const NUMERIC = /^[\s(+\-]*(?:Rp\.?\s*|IDR\s*)?[\d.,]+\s*%?\)?\s*$/i;

// Minimal hast shapes: just what the numeric-column pass touches.
type HastNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

const textOf = (n: HastNode): string =>
  n.type === "text" ? (n.value ?? "") : (n.children ?? []).map(textOf).join("");

const tagsIn = (n: HastNode, tag: string): HastNode[] =>
  (n.children ?? []).flatMap((ch) =>
    ch.type === "element" && ch.tagName === tag ? [ch] : tagsIn(ch, tag),
  );

// For each table: a column (other than the first) whose body cells are all
// numeric gets align=right on its th and td cells, unless GFM set an explicit
// alignment (explicit always wins). The hast-to-JSX step turns align into
// style.textAlign, which the th/td overrides below merge.
function rehypeNumericColumns() {
  const visit = (n: HastNode) => {
    if (n.type === "element" && n.tagName === "table") {
      const rows = tagsIn(n, "tr").map((tr) =>
        (tr.children ?? []).filter(
          (x) => x.type === "element" && (x.tagName === "td" || x.tagName === "th"),
        ),
      );
      const body = rows.filter((cells) => cells.some((x) => x.tagName === "td"));
      const cols = Math.max(0, ...rows.map((r) => r.length));
      for (let i = 1; i < cols; i++) {
        const numeric =
          body.length > 0 && body.every((r) => r[i] && NUMERIC.test(textOf(r[i])));
        if (!numeric) continue;
        for (const r of rows) {
          const cell = r[i];
          if (cell && !cell.properties?.align) {
            cell.properties = { ...cell.properties, align: "right" };
          }
        }
      }
    }
    (n.children ?? []).forEach(visit);
  };
  return visit;
}

const heading = (
  size: number,
  margin: string,
  col: string,
  extra?: CSSProperties,
): CSSProperties => ({
  fontSize: size,
  fontWeight: 600,
  lineHeight: 1.4,
  margin,
  color: col,
  ...extra,
});

function makeComponents(dimmed: boolean): Components {
  const ink = dimmed ? c.muted3 : c.ink;
  const soft = dimmed ? c.muted3 : c.textSoft;
  const cell: CSSProperties = {
    fontSize: 14,
    lineHeight: 1.5,
    padding: "8px 16px",
    color: ink,
    fontVariantNumeric: "tabular-nums",
  };
  return {
    p: ({ node: _n, ...p }) => <p style={{ margin: "0 0 16px" }} {...p} />,
    h1: ({ node: _n, ...p }) => (
      <h1
        style={heading(16, "24px 0 8px", ink, {
          paddingBottom: 4,
          borderBottom: `1px solid ${c.border}`,
        })}
        {...p}
      />
    ),
    h2: ({ node: _n, ...p }) => <h2 style={heading(16, "24px 0 8px", ink)} {...p} />,
    h3: ({ node: _n, ...p }) => <h3 style={heading(16, "16px 0 8px", soft)} {...p} />,
    h4: ({ node: _n, ...p }) => <h4 style={heading(14, "16px 0 4px", ink)} {...p} />,
    h5: ({ node: _n, ...p }) => <h5 style={heading(14, "16px 0 4px", ink)} {...p} />,
    h6: ({ node: _n, ...p }) => <h6 style={heading(14, "16px 0 4px", ink)} {...p} />,
    strong: ({ node: _n, ...p }) => <strong style={{ fontWeight: 600 }} {...p} />,
    ul: ({ node: _n, ...p }) => <ul style={{ paddingLeft: 24, margin: "0 0 16px" }} {...p} />,
    ol: ({ node: _n, ...p }) => (
      <ol
        style={{ paddingLeft: 24, margin: "0 0 16px", fontVariantNumeric: "tabular-nums" }}
        {...p}
      />
    ),
    li: ({ node: _n, ...p }) => <li style={{ margin: "4px 0" }} {...p} />,
    blockquote: ({ node: _n, ...p }) => (
      <blockquote
        style={{
          margin: "0 0 16px",
          paddingLeft: 16,
          borderLeft: `3px solid ${c.border2}`,
          color: c.muted3,
        }}
        {...p}
      />
    ),
    hr: () => <hr style={{ border: 0, borderTop: `1px solid ${c.border}`, margin: "24px 0" }} />,
    // Inline code gets the chip; a fenced block's inner code gets `block`
    // from the pre override below and stays chip-free.
    code: ({ node: _n, block, ...p }: ComponentPropsWithoutRef<"code"> & { node?: unknown; block?: boolean }) => (
      <code
        style={{
          fontFamily: MONO,
          fontSize: 14,
          color: ink,
          ...(block ? null : { background: c.tintNeutral, padding: "0 4px", borderRadius: 4 }),
        }}
        {...p}
      />
    ),
    pre: ({ node: _n, children }) => (
      <pre
        tabIndex={0}
        aria-label="Code"
        style={{
          background: c.inputBg,
          border: `1px solid ${c.border2}`,
          borderRadius: radius.sm,
          padding: "12px 16px",
          fontFamily: MONO,
          fontSize: 14,
          lineHeight: 1.5,
          overflowX: "auto",
          margin: "0 0 16px",
        }}
      >
        {Children.map(children, (ch: ReactNode) =>
          isValidElement(ch) ? cloneElement(ch as ReactElement<{ block?: boolean }>, { block: true }) : ch,
        )}
      </pre>
    ),
    a: ({ node: _n, href, children }) => {
      // D-10a: a blanked href is plain text, never <a href="">.
      if (!href) return <span>{children}</span>;
      const external = /^https?:/i.test(href);
      const link: CSSProperties = {
        color: ink,
        textDecoration: "underline",
        textUnderlineOffset: 4,
      };
      return external ? (
        <a href={href} target="_blank" rel="noopener noreferrer" style={link}>
          {children}
          <span aria-hidden="true" style={{ fontSize: 12 }}>
            {" ↗"}
          </span>
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      ) : (
        <a href={href} style={link}>
          {children}
        </a>
      );
    },
    // Never an <img>: no element means no request (D-10a, T-37-18).
    img: ({ alt }) => (alt ? <span>{alt}</span> : null),
    table: ({ node: _n, children }) => (
      <div
        role="region"
        aria-label="Table"
        tabIndex={0}
        style={{
          overflowX: "auto",
          maxWidth: "100%",
          border: `1px solid ${c.border2}`,
          borderRadius: radius.sm,
          background: c.card,
          margin: "0 0 16px",
        }}
      >
        <table
          style={{
            borderCollapse: "collapse",
            width: "max-content",
            minWidth: "100%",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {children}
        </table>
      </div>
    ),
    th: ({ node: _n, style, children }) => (
      <th
        style={{
          ...cell,
          fontWeight: 600,
          background: c.sidebar,
          whiteSpace: "nowrap",
          borderBottom: `1px solid ${c.border2}`,
          textAlign: "left",
          ...style,
        }}
      >
        {children}
      </th>
    ),
    td: ({ node: _n, style, children }) => (
      <td
        style={{
          ...cell,
          fontWeight: 400,
          borderTop: `1px solid ${c.borderInner}`,
          textAlign: "left",
          ...style,
        }}
      >
        {children}
      </td>
    ),
  };
}

// Stable component maps (one per colour mode) so a re-render never remounts.
const COMPONENTS = { normal: makeComponents(false), dimmed: makeComponents(true) };

function Markdown({ children, dimmed = false }: { children: string; dimmed?: boolean }) {
  return (
    <div
      className="md"
      style={{ color: dimmed ? c.muted3 : c.ink, fontSize: 16, lineHeight: 1.6, fontWeight: 400 }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeNumericColumns]}
        skipHtml
        urlTransform={safeUrl}
        components={dimmed ? COMPONENTS.dimmed : COMPONENTS.normal}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export default memo(Markdown);
