"use client";

import { useEffect, useRef, useState } from "react";

import { tokens } from "../styles";
import {
  type McpServer,
  body14,
  small,
  errText,
  hint,
  blockLabel,
  rowBtn,
  primaryBtn,
  dimmed,
  panelBox,
  panelHeading,
  pre,
  chipNeutral,
  chipWarm,
  errDetail,
  serverUrl,
  putJson,
} from "./mcpShared";

// ---------------------------------------------------------------------------
// Test / review panel for one external MCP server (phase 41, plan 09; contract:
// 41-UI-SPEC.md section A4, D-09, D-10, D-18). Shows every tool's description,
// input schema and server-claimed annotations as raw text, lets the owner set
// Ask / Always / Deny per tool, and puts the Enable button after all of it.
// Enable echoes the tools_hash of the list on screen; a 409 swaps in the live
// list. Every server-supplied string is a React text node: no raw HTML.
// ---------------------------------------------------------------------------

type Tool = {
  name: string;
  description: string;
  input_schema: unknown;
  annotations: Record<string, unknown> | null;
  usable_name: boolean;
  status: "new" | "changed" | "unchanged";
};
type TestOut = { tools_hash: string; tools: Tool[]; removed: string[]; policies: Record<string, string> };
type Policy = "ask" | "always" | "deny";

const STALE =
  "This server's tools changed after you opened this list. The list below is the new version. Read it, then enable it again.";
const POLICY_TEXT: Record<Policy, string> = { ask: "Ask", always: "Always", deny: "Deny" };
const UNUSABLE =
  "The agent can't use this tool: its name doesn't fit monai's rules (letters, numbers, - and _, 64 characters including the server prefix).";

const asPolicy = (p: string | undefined): Policy => (p === "always" || p === "deny" ? p : "ask");
const pretty = (v: unknown) => JSON.stringify(v, null, 2);

export default function McpToolReview(props: {
  server: McpServer;
  onClose: () => void;
  onEnabled: () => void;
  onStatus: (text: string) => void;
  onGone: () => void;
}) {
  const { server, onClose, onEnabled, onStatus, onGone } = props;
  const slug = server.slug;
  const reviewed = server.changed_count !== null;

  const [data, setData] = useState<TestOut | null>(null);
  const [failed, setFailed] = useState("");
  const [policies, setPolicies] = useState<Record<string, Policy>>({});
  const [toolErr, setToolErr] = useState<Record<string, string>>({});
  const [panelError, setPanelError] = useState("");
  const [enabling, setEnabling] = useState(false);
  const [rechecking, setRechecking] = useState(false);

  const panelRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const enableRef = useRef<HTMLButtonElement>(null);
  const focusHeading = useRef(true);
  const focusEnable = useRef(false);

  /** Run Test and swap the result in; returns the failure detail, or "" on success. */
  async function runTest(): Promise<string> {
    try {
      const r = await fetch(`${serverUrl(server.id)}/test`, { method: "POST" });
      if (!r.ok) return await errDetail(r);
      const out: TestOut = await r.json();
      setData(out);
      setPolicies(Object.fromEntries(out.tools.map((t) => [t.name, asPolicy(out.policies?.[t.name])])));
      setToolErr({});
      return "";
    } catch {
      return "Network error";
    }
  }

  async function connect() {
    setFailed("");
    setData(null);
    const d = await runTest();
    if (d) setFailed(d);
  }

  useEffect(() => {
    void connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Focus the heading when the first list lands; scroll every block to the top on new text.
  useEffect(() => {
    if (!data) return;
    if (focusHeading.current) {
      headingRef.current?.focus();
      focusHeading.current = false;
    }
    panelRef.current?.querySelectorAll("pre").forEach((p) => (p.scrollTop = 0));
  }, [data]);

  // Keep focus on the commit button after an outcome that leaves the panel open.
  useEffect(() => {
    if (focusEnable.current && !enabling && !rechecking) {
      enableRef.current?.focus();
      focusEnable.current = false;
    }
  });

  async function enable() {
    if (!data) return;
    setEnabling(true);
    setPanelError("");
    let status = 0;
    let detail = "Network error";
    try {
      const r = await putJson(`${serverUrl(server.id)}/enabled`, { enabled: true, tools_hash: data.tools_hash });
      status = r.status;
      if (!r.ok) detail = await errDetail(r);
    } catch {
      status = 0;
    }
    if (status === 200) return onEnabled();
    if (status === 404) return onGone();
    if (status === 409) {
      setRechecking(true);
      setPanelError(STALE);
      focusEnable.current = true;
      const d = await runTest();
      if (d) setPanelError(`Couldn't re-check ${slug}: ${d}. Nothing was enabled.`);
      setRechecking(false);
    } else {
      setPanelError(`Couldn't enable ${slug}: ${detail}. ${server.enabled ? "It stays as it was." : "It stays off."}`);
      focusEnable.current = true;
    }
    setEnabling(false);
  }

  async function setPolicy(tool: string, next: Policy) {
    const prev = policies[tool] ?? "ask";
    setPolicies((p) => ({ ...p, [tool]: next }));
    setToolErr((e) => ({ ...e, [tool]: "" }));
    let fail = "";
    try {
      const r = await putJson(`${serverUrl(server.id)}/tools/${encodeURIComponent(tool)}`, { policy: next });
      if (!r.ok) fail = await errDetail(r);
    } catch {
      fail = "Network error";
    }
    if (fail) {
      setPolicies((p) => ({ ...p, [tool]: prev }));
      setToolErr((e) => ({ ...e, [tool]: `Couldn't change ${tool}: ${fail}. It stays on ${POLICY_TEXT[prev]}.` }));
    } else {
      onStatus(`${tool} is now set to ${POLICY_TEXT[next]}.`);
    }
  }

  const raw = (label: string, tool: string, text: string, testid?: string) => (
    <pre style={pre} tabIndex={0} role="region" aria-label={`${label} of ${tool}`} data-testid={testid}>
      {text}
    </pre>
  );

  const connecting = data === null && failed === "";
  const tools = data?.tools ?? [];
  const anyChanged = tools.some((t) => t.status !== "unchanged") || (server.changed_count ?? 0) > 0;
  const showCommit = data !== null && (!server.enabled || anyChanged);
  const commitLabel = server.enabled ? "Approve these tools" : "Enable server";
  const counts = [
    [tools.filter((t) => t.status === "new").length, "new"],
    [tools.filter((t) => t.status === "changed").length, "changed"],
    [data?.removed.length ?? 0, "no longer offered"],
  ]
    .filter(([n]) => n !== 0)
    .map(([n, w]) => `${n} ${w}`)
    .join(", ");

  return (
    <div
      id={`mcp-panel-${slug}`}
      ref={panelRef}
      role="group"
      aria-labelledby={`mcp-panel-heading-${slug}`}
      aria-busy={connecting}
      data-testid="mcp-panel"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !enabling) onClose();
      }}
      style={panelBox}
    >
      <h3 id={`mcp-panel-heading-${slug}`} ref={headingRef} tabIndex={-1} style={panelHeading}>
        {`Tools from ${slug}`}
      </h3>

      {connecting && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={small}>{`Connecting to ${slug}…`}</div>
          {server.transport === "stdio" && (
            <div style={small}>The first run of a local command can take about 10 seconds while it downloads.</div>
          )}
        </div>
      )}

      {failed !== "" && (
        <div role="alert" style={errText}>
          {`Couldn't connect to ${slug}: ${failed}. Check the address and settings, then try again.`}
        </div>
      )}

      {data && (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div id={`mcp-count-${slug}`} style={small}>
              {tools.length === 0 ? "This server offers no tools." : `${tools.length} ${tools.length === 1 ? "tool" : "tools"} found.`}
            </div>
            {reviewed && counts && <div style={small}>{`${counts}.`}</div>}
          </div>

          {tools.map((t, i) => (
            <article
              key={t.name}
              data-testid="mcp-tool"
              data-tool={t.name}
              style={{
                borderTop: `1px solid ${tokens.color.borderInner}`,
                padding: "16px 0",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
                <span style={{ ...body14, fontWeight: 600, color: tokens.color.ink, overflowWrap: "anywhere" }}>{t.name}</span>
                {!t.usable_name ? (
                  <span style={chipWarm}>Unusable name</span>
                ) : (
                  reviewed && (
                    <span data-testid="mcp-tool-state" style={t.status === "unchanged" ? chipNeutral : chipWarm}>
                      {t.status === "new" ? "New" : t.status === "changed" ? "Changed" : "Unchanged"}
                    </span>
                  )
                )}
              </div>
              {!t.usable_name ? (
                <div style={{ ...body14, color: tokens.color.ink }}>{UNUSABLE}</div>
              ) : (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <label htmlFor={`mcp-policy-${slug}-${i}`} style={blockLabel}>
                    Policy
                  </label>
                  <select
                    id={`mcp-policy-${slug}-${i}`}
                    data-testid="mcp-policy"
                    aria-label={`Policy for ${t.name}`}
                    value={policies[t.name] ?? "ask"}
                    onChange={(e) => void setPolicy(t.name, e.target.value as Policy)}
                    style={{
                      background: tokens.color.inputBg,
                      border: `1px solid ${tokens.color.border2}`,
                      borderRadius: tokens.radius.sm,
                      color: tokens.color.text,
                      padding: "6px 8px",
                      fontSize: 14,
                      minHeight: 36,
                    }}
                    className="coarse-tap"
                  >
                    {(Object.keys(POLICY_TEXT) as Policy[]).map((p) => (
                      <option key={p} value={p}>
                        {POLICY_TEXT[p]}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {toolErr[t.name] && (
                <div role="alert" data-testid="mcp-tool-error" style={errText}>
                  {toolErr[t.name]}
                </div>
              )}
              <div style={blockLabel}>Description (written by the server)</div>
              {raw("Description", t.name, t.description)}
              <div style={blockLabel}>Input schema</div>
              {raw("Input schema", t.name, pretty(t.input_schema))}
              {t.annotations && (
                <>
                  <div style={blockLabel}>Claimed by the server</div>
                  {raw("Annotations", t.name, pretty(t.annotations))}
                  <div style={hint}>Not verified. monai ignores these when deciding whether to ask.</div>
                </>
              )}
            </article>
          ))}

          {data.removed.length > 0 && (
            <div style={small}>{`No longer offered by the server: ${data.removed.join(", ")}.`}</div>
          )}
          <div style={hint}>
            Ask: you approve each call. Always: runs without asking, except right after an answer has used your monai
            data. Deny: the agent never sees the tool. At most 16 external tools are offered per chat, sorted by server
            and then tool name; set the ones you don&apos;t need to Deny.
          </div>
          <div style={small}>
            Shown as the server sent them. The agent reads the first 1000 characters of each description. If a
            tool&apos;s name, description or input schema changes later, that tool is held back until you review it again.
          </div>
        </>
      )}

      <div role="alert" data-testid="mcp-panel-error" style={errText}>
        {panelError}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {failed !== "" && (
          <button type="button" style={rowBtn} className="coarse-tap" data-testid="mcp-retry" onClick={() => void connect()}>
            Try again
          </button>
        )}
        {showCommit && (
          <button
            type="button"
            ref={enableRef}
            style={{ ...primaryBtn, ...dimmed(enabling || rechecking || tools.length === 0) }}
            className="coarse-tap"
            data-testid="mcp-enable"
            aria-label={server.enabled ? `Approve these tools for ${slug}` : `Enable server ${slug}`}
            disabled={enabling || rechecking || tools.length === 0}
            aria-describedby={tools.length === 0 ? `mcp-count-${slug}` : undefined}
            onClick={() => void enable()}
          >
            {enabling ? "Enabling…" : commitLabel}
          </button>
        )}
        <button
          type="button"
          style={rowBtn}
          className="coarse-tap"
          data-testid="mcp-close"
          disabled={enabling}
          onClick={onClose}
        >
          Close
        </button>
      </div>
    </div>
  );
}
