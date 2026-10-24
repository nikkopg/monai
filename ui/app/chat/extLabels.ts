// The pure label, state and join logic for Phase 41 external MCP tools
// (41-UI-SPEC sections B, C and "Copywriting Contract"). No React, so every
// sentence is unit-tested without a browser.
//
// Rule (D-25): every label here is derived from `ext_calls` state (approval,
// decided_via, receipt) or from a server-built string, never from the model's
// words. "Sent to" is produced ONLY for receipt === "confirmed" (D-21).

export type ExtApproval = "pending" | "approved" | "denied" | "expired";
export type ExtReceipt = "pending" | "confirmed" | "failed" | "unknown" | null;

/** One row of GET /threads/{id}.ext_calls (or a card built from the live stream). */
export type ExtCall = {
  id: string;
  message_id: string | null;
  server_slug: string;
  tool: string;
  args: Record<string, unknown>;
  destination: string;
  leaves_machine: boolean;
  reason: string | null;
  approval: ExtApproval;
  decided_via: "user" | "policy" | "stop" | "expiry" | null;
  expires_at: string;
  receipt: ExtReceipt;
  error_class: string | null;
};

export type ExtNotice = { code: string; server?: string | null; message?: string | null; limit?: number | null };

// --- Names (C1 parse rule) --------------------------------------------------

const PREFIX = "ext__";

/** `ext__<slug>__<tool>`: a slug has no underscore, so the first `__` splits. */
export function parseExt(name: string): { slug: string; tool: string } | null {
  if (!name.startsWith(PREFIX)) return null;
  const rest = name.slice(PREFIX.length);
  const i = rest.indexOf("__");
  if (i <= 0 || i + 2 >= rest.length) return null;
  return { slug: rest.slice(0, i), tool: rest.slice(i + 2) };
}

export const isExt = (name: string): boolean => parseExt(name) !== null;

// --- Unpinned package check (A2) ---------------------------------------------

/**
 * The package argument when it carries no pinned version, else null. The package
 * is the first argument that does not start with "-". Pinned means `name@<digit>`
 * (the "@" after index 0 for a scoped package) or `name==<digit>`.
 */
export function unpinned(command: string, args: string[]): string | null {
  void command;
  const pkg = args.find((a) => !a.startsWith("-"));
  if (pkg === undefined) return null;
  const at = pkg.lastIndexOf("@");
  if (at > 0 && /^\d/.test(pkg.slice(at + 1))) return null;
  if (/==\d/.test(pkg)) return null;
  return pkg;
}

// --- Countdown (B2) ----------------------------------------------------------

export function countdownText(msLeft: number): string {
  if (msLeft <= 0) return "Auto-denying…";
  const s = Math.ceil(msLeft / 1000);
  return `Auto-denies in ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const isLastMinute = (msLeft: number): boolean => msLeft <= 60_000;

// --- Step to call join (PC-07) -------------------------------------------------

/** Recursive sorted-key JSON, so equal args compare equal whatever the key order. */
export function canonicalArgs(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalArgs).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const o = value as Record<string, unknown>;
    return `{${Object.keys(o)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonicalArgs(o[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/**
 * Per step, the ext_calls row it ran as. Per external step in order: the first
 * not-yet-used call whose `ext__<slug>__<tool>` name and canonical args match;
 * a repeat of an already used key reuses that call; otherwise null.
 */
export function joinSteps(
  steps: { tool: string; args: Record<string, unknown> }[],
  calls: ExtCall[]
): (ExtCall | null)[] {
  const used = new Set<string>();
  const byKey = new Map<string, ExtCall>();
  return steps.map((s) => {
    if (!isExt(s.tool)) return null;
    const key = `${s.tool}|${canonicalArgs(s.args)}`;
    const seen = byKey.get(key);
    if (seen) return seen;
    const hit = calls.find(
      (c) =>
        !used.has(c.id) &&
        `${PREFIX}${c.server_slug}__${c.tool}` === s.tool &&
        canonicalArgs(c.args) === canonicalArgs(s.args)
    );
    if (!hit) return null;
    used.add(hit.id);
    byKey.set(key, hit);
    return hit;
  });
}

// --- Card state and sentences (B3) --------------------------------------------

export type CardState =
  | "pending"
  | "busy"
  | "running"
  | "sent"
  | "failed"
  | "unknown"
  | "denied"
  | "stopped"
  | "expired"
  | "missing";

/** First match wins (UI-SPEC B3). A missing row is `missing`. */
export function cardState(call: ExtCall | null, busy = false): CardState {
  if (!call) return "missing";
  switch (call.approval) {
    case "pending":
      return busy ? "busy" : "pending";
    case "approved":
      return call.receipt === "confirmed"
        ? "sent"
        : call.receipt === "failed"
        ? "failed"
        : call.receipt === "unknown"
        ? "unknown"
        : "running";
    case "denied":
      return call.decided_via === "stop" ? "stopped" : call.decided_via === "expiry" ? "expired" : "denied";
    default:
      return "expired";
  }
}

/** The status sentence of a card state; "" for the states that show buttons instead. */
export function cardStatus(state: CardState, call: ExtCall): string {
  const s = call.server_slug;
  switch (state) {
    case "running":
      return `Allowed once. Running on ${s}…`;
    case "sent":
      return `Sent to ${s}.`; // the only place the card may say "Sent to" (D-21)
    case "failed":
      return `Allowed, but the call to ${s} failed${call.error_class ? ` (${call.error_class})` : ""}. Don't assume it happened.`;
    case "unknown":
      return `Allowed, but the outcome is unknown: monai lost contact before ${s} confirmed it. Check on ${s} before trying again.`;
    case "denied":
      return `Denied. Nothing was sent to ${s}.`;
    case "stopped":
      return `Denied because the run was stopped. Nothing was sent to ${s}.`;
    case "expired":
      return `No answer in time, so it was denied. Nothing was sent to ${s}.`;
    case "missing":
      return "This request is no longer available.";
    default:
      return "";
  }
}

export const SENT_NOTE = "What it returned is external and unverified.";

/** The dot-separated suffix a ToolSteps row appends (C1). Only a confirmed receipt says "Sent to". */
export function stepSuffix(call: ExtCall | null): string {
  switch (cardState(call)) {
    case "pending":
      return " · waiting for your answer";
    case "denied":
      return " · denied";
    case "stopped":
      return " · denied (stopped)";
    case "expired":
      return " · expired, denied";
    case "running":
      return " · in progress";
    case "sent":
      return ` · Sent to ${call!.server_slug}`;
    case "failed":
      return " · failed";
    case "unknown":
      return " · outcome unknown";
    default:
      return "";
  }
}

export function decisionLabel(call: ExtCall): string {
  if (call.approval === "pending") return "Waiting for your answer";
  if (call.approval === "expired" || call.decided_via === "expiry") return "Timed out, so denied";
  if (call.decided_via === "stop") return "Denied because the run was stopped";
  if (call.approval === "denied") return "You denied it";
  return call.decided_via === "policy" ? "Allowed by your Always rule" : "You allowed it";
}

export function receiptLabel(call: ExtCall): string {
  switch (cardState(call)) {
    case "sent":
      return `Sent to ${call.server_slug}`;
    case "failed":
      return `failed${call.error_class ? ` (${call.error_class})` : ""}`;
    case "unknown":
      return "outcome unknown";
    case "running":
      return "in progress";
    case "pending":
      return "waiting for your answer";
    default:
      return "nothing was sent";
  }
}

/** Unique slugs of approved calls (failed and unknown included: they were sent), first-use order (C2). */
export function footerServers(calls: ExtCall[]): string[] {
  return Array.from(new Set(calls.filter((c) => c.approval === "approved").map((c) => c.server_slug)));
}

// --- Notices (C3) ---------------------------------------------------------------

export function noticeSentence(n: ExtNotice): { text: string; linkText?: string; tail?: string } {
  const start = n.server || "An external server";
  const mid = n.server || "an external server";
  switch (n.code) {
    case "tools_changed":
      return { text: `${start} changed its tools; review them in `, linkText: "Settings", tail: "." };
    case "unreachable":
      return { text: `Couldn't reach ${mid}, so its tools were left out of this answer.` };
    case "cap":
      return {
        text: `Only the first ${n.limit ?? 16} external tools were offered this time. Set the ones you don't need to Deny in Settings.`,
      };
    case "too_many_tools":
      return { text: `${start} offers too many tools (over 200), so none of them were used.` };
    case "blocked":
      return { text: `monai blocked a call to ${mid} because its arguments contained a monai secret.` };
    default:
      return { text: n.message ?? "" };
  }
}

// --- Live events (B2) -------------------------------------------------------------

export type ExtEvent =
  | {
      type: "approval_required";
      call_id: string;
      server: string;
      tool: string;
      args: Record<string, unknown>;
      destination: string;
      leaves_machine: boolean;
      expires_at: string;
      reason?: string | null;
    }
  | {
      type: "ext_call";
      call_id: string;
      approval?: ExtApproval; // absent on receipt events (ext_calls._receipt)
      decided_via?: ExtCall["decided_via"];
      receipt?: ExtReceipt;
      error_class?: string | null;
    };

/**
 * Fold one stream event into the call list. The last ext_call wins; a replayed
 * approval_required for a call already known never turns it back to pending.
 */
export function mergeCallEvent(calls: ExtCall[], e: ExtEvent): ExtCall[] {
  const known = calls.some((c) => c.id === e.call_id);
  if (e.type === "approval_required") {
    if (known) return calls;
    return [
      ...calls,
      {
        id: e.call_id,
        message_id: null,
        server_slug: e.server,
        tool: e.tool,
        args: e.args,
        destination: e.destination,
        leaves_machine: e.leaves_machine,
        reason: e.reason ?? null,
        approval: "pending",
        decided_via: null,
        expires_at: e.expires_at,
        receipt: null,
        error_class: null,
      },
    ];
  }
  return calls.map((c) =>
    c.id === e.call_id
      ? {
          ...c,
          approval: e.approval ?? c.approval,
          decided_via: e.decided_via ?? c.decided_via,
          receipt: e.receipt ?? c.receipt,
          error_class: e.error_class ?? c.error_class,
        }
      : c
  );
}

// --- Announcements (B2) -----------------------------------------------------------

export const announce = {
  appeared: (c: ExtCall, nowMs: number = Date.now()) => {
    const n = Math.max(1, Math.round((Date.parse(c.expires_at) - nowMs) / 60_000));
    return `Approval needed: ${c.server_slug} wants to run ${c.tool}. It is denied automatically in ${n} ${n === 1 ? "minute" : "minutes"}.`;
  },
  oneMinute: (c: ExtCall) => `One minute left to answer ${c.tool} on ${c.server_slug}.`,
  terminal: (c: ExtCall) => cardStatus(cardState(c), c),
};
