"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, card, btn, btnGhost } from "../styles";

// ---------------------------------------------------------------------------
// Settings "Skills" card (phase 40, plan 02; contract: 40-UI-SPEC.md).
// Lists skill packs with a status in words, opens an inline panel that shows
// the raw text of every file the owner is approving, and puts Enable after it.
// Enable echoes the hash of the detail on screen; a 409 swaps in the new text.
// Every skill-supplied string is a React text node: no raw HTML, no markdown.
// ---------------------------------------------------------------------------

type SkillRow = {
  name: string;
  description: string;
  valid: boolean;
  reason: string | null;
  enabled: boolean;
  changed: boolean;
  declares_allowed_tools: boolean;
};
type SkillFile = { path: string; text?: string; reason?: string };
type SkillDetail = {
  name: string;
  description: string;
  content: string;
  files: SkillFile[];
  hash: string;
};

const STALE =
  "This skill changed after you opened it. The text below is the new version. Read it, then enable it again.";

const body14: React.CSSProperties = { fontSize: 14, lineHeight: 1.5 };
const small: React.CSSProperties = { ...body14, color: tokens.color.muted3 };
const errText: React.CSSProperties = { ...body14, color: tokens.color.terracottaText };
const blockLabel: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  lineHeight: 1.5,
  color: tokens.color.muted3,
  overflowWrap: "anywhere",
};
const rowBtn: React.CSSProperties = {
  ...btnGhost,
  padding: "8px 16px",
  minHeight: 36,
  lineHeight: 1.5,
};
const pre: React.CSSProperties = {
  ...body14,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  color: tokens.color.ink,
  background: tokens.color.inputBg,
  border: `1px solid ${tokens.color.border2}`,
  borderRadius: tokens.radius.sm,
  padding: "8px 16px",
  margin: 0,
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  maxHeight: 320,
  overflow: "auto",
};
const chipBase: React.CSSProperties = {
  display: "inline-block",
  fontSize: 12,
  fontWeight: 600,
  lineHeight: 1.5,
  borderRadius: tokens.radius.pill,
  padding: "4px 8px",
  color: tokens.color.ink,
};

/** `detail` string from an error body, else `HTTP {status}` (putSettings pattern). */
async function errDetail(r: Response): Promise<string> {
  try {
    const b = await r.json();
    if (typeof b?.detail === "string") return b.detail;
  } catch {
    // keep the status-based detail
  }
  return `HTTP ${r.status}`;
}

const url = (name: string) => `/api/skills/${encodeURIComponent(name)}`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function chip(s: SkillRow): { text: string; style: React.CSSProperties } {
  if (!s.valid)
    return { text: "Invalid", style: { background: tokens.color.tintWarm, border: `1px solid ${tokens.color.border2}` } };
  if (!s.enabled) return { text: "Off", style: { background: tokens.color.tintNeutral, color: tokens.color.muted3 } };
  if (s.changed)
    return {
      text: "Changed since enabled",
      style: { background: tokens.color.tintWarm, border: `1px solid ${tokens.color.border2}` },
    };
  return { text: "On", style: { background: tokens.color.tintGreen } };
}

export default function SkillsCard() {
  const [rows, setRows] = useState<SkillRow[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [rowErr, setRowErr] = useState<Record<string, string>>({});
  const [disabling, setDisabling] = useState<string | null>(null);

  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [refetching, setRefetching] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [panelError, setPanelError] = useState("");

  const openRef = useRef<string | null>(null);
  const viewBtns = useRef(new Map<string, HTMLButtonElement>());
  const headingRef = useRef<HTMLHeadingElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const enableRef = useRef<HTMLButtonElement>(null);
  const pendingFocus = useRef<string | null>(null);
  const focusHeading = useRef(false);
  const focusEnable = useRef(false);

  async function loadList(): Promise<void> {
    try {
      const r = await fetch("/api/skills");
      if (!r.ok) {
        setListError(await errDetail(r));
        return;
      }
      setRows(await r.json());
      setListError(null);
    } catch {
      setListError("Network error");
    }
  }

  useEffect(() => {
    void loadList();
  }, []);

  // Hand focus to a row's View button once the refreshed list has rendered.
  useEffect(() => {
    if (pendingFocus.current) {
      viewBtns.current.get(pendingFocus.current)?.focus();
      pendingFocus.current = null;
    }
  }, [rows]);

  // Focus the heading when a panel's text first lands; scroll every block to the top on new text.
  useEffect(() => {
    if (!detail) return;
    if (focusHeading.current) {
      headingRef.current?.focus();
      focusHeading.current = false;
    }
    panelRef.current?.querySelectorAll("pre").forEach((p) => (p.scrollTop = 0));
  }, [detail]);

  // Keep focus on Enable after an outcome that leaves the panel open.
  useEffect(() => {
    if (focusEnable.current && !enabling && !refetching) {
      enableRef.current?.focus();
      focusEnable.current = false;
    }
  });

  function closePanel(name: string, refocus = true) {
    openRef.current = null;
    setOpen(null);
    setDetail(null);
    setPanelError("");
    if (refocus) viewBtns.current.get(name)?.focus();
  }

  /** Fetch the detail; false when it failed. Ignores answers for a panel no longer open. */
  async function loadDetail(name: string): Promise<boolean> {
    try {
      const r = await fetch(url(name));
      if (openRef.current !== name) return false;
      if (!r.ok) {
        if (r.status === 404) void loadList();
        setDetail(null);
        setPanelError(`Couldn't open ${name}: ${await errDetail(r)}.`);
        return false;
      }
      setDetail(await r.json());
      return true;
    } catch {
      if (openRef.current !== name) return false;
      setDetail(null);
      setPanelError(`Couldn't open ${name}: Network error.`);
      return false;
    }
  }

  async function openPanel(name: string) {
    if (openRef.current === name) return closePanel(name);
    openRef.current = name;
    setOpen(name);
    setDetail(null);
    setPanelError("");
    setLoadingDetail(true);
    focusHeading.current = true;
    await loadDetail(name);
    if (openRef.current === name) setLoadingDetail(false);
  }

  async function enable(name: string) {
    if (!detail) return;
    setEnabling(true);
    setPanelError("");
    let r: Response | null = null;
    let detailMsg = "Network error";
    try {
      r = await fetch(url(name), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: true, hash: detail.hash }),
      });
      if (!r.ok) detailMsg = await errDetail(r);
    } catch {
      r = null;
    }
    if (r?.ok) {
      closePanel(name, false);
      pendingFocus.current = name;
      setStatus(`${name} is now on.`);
      await loadList();
    } else if (r?.status === 404) {
      closePanel(name, false);
      setStatus(`${name} is no longer in the skills folder.`);
      await loadList();
    } else if (r?.status === 409) {
      setRefetching(true);
      setPanelError(STALE);
      focusEnable.current = true;
      if (!(await loadDetail(name))) focusEnable.current = false;
      setRefetching(false);
    } else {
      setPanelError(`Couldn't enable ${name}: ${detailMsg}. It stays off.`);
      focusEnable.current = true;
    }
    setEnabling(false);
  }

  async function disable(name: string) {
    setDisabling(name);
    setRowErr((e) => ({ ...e, [name]: "" }));
    let fail = "";
    try {
      const r = await fetch(url(name), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: false }),
      });
      if (!r.ok) fail = await errDetail(r);
    } catch {
      fail = "Network error";
    }
    if (fail) {
      setRowErr((er) => ({ ...er, [name]: `Couldn't disable ${name}: ${fail}. Nothing was changed.` }));
    } else {
      if (openRef.current === name) closePanel(name, false);
      pendingFocus.current = name;
      setStatus(`${name} is now off.`);
      await loadList();
    }
    setDisabling(null);
  }

  function renderPanel(s: SkillRow) {
    const name = s.name;
    const reread = (path: string) => `${path} of ${name}`;
    const raw = (path: string, text: string, testid?: string) => (
      <pre style={pre} tabIndex={0} role="region" aria-label={reread(path)} data-testid={testid}>
        {text}
      </pre>
    );
    const label = s.changed ? "Re-enable skill" : "Enable skill";
    return (
      <div
        id={`skill-panel-${name}`}
        ref={panelRef}
        role="group"
        aria-labelledby={`skill-panel-heading-${name}`}
        aria-busy={loadingDetail}
        data-testid="skill-panel"
        onKeyDown={(e) => {
          if (e.key === "Escape") closePanel(name);
        }}
        style={{
          background: tokens.color.card,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: tokens.radius.md,
          padding: 16,
          marginTop: 16,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <h3
          id={`skill-panel-heading-${name}`}
          ref={headingRef}
          tabIndex={-1}
          style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.3, margin: 0, color: tokens.color.ink, overflowWrap: "anywhere" }}
        >
          {name}
        </h3>
        {loadingDetail && <div style={small}>Loading…</div>}
        {detail && (
          <>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={blockLabel}>Listed to the agent as</div>
              <div
                style={{
                  ...body14,
                  color: tokens.color.ink,
                  background: tokens.color.inputBg,
                  border: `1px solid ${tokens.color.border2}`,
                  borderRadius: tokens.radius.sm,
                  padding: 16,
                  overflowWrap: "anywhere",
                }}
              >
                {`${detail.name}: ${detail.description}`}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={blockLabel}>SKILL.md</div>
              {raw("SKILL.md", detail.content, "skill-content")}
            </div>
            {detail.files
              .filter((f) => f.path !== "SKILL.md")
              .map((f) => (
                <div
                  key={f.path}
                  data-testid="skill-file"
                  data-path={f.path}
                  style={{ display: "flex", flexDirection: "column", gap: 8 }}
                >
                  <div style={blockLabel}>{f.path}</div>
                  {typeof f.text === "string" ? (
                    raw(f.path, f.text)
                  ) : (
                    <div style={small}>{`Not shown: ${f.reason}. The agent can't read it either.`}</div>
                  )}
                </div>
              ))}
            <div style={small}>
              Shown exactly as the agent will receive it, with hidden control characters removed. If any of these files
              changes, the skill switches off until you enable it again.
            </div>
          </>
        )}
        <div role="alert" data-testid="skill-error" style={errText}>
          {panelError}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {detail && (
            <button
              type="button"
              ref={enableRef}
              style={{ ...btn, minHeight: 36, lineHeight: 1.5 }}
              className="coarse-tap"
              data-testid="skill-enable"
              aria-label={`${label} ${name}`}
              disabled={enabling || refetching}
              onClick={() => void enable(name)}
            >
              {enabling ? "Enabling…" : label}
            </button>
          )}
          <button
            type="button"
            style={rowBtn}
            className="coarse-tap"
            data-testid="skill-close"
            onClick={() => closePanel(name)}
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  function renderRow(s: SkillRow, i: number) {
    const c = chip(s);
    const changedRow = s.valid && s.enabled && s.changed;
    const opener = changedRow ? "Review" : "View";
    return (
      <li
        key={s.name}
        data-testid="skill-row"
        data-skill={s.name}
        style={{
          listStyle: "none",
          borderTop: i === 0 ? "none" : `1px solid ${tokens.color.borderInner}`,
          ...(changedRow
            ? { background: tokens.color.tintWarm, padding: 16, borderRadius: tokens.radius.sm }
            : s.valid
              ? { padding: "16px 0" }
              : { padding: "16px 0 16px 16px", borderLeft: `3px solid ${tokens.color.terracotta}` }),
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
          <span style={{ ...body14, fontWeight: 600, color: tokens.color.ink, overflowWrap: "anywhere" }}>{s.name}</span>
          <span data-testid="skill-status" style={{ ...chipBase, ...c.style }}>
            {c.text}
          </span>
          {s.valid && (
            <span style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                ref={(el) => {
                  if (el) viewBtns.current.set(s.name, el);
                  else viewBtns.current.delete(s.name);
                }}
                style={rowBtn}
                className="coarse-tap"
                data-testid="skill-view"
                aria-label={`${opener} ${s.name}`}
                aria-expanded={open === s.name}
                aria-controls={`skill-panel-${s.name}`}
                onClick={() => void openPanel(s.name)}
              >
                {opener}
              </button>
              {s.enabled && (
                <button
                  type="button"
                  style={rowBtn}
                  className="coarse-tap"
                  data-testid="skill-disable"
                  aria-label={`Disable ${s.name}`}
                  disabled={disabling === s.name}
                  onClick={() => void disable(s.name)}
                >
                  {disabling === s.name ? "Disabling…" : "Disable"}
                </button>
              )}
            </span>
          )}
        </div>
        {s.description && <div style={{ ...small, marginTop: 4, overflowWrap: "anywhere" }}>{s.description}</div>}
        {s.valid && s.declares_allowed_tools && (
          <div style={{ ...small, marginTop: 4 }}>This skill declares allowed-tools. It is ignored.</div>
        )}
        {changedRow && (
          <div style={{ ...body14, color: tokens.color.ink, marginTop: 4 }}>
            Changed since you enabled it, so the agent can&apos;t see it. Review it and enable it again, or disable it.
          </div>
        )}
        {!s.valid && (
          <div style={{ ...errText, marginTop: 4, overflowWrap: "anywhere" }}>
            {`${cap(s.reason ?? "invalid")}. Fix the file in the skills folder, then reload this page.`}
          </div>
        )}
        {rowErr[s.name] && (
          <div role="alert" style={{ ...errText, marginTop: 4 }}>
            {rowErr[s.name]}
          </div>
        )}
        {open === s.name && s.valid && renderPanel(s)}
      </li>
    );
  }

  return (
    <div style={card} data-testid="skills-card">
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Skills</div>
      <div style={{ ...small, marginBottom: 16 }}>
        Instruction packs the chat agent can load when your question matches. Each one is off until you enable it.
      </div>
      <div
        data-testid="skills-instructions"
        style={{
          background: tokens.color.tintNeutral,
          border: `1px solid ${tokens.color.border2}`,
          borderRadius: tokens.radius.sm,
          padding: 16,
          marginBottom: 16,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <p style={{ ...body14, margin: 0, fontWeight: 600, color: tokens.color.ink }}>
          Skills are instructions only. monai never runs scripts or code from a skill folder.
        </p>
        <p style={{ ...body14, margin: 0, color: tokens.color.ink }}>
          A skill&apos;s allowed-tools setting is ignored. A skill cannot add tools or skip confirmation.
        </p>
      </div>
      <div role="status" aria-live="polite" data-testid="skills-status" style={{ ...small, minHeight: 21 }}>
        {status}
      </div>
      <div aria-busy={rows === null && listError === null}>
        {listError !== null ? (
          <div role="alert" data-testid="skills-load-error" style={{ ...errText, display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
            <span>{`Couldn't load skills: ${listError}. Check the backend is running, then try again.`}</span>
            <button type="button" style={rowBtn} className="coarse-tap" data-testid="skills-retry" onClick={() => void loadList()}>
              Try again
            </button>
          </div>
        ) : rows === null ? (
          <div style={small}>Loading skills…</div>
        ) : rows.length === 0 ? (
          <div data-testid="skills-empty">
            <div style={{ ...body14, fontWeight: 600, color: tokens.color.ink }}>No skills found.</div>
            <div style={small}>
              Add a folder containing a SKILL.md file to the skills folder (./skills in the monai project folder), then
              reload this page. Skills you add start switched off.
            </div>
          </div>
        ) : (
          <ul aria-label="Skills" style={{ margin: 0, padding: 0 }}>
            {rows.map(renderRow)}
          </ul>
        )}
      </div>
    </div>
  );
}
