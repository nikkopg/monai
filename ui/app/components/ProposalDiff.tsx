// ---------------------------------------------------------------------------
// ProposalDiff — the before -> after diff the chat ProposalCard has rendered
// since v1.1, extracted unchanged so chat and the Inbox share it.
// `dimColor` defaults to the chat colour so chat output is identical; the Inbox
// passes muted3 because the UI-SPEC bans the lighter tone for new text.
// Primitive-valued output is unchanged; object values render as JSON text, and
// an unknown row shape or an empty before/after object falls back to the row's
// own key: value lines, so a row never renders an empty body. Callers strip
// their own read annotations first (the Inbox drops duplicates and skip).
// ---------------------------------------------------------------------------

import { tokens } from "../styles";

export type DiffRow = {
  id?: number;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  old_name?: string;
  new_name?: string;
  from_name?: string;
  into_name?: string;
  affected_count?: number;
};

// null stays "null" (as String(null)); objects/arrays render as JSON, never "[object Object]".
function show(v: unknown): string {
  return v !== null && typeof v === "object" ? JSON.stringify(v) : String(v);
}

export function ProposalDiff({
  rows,
  dimColor = tokens.color.muted2,
}: {
  rows: DiffRow[];
  dimColor?: string;
}) {
  const del = { color: tokens.color.terracotta };
  const add = { color: tokens.color.green };
  const dim = { color: dimColor };
  const rowBorder = (i: number) =>
    i > 0 ? `1px solid ${tokens.color.borderInner}` : undefined;

  if (!rows || rows.length === 0) return null;

  const batchSummary =
    rows.length > 1 ? (
      <div style={{ fontSize: 12, ...dim, marginBottom: 10 }}>
        {rows.length} rows affected
      </div>
    ) : null;

  const displayRows = rows.slice(0, 5);
  const remainder = rows.length - displayRows.length;

  return (
    <div style={{ fontSize: 14 }}>
      {batchSummary}
      {displayRows.map((row, i) => {
        if (row.old_name !== undefined) {
          return (
            <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
              <span style={{ ...del, textDecoration: "line-through" }}>
                {row.old_name}
              </span>
              {" → "}
              <span style={{ ...add, fontWeight: 600 }}>{row.new_name}</span>
              {row.affected_count !== undefined && (
                <span style={dim}> ({row.affected_count} tx)</span>
              )}
            </div>
          );
        }
        if (row.from_name !== undefined) {
          return (
            <div key={i} style={{ padding: "6px 0" }}>
              merge <span style={del}>{row.from_name}</span>
              {" → "}
              <span style={{ ...add, fontWeight: 600 }}>{row.into_name}</span>
            </div>
          );
        }
        if (!row.before && row.after && Object.keys(row.after).length > 0) {
          return (
            <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
              {Object.entries(row.after).map(([k, v]) => (
                <div key={k}>
                  <span style={dim}>{k}: </span>
                  <span style={add}>{show(v ?? "—")}</span>
                </div>
              ))}
            </div>
          );
        }
        if (row.before && !row.after && Object.keys(row.before).length > 0) {
          return (
            <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
              {Object.entries(row.before).map(([k, v]) => (
                <div key={k}>
                  <span style={dim}>{k}: </span>
                  <span style={del}>{show(v ?? "—")}</span>
                </div>
              ))}
            </div>
          );
        }
        if (row.before && row.after) {
          const changedKeys = Object.keys(row.after).filter(
            (k) => show(row.after![k]) !== show(row.before![k])
          );
          if (changedKeys.length === 0) {
            return (
              <div key={i} style={{ ...dim, fontSize: 12 }}>
                (no field changes detected)
              </div>
            );
          }
          return (
            <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
              {changedKeys.map((k) => (
                <div key={k}>
                  <span style={dim}>{k}: </span>
                  <span style={del}>{show(row.before![k] ?? "—")}</span>
                  {" → "}
                  <span style={add}>{show(row.after![k] ?? "—")}</span>
                </div>
              ))}
            </div>
          );
        }
        // Unknown shape: show the row's own fields.
        const fields = Object.entries(row);
        if (fields.length === 0) {
          return (
            <div key={i} style={{ ...dim, fontSize: 12 }}>
              (no row details)
            </div>
          );
        }
        return (
          <div key={i} style={{ padding: "6px 0", borderTop: rowBorder(i) }}>
            {fields.map(([k, v]) => (
              <div key={k}>
                <span style={dim}>{k}: </span>
                <span>{show(v ?? "—")}</span>
              </div>
            ))}
          </div>
        );
      })}
      {remainder > 0 && (
        <div style={{ ...dim, fontSize: 12, marginTop: 6 }}>
          + {remainder} more row{remainder > 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}

export default ProposalDiff;
