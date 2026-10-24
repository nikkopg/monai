import { tokens, btn, btnGhost } from "../styles";

// Shared types and style objects for the Settings "External MCP servers" card
// (phase 41, plan 09; contract: 41-UI-SPEC.md section A). Same look as
// SkillsCard.tsx; kept in one place because the card, the form and the tool
// review panel all use them.

export type McpSecret = { name: string; value_masked: string | null };
export type McpServer = {
  id: string;
  slug: string;
  transport: "http" | "sse" | "stdio";
  url: string | null;
  destination: string;
  command: string | null;
  args: string[];
  headers: McpSecret[];
  env: McpSecret[];
  enabled: boolean;
  changed_count: number | null;
};

export const TRANSPORT_LABEL: Record<McpServer["transport"], string> = {
  http: "HTTP",
  sse: "SSE",
  stdio: "Local command",
};

/** What the owner would see on the command line: monai adds -y for npx. */
export const commandLine = (command: string | null, args: string[]): string =>
  [command ?? "", ...(command === "npx" ? ["-y"] : []), ...args].join(" ");

export const body14: React.CSSProperties = { fontSize: 14, lineHeight: 1.5 };
export const small: React.CSSProperties = { ...body14, color: tokens.color.muted3 };
export const errText: React.CSSProperties = { ...body14, color: tokens.color.terracottaText };
export const hint: React.CSSProperties = { fontSize: 12, lineHeight: 1.5, color: tokens.color.muted3 };
export const fieldLabel: React.CSSProperties = { ...body14, fontWeight: 600, color: tokens.color.ink };
export const blockLabel: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  lineHeight: 1.5,
  color: tokens.color.muted3,
  overflowWrap: "anywhere",
};
export const rowBtn: React.CSSProperties = { ...btnGhost, padding: "8px 16px", minHeight: 36, lineHeight: 1.5 };
export const primaryBtn: React.CSSProperties = { ...btn, padding: "8px 16px", minHeight: 36, lineHeight: 1.5 };
export const dimmed = (off: boolean): React.CSSProperties => (off ? { opacity: 0.6, cursor: "not-allowed" } : {});
export const panelBox: React.CSSProperties = {
  background: tokens.color.card,
  border: `1px solid ${tokens.color.border2}`,
  borderRadius: tokens.radius.md,
  padding: 16,
  marginTop: 16,
  display: "flex",
  flexDirection: "column",
  gap: 16,
};
export const panelHeading: React.CSSProperties = {
  fontSize: 15,
  fontWeight: 600,
  lineHeight: 1.3,
  margin: 0,
  color: tokens.color.ink,
  overflowWrap: "anywhere",
};
export const pre: React.CSSProperties = {
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
  maxHeight: 240,
  overflow: "auto",
};
export const chipBase: React.CSSProperties = {
  display: "inline-block",
  fontSize: 12,
  fontWeight: 600,
  lineHeight: 1.5,
  borderRadius: tokens.radius.pill,
  padding: "4px 8px",
  color: tokens.color.ink,
};
export const chipNeutral: React.CSSProperties = {
  ...chipBase,
  background: tokens.color.tintNeutral,
  color: tokens.color.muted3,
};
export const chipWarm: React.CSSProperties = {
  ...chipBase,
  background: tokens.color.tintWarm,
  border: `1px solid ${tokens.color.border2}`,
};
export const warmBox: React.CSSProperties = {
  ...body14,
  color: tokens.color.ink,
  background: tokens.color.tintWarm,
  border: `1px solid ${tokens.color.border2}`,
  borderRadius: tokens.radius.sm,
  overflowWrap: "anywhere",
};

/** `detail` string from an error body (or the first validation message), else `HTTP {status}`. */
export async function errDetail(r: Response): Promise<string> {
  try {
    const d = (await r.json())?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && typeof d[0]?.msg === "string") return d[0].msg;
  } catch {
    // keep the status-based detail
  }
  return `HTTP ${r.status}`;
}

export const serverUrl = (id: string) => `/api/mcp-servers/${encodeURIComponent(id)}`;

export async function putJson(url: string, body: unknown): Promise<Response> {
  return fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
