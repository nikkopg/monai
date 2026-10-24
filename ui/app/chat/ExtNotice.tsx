"use client";

import Link from "next/link";

import { tokens } from "../styles";
import { noticeSentence, type ExtNotice } from "./extLabels";

// ---------------------------------------------------------------------------
// Turn notices and the "Used external tools" footer (41-UI-SPEC C2/C3, D-25).
// Sentences come from the event's code and server (extLabels.noticeSentence);
// everything server-supplied is a React text node, and the only link is the
// fixed /settings#external-mcp.
// ---------------------------------------------------------------------------

export function ExtNotices({ notices }: { notices: ExtNotice[] }) {
  return (
    <>
      {notices.map((n, i) => {
        const s = noticeSentence(n);
        return (
          <p
            key={`${n.code}-${i}`}
            data-testid="ext-notice"
            data-code={n.code}
            style={{
              margin: "0 0 8px",
              paddingLeft: 12,
              borderLeft: `3px solid ${tokens.color.border2}`,
              fontSize: 14,
              lineHeight: 1.5,
              color: tokens.color.muted3,
              overflowWrap: "anywhere",
            }}
          >
            {s.text}
            {s.linkText && (
              <Link
                href="/settings#external-mcp"
                data-testid="ext-notice-link"
                className="coarse-tap"
                style={{
                  color: tokens.color.ink,
                  textDecoration: "underline",
                  textUnderlineOffset: 4,
                  display: "inline-block",
                  minHeight: 36,
                  lineHeight: "36px",
                }}
              >
                {s.linkText}
              </Link>
            )}
            {s.tail}
          </p>
        );
      })}
    </>
  );
}

export function ExtFooter({ slugs }: { slugs: string[] }) {
  if (slugs.length === 0) return null;
  return (
    <p
      data-testid="ext-footer"
      style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.5, color: tokens.color.muted3, overflowWrap: "anywhere" }}
    >
      <span style={{ fontWeight: 600, color: tokens.color.ink }}>Used external tools:</span> {slugs.join(", ")}. External
      results are unverified.
    </p>
  );
}
