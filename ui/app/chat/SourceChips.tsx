"use client";

import Link from "next/link";

import { tokens } from "../styles";
import type { Source } from "./labels";

// SOURCES row under a completed answer (D-12, D-13, D-14). A linked chip opens
// Records filtered to the exact rows behind the number; a plain chip names the
// source but is not clickable.

/** Records URL for a linked chip. Fixed path, fields encoded by URLSearchParams. */
export function chipHref(s: Source): string {
  const p = new URLSearchParams();
  if (s.date_from) p.set("date_from", s.date_from);
  if (s.date_to) p.set("date_to", s.date_to);
  if (s.category) p.set("category", s.category);
  if (s.type) p.set("type", s.type);
  if (s.account_id != null) p.set("account_id", String(s.account_id));
  p.set("cashflow", "1");
  return `/records?${p.toString()}`;
}

/** First occurrence wins, step order kept. */
export function dedupeSources(list: Source[]): Source[] {
  const seen = new Set<string>();
  return list.filter((s) => {
    const key = JSON.stringify([s.label, s.period_label, s.category, s.date_from, s.date_to, s.type]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

const chipBase: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  minHeight: 32,
  maxWidth: "100%",
  padding: "0 12px",
  fontSize: 14,
  color: tokens.color.ink,
  borderRadius: tokens.radius.pill,
  textDecoration: "none",
};

export default function SourceChips({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: ".12em",
          color: tokens.color.muted3,
          marginBottom: 8,
        }}
      >
        Sources
      </div>
      <ul
        aria-label="Sources"
        style={{ display: "flex", flexWrap: "wrap", gap: 8, listStyle: "none", padding: 0, margin: 0 }}
      >
        {sources.map((s, i) => {
          const parts = [s.label, s.category, s.period_label].filter(Boolean) as string[];
          const text = parts.join(" · ");
          const inner = (
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {text}
            </span>
          );
          return (
            <li key={i} style={{ display: "flex", maxWidth: "100%" }}>
              {s.linked ? (
                <Link
                  href={chipHref(s)}
                  data-testid="source-chip"
                  className="source-chip coarse-tap"
                  title={text}
                  aria-label={`Open in Records: ${parts.join(", ")}`}
                  style={{
                    ...chipBase,
                    background: tokens.color.card,
                    border: `1px solid ${tokens.color.border2}`,
                  }}
                >
                  {inner}
                  <span aria-hidden="true">{"›"}</span>
                </Link>
              ) : (
                <span
                  data-testid="source-chip-plain"
                  title={text}
                  style={{
                    ...chipBase,
                    background: tokens.color.tintNeutral,
                    border: `1px dashed ${tokens.color.border2}`,
                  }}
                >
                  {inner}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
