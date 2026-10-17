"use client";

import { useEffect, useId, useState } from "react";

import { tokens } from "../styles";
import { argRows, formatDuration, formatElapsed, toolLabel } from "./labels";
import type { StepEntry, TimelineEntry } from "./useChatStream";

// Tool steps for one assistant message (STRM-02, D-06..D-09). One toggle: a live
// line while the turn runs, "Used N tools" afterwards. The panel lists steps and
// working notes in order. Args and resolved dates only: never JSON, never the
// result (D-08). Narration is rendered as a plain text node, never markdown.

const toggleBase: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 4,
  minHeight: 36,
  background: "transparent",
  border: "none",
  fontFamily: "inherit",
  fontSize: 14,
  cursor: "pointer",
  textAlign: "left",
};

const glyph = (c: string, color?: string) => (
  <span aria-hidden="true" style={color ? { color } : undefined}>
    {c}
  </span>
);

export default function ToolSteps({
  timeline,
  running,
  open,
  onToggle,
}: {
  timeline: TimelineEntry[];
  running: boolean;
  open: Record<string, boolean>;
  onToggle: (key: string) => void;
}) {
  const uid = useId();
  const [, setTick] = useState(0);
  const steps = timeline.filter((e): e is StepEntry => e.kind === "step");
  // A step still "running" in a message that is no longer running (stopped,
  // errored) is shown as finished, without a duration.
  const live = (s: StepEntry) => running && s.status === "running";
  const runningSteps = steps.filter(live);
  const ticking = runningSteps.length > 0;

  useEffect(() => {
    if (!ticking) return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [ticking]);

  if (timeline.length === 0) return null;

  const groupOpen = !!open.group;
  const groupId = `${uid}-group`;
  let label: React.ReactNode;
  if (running && steps.length > 0) {
    const cur = runningSteps[0];
    const shown = cur ?? [...steps].reverse().find((s) => s.status === "done") ?? steps[steps.length - 1];
    const doneCount = steps.filter((s) => !live(s)).length;
    const time = cur
      ? formatElapsed(Date.now() - (cur.startedAt ?? Date.now()))
      : typeof shown.ms === "number"
      ? formatDuration(shown.ms)
      : null;
    label = (
      <>
        {glyph("›", tokens.color.green)}
        <span style={{ color: tokens.color.ink }}>{toolLabel(shown.tool)}</span>
        {time && (
          <span style={{ color: tokens.color.muted3, fontVariantNumeric: "tabular-nums" }}>
            {" "}
            · {time}
          </span>
        )}
        {cur && doneCount > 0 && (
          <span style={{ color: tokens.color.muted3 }}> · {doneCount} done</span>
        )}
        {runningSteps.length > 1 && (
          <span style={{ color: tokens.color.muted3 }}> · +{runningSteps.length - 1} running</span>
        )}
        {glyph(groupOpen ? "▴" : "▾", tokens.color.muted3)}
      </>
    );
  } else {
    const text =
      steps.length > 0 ? `Used ${steps.length} ${steps.length === 1 ? "tool" : "tools"}` : "Working note";
    label = (
      <>
        {text}
        {glyph(groupOpen ? "▴" : "▾")}
      </>
    );
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <button
        type="button"
        data-testid="steps-toggle"
        className="coarse-tap steps-toggle"
        aria-expanded={groupOpen}
        aria-controls={groupId}
        onClick={() => onToggle("group")}
        style={{ ...toggleBase, padding: "8px 0", color: tokens.color.muted3 }}
      >
        {label}
      </button>
      <div
        id={groupId}
        hidden={!groupOpen}
        style={
          groupOpen
            ? {
                display: "flex",
                flexDirection: "column",
                gap: 4,
                marginLeft: 4,
                paddingLeft: 16,
                borderLeft: `1px solid ${tokens.color.border2}`,
              }
            : undefined
        }
      >
        {timeline.map((e, i) => {
          const key = e.kind === "step" ? `s${i}` : `n${i}`;
          const isOpen = !!open[key];
          const panelId = `${uid}-${key}`;
          if (e.kind === "note") {
            return (
              <div key={key}>
                <button
                  type="button"
                  className="coarse-tap"
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  onClick={() => onToggle(key)}
                  style={{ ...toggleBase, color: tokens.color.muted3 }}
                >
                  Working note {glyph(isOpen ? "▴" : "▾")}
                </button>
                <div
                  id={panelId}
                  hidden={!isOpen}
                  style={
                    isOpen
                      ? {
                          padding: "4px 0 8px 24px",
                          fontSize: 14,
                          lineHeight: 1.5,
                          color: tokens.color.muted3,
                          whiteSpace: "pre-wrap",
                          overflowWrap: "anywhere",
                        }
                      : undefined
                  }
                >
                  {e.text}
                </div>
              </div>
            );
          }
          const rows = argRows(e.args, e.sources);
          return (
            <div key={key}>
              <button
                type="button"
                data-testid="step-toggle"
                className="coarse-tap step-toggle"
                aria-expanded={isOpen}
                aria-controls={panelId}
                onClick={() => onToggle(key)}
                style={{ ...toggleBase, width: "100%", color: tokens.color.ink }}
              >
                {glyph("›", tokens.color.green)}
                <span className="step-label" style={{ color: tokens.color.ink }}>
                  {toolLabel(e.tool)}
                </span>
                {typeof e.ms === "number" && !live(e) && (
                  <span style={{ color: tokens.color.muted3, fontVariantNumeric: "tabular-nums" }}>
                    {" "}
                    · {formatDuration(e.ms)}
                  </span>
                )}
                {e.failed && <span style={{ color: tokens.color.muted3 }}> · no result</span>}
                {glyph(isOpen ? "▴" : "▾", tokens.color.muted3)}
              </button>
              <dl
                id={panelId}
                hidden={!isOpen}
                style={
                  isOpen
                    ? {
                        display: "grid",
                        gridTemplateColumns: "96px 1fr",
                        columnGap: 16,
                        rowGap: 4,
                        margin: 0,
                        padding: "4px 0 8px 24px",
                      }
                    : undefined
                }
              >
                {rows.map((r, j) => (
                  <div key={j} style={{ display: "contents" }}>
                    <dt style={{ fontSize: 12, color: tokens.color.muted3 }}>{r.label}</dt>
                    <dd
                      style={{
                        margin: 0,
                        fontSize: 14,
                        lineHeight: 1.5,
                        overflowWrap: "anywhere",
                        color: r.label ? tokens.color.ink : tokens.color.muted3,
                      }}
                    >
                      {r.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          );
        })}
      </div>
    </div>
  );
}
