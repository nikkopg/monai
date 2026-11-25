"use client";
// 261122-stm: the live answer's stage (loading / thinking / tool / answering),
// animated, with each stage's elapsed time and a line of finished stages.
import { useEffect, useState } from "react";

import { tokens } from "../styles";
import { formatElapsed, toolLabel } from "./labels";

export type Stage = "loading" | "thinking" | "tool" | "answering";
export type Phase = { stage: Stage; tool?: string; start: number; end?: number };

const PAST: Record<Stage, string> = {
  loading: "loaded",
  thinking: "thought",
  tool: "checked",
  answering: "answered",
};

/** Close the open phase and start `stage`, unless it is already the open one. */
export function enterPhase(phases: Phase[] | undefined, stage: Stage, now: number, tool?: string): Phase[] {
  const list = phases ?? [];
  const last = list[list.length - 1];
  if (last && last.end === undefined && last.stage === stage && last.tool === tool) return list;
  const closed = last && last.end === undefined ? [...list.slice(0, -1), { ...last, end: now }] : list;
  return [...closed, { stage, tool, start: now }];
}

/** Close the open phase (the run ended). */
export function closePhases(phases: Phase[] | undefined, now: number): Phase[] | undefined {
  const last = phases?.[phases.length - 1];
  if (!phases || !last || last.end !== undefined) return phases;
  return [...phases.slice(0, -1), { ...last, end: now }];
}

function liveText(p: Phase): string {
  if (p.stage === "loading") return "loading the model…";
  if (p.stage === "tool") return `checking ${p.tool ? toolLabel(p.tool) : "a tool"}…`;
  return p.stage === "answering" ? "answering…" : "thinking…";
}

/** Finished stages: "loaded 1m 16s · thought 46s · checked 1s". */
export function stageTrail(phases: Phase[]): string {
  return phases
    .filter((p) => p.end !== undefined && p.stage !== "answering")
    .map((p) => `${PAST[p.stage]} ${formatElapsed(p.end! - p.start)}`)
    .join(" · ");
}

const muted = { fontSize: "var(--fs-xs, 12px)", color: tokens.color.muted3 } as const;

/** Running: glyph, waving label and timer. Done: "answered in …". */
export default function StageLabel({ phases, running }: { phases: Phase[]; running: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  const cur = phases[phases.length - 1];
  if (!running) {
    const end = cur?.end ?? now;
    return (
      <span style={muted}>· answered in {formatElapsed(end - phases[0].start)}</span>
    );
  }
  const text = liveText(cur);
  return (
    <span style={{ ...muted, display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span aria-hidden="true">·</span>
      {cur.stage === "loading" ? (
        <span className="stage-bar" aria-hidden="true"><i /></span>
      ) : cur.stage !== "answering" ? (
        <span className="stage-dots" aria-hidden="true"><i /><i /><i /></span>
      ) : null}
      <span data-testid="stage-label">
        {Array.from(text).map((ch, i) => (
          <span key={i} className="stage-ch" style={{ animationDelay: `${(i * 0.06).toFixed(2)}s` }}>
            {ch === " " ? " " : ch}
          </span>
        ))}
      </span>
      <span style={{ fontVariantNumeric: "tabular-nums" }}>{formatElapsed(now - cur.start)}</span>
    </span>
  );
}
