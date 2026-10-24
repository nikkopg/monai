"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, input } from "../styles";
import { unpinned } from "../chat/extLabels";
import {
  type McpServer,
  type McpSecret,
  body14,
  errText,
  hint,
  fieldLabel,
  rowBtn,
  primaryBtn,
  dimmed,
  panelBox,
  panelHeading,
  warmBox,
  errDetail,
  serverUrl,
  putJson,
} from "./mcpShared";

// ---------------------------------------------------------------------------
// Add / edit form for an external MCP server (phase 41, plan 09; contract:
// 41-UI-SPEC.md section A3, D-04, D-05, A-01). Secrets live only in password
// inputs with no `name`; a saved value arrives masked from the server and,
// left alone, is sent back unchanged so the server keeps the real one. The
// local-read acknowledgement gates Save for a local command (A-01).
// ---------------------------------------------------------------------------

type Row = { name: string; value: string };
type Transport = McpServer["transport"];

const MAX_ROWS = 10;
const toRows = (s: McpSecret[]): Row[] => s.map((x) => ({ name: x.name, value: x.value_masked ?? "" }));
const lines = (t: string) => t.split("\n").map((s) => s.replace(/\r$/, "")).filter((s) => s !== "");

/** Warning shown while the package argument has no pinned version (never blocks). */
export function UnpinnedWarning({ command, args, live }: { command: string; args: string[]; live?: boolean }) {
  const pkg = unpinned(command, args);
  const box =
    pkg === null ? null : (
      <div data-testid="mcp-unpinned" style={{ ...warmBox, padding: "8px 12px" }}>
        {`${pkg} has no pinned version, so a new release would run without your review. Pin it as name@1.2.3 (npx) or name==1.2.3 (uvx).`}
      </div>
    );
  return live ? <div role="status">{box}</div> : box;
}

function SecretRows(props: {
  rows: Row[];
  onChange: (rows: Row[]) => void;
  noun: "header" | "variable";
  nameLabel: string;
  addLabel: string;
}) {
  const { rows, onChange, noun, nameLabel, addLabel } = props;
  const cap = noun === "header" ? "Header" : "Variable";
  const set = (i: number, patch: Partial<Row>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="text"
            style={{ ...input, flex: "1 1 160px", width: "auto" }}
            placeholder={nameLabel}
            aria-label={`${cap} ${i + 1} name`}
            autoComplete="off"
            spellCheck={false}
            value={r.name}
            onChange={(e) => set(i, { name: e.target.value })}
          />
          <input
            type="password"
            style={{ ...input, flex: "1 1 160px", width: "auto" }}
            placeholder="Value"
            aria-label={`${cap} ${i + 1} value`}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            value={r.value}
            onChange={(e) => set(i, { value: e.target.value })}
          />
          <button
            type="button"
            style={rowBtn}
            className="coarse-tap"
            aria-label={`Remove ${noun} ${i + 1}`}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      {rows.length < MAX_ROWS && (
        <div>
          <button
            type="button"
            style={rowBtn}
            className="coarse-tap"
            onClick={() => onChange([...rows, { name: "", value: "" }])}
          >
            {addLabel}
          </button>
        </div>
      )}
    </div>
  );
}

export default function McpServerForm(props: {
  /** null = add. */
  server: McpServer | null;
  onSaved: (slug: string, added: boolean) => void;
  onClose: () => void;
}) {
  const { server, onSaved, onClose } = props;
  const editing = server !== null;
  const key = editing ? server.slug : "new";

  const [slug, setSlug] = useState("");
  const [transport, setTransport] = useState<Transport>(server?.transport ?? "http");
  const [url, setUrl] = useState(server?.url ?? "");
  const [headers, setHeaders] = useState<Row[]>(toRows(server?.headers ?? []));
  const [command, setCommand] = useState(server?.command === "uvx" ? "uvx" : "npx");
  const [argsText, setArgsText] = useState((server?.args ?? []).join("\n"));
  const [env, setEnv] = useState<Row[]>(toRows(server?.env ?? []));
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const firstRef = useRef<HTMLInputElement | HTMLSelectElement>(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  const args = lines(argsText);
  const stdio = transport === "stdio";
  const argsChanged = editing && (command !== server.command || args.join("\n") !== server.args.join("\n"));
  const needAck = stdio && (!editing || argsChanged);
  const blocked = needAck && !ack;
  const name = editing ? server.slug : slug;

  const clean = (rows: Row[]) => rows.filter((r) => r.name !== "" || r.value !== "");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (blocked || busy) return;
    setBusy(true);
    setError("");
    const body = {
      slug: name,
      transport,
      url: stdio ? null : url,
      headers: stdio ? [] : clean(headers),
      command: stdio ? command : null,
      args: stdio ? args : [],
      env: stdio ? clean(env) : [],
      acknowledged_local_read: ack,
    };
    let fail = "";
    try {
      const r = editing
        ? await putJson(serverUrl(server.id), body)
        : await fetch("/api/mcp-servers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
      if (!r.ok) fail = await errDetail(r);
    } catch {
      fail = "Network error";
    }
    setBusy(false);
    if (fail) setError(`Couldn't save ${name || "the server"}: ${fail}. Nothing was changed.`);
    else onSaved(name, !editing);
  }

  const field = (id: string, text: string, node: React.ReactNode, hintText?: string) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <label htmlFor={id} style={fieldLabel}>
        {text}
      </label>
      {node}
      {hintText && (
        <div id={`${id}-hint`} style={hint}>
          {hintText}
        </div>
      )}
    </div>
  );

  return (
    <form
      id={`mcp-form-${key}`}
      role="group"
      aria-labelledby={`mcp-form-heading-${key}`}
      data-testid="mcp-form"
      onSubmit={save}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      style={panelBox}
    >
      <h3 id={`mcp-form-heading-${key}`} tabIndex={-1} style={panelHeading}>
        {editing ? `Edit ${server.slug}` : "Add a server"}
      </h3>

      {editing ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={fieldLabel}>Short name</div>
          <div style={{ ...body14, fontWeight: 600, color: tokens.color.ink, overflowWrap: "anywhere" }}>{server.slug}</div>
        </div>
      ) : (
        field(
          "mcp-slug",
          "Short name",
          <input
            id="mcp-slug"
            ref={firstRef as React.RefObject<HTMLInputElement>}
            type="text"
            style={input}
            autoComplete="off"
            spellCheck={false}
            aria-describedby="mcp-slug-hint"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />,
          "Lowercase letters, numbers and hyphens, up to 24. It prefixes the tool names the agent sees, so it can't be changed later.",
        )
      )}

      {editing ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={fieldLabel}>Type</div>
          <div style={body14}>{{ http: "Streamable HTTP", sse: "SSE", stdio: "Local command (npx or uvx)" }[transport]}</div>
        </div>
      ) : (
        <fieldset style={{ border: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          <legend style={{ ...fieldLabel, padding: 0, marginBottom: 8 }}>Type</legend>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {(
              [
                ["http", "Streamable HTTP"],
                ["sse", "SSE"],
                ["stdio", "Local command (npx or uvx)"],
              ] as [Transport, string][]
            ).map(([v, text]) => (
              <label
                key={v}
                className="coarse-tap"
                style={{ ...body14, color: tokens.color.ink, display: "flex", alignItems: "center", gap: 8, minHeight: 36 }}
              >
                <input
                  type="radio"
                  name="mcp-transport"
                  style={{ width: 20, height: 20 }}
                  checked={transport === v}
                  onChange={() => setTransport(v)}
                />
                {text}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {!stdio && (
        <>
          {field(
            "mcp-url",
            "URL",
            <input
              id="mcp-url"
              ref={editing ? (firstRef as React.RefObject<HTMLInputElement>) : undefined}
              type="text"
              inputMode="url"
              style={input}
              autoComplete="off"
              spellCheck={false}
              aria-describedby="mcp-url-hint"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />,
            "Start with https://. Don't put a password in the address; use a header below.",
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={fieldLabel}>Headers</div>
            <SecretRows rows={headers} onChange={setHeaders} noun="header" nameLabel="Header name" addLabel="Add header" />
            <div style={hint}>For example Authorization: Bearer … Values are saved masked and never shown again.</div>
          </div>
        </>
      )}

      {stdio && (
        <>
          {field(
            "mcp-command",
            "Command",
            <select
              id="mcp-command"
              ref={editing ? (firstRef as React.RefObject<HTMLSelectElement>) : undefined}
              style={{ ...input, width: "auto" }}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
            >
              <option value="npx">npx</option>
              <option value="uvx">uvx</option>
            </select>,
          )}
          {field(
            "mcp-args",
            "Arguments",
            <textarea
              id="mcp-args"
              rows={3}
              style={{ ...input, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
              spellCheck={false}
              aria-describedby="mcp-args-hint"
              value={argsText}
              onChange={(e) => setArgsText(e.target.value)}
            />,
            "One argument per line, passed as they are with no shell. monai adds -y for npx.",
          )}
          <UnpinnedWarning command={command} args={args} live />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={fieldLabel}>Environment</div>
            <SecretRows rows={env} onChange={setEnv} noun="variable" nameLabel="Variable name" addLabel="Add variable" />
            <div style={hint}>Only these variables, plus a few safe defaults, reach the command. Values are saved masked.</div>
          </div>
          <div data-testid="mcp-stdio-ack" style={{ ...warmBox, padding: "12px 16px" }}>
            <label style={{ display: "flex", alignItems: "flex-start", gap: 8, minHeight: 36 }} className="coarse-tap">
              <input
                type="checkbox"
                style={{ width: 20, height: 20, flexShrink: 0 }}
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
              />
              <span>
                <span style={{ fontWeight: 600 }}>A local command can read your monai data on this computer.</span>
                {" I only add packages I trust and have pinned to a version."}
              </span>
            </label>
          </div>
        </>
      )}

      {(headers.length > 0 || env.length > 0) && editing && (
        <div style={hint}>Saved values are masked. Leave one alone to keep it.</div>
      )}

      <div role="alert" data-testid="mcp-form-error" style={errText}>
        {error}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button
          type="submit"
          style={{ ...primaryBtn, ...dimmed(blocked || busy) }}
          className="coarse-tap"
          data-testid="mcp-save"
          disabled={blocked || busy}
          aria-describedby={blocked ? "mcp-ack-hint" : undefined}
        >
          {busy ? "Saving…" : "Save server"}
        </button>
        <button type="button" style={rowBtn} className="coarse-tap" data-testid="mcp-cancel" onClick={onClose}>
          Cancel
        </button>
        {blocked && (
          <span id="mcp-ack-hint" style={hint}>
            Tick the box above to save.
          </span>
        )}
      </div>
    </form>
  );
}
