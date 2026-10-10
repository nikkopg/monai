/**
 * Pure helpers for the /inbox page and the sidebar badge (Phase 33).
 *
 * No React and no Next imports, so a non-browser Playwright spec can import it.
 * Every user-visible string here is the 33-UI-SPEC copy verbatim.
 */

import { fmtPlain } from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DuplicateFlag =
  | { kind: "transaction"; id: number; date: string; amount: string; merchant: string | null }
  | { kind: "proposal"; id: string; row: number };

export type ProposalRow = {
  id?: number;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  old_name?: string;
  new_name?: string;
  from_name?: string;
  into_name?: string;
  affected_count?: number;
  account_id?: number;
  target_balance?: string;
  duplicates?: DuplicateFlag[];
  skip?: boolean;
};

export type InboxProposal = {
  id: string;
  operation: string;
  payload: { operation?: string; rows: ProposalRow[] };
  status: string;
  expires_at: string;
  created_at: string;
  confirmed_at: string | null;
  channel: string;
  status_changed_at?: string;
  supersedes_id: string | null;
  failed_attempts: number;
  code?: string | null;
};

export type CardPhase =
  | "live"
  | "approved"
  | "approvedElsewhere"
  | "rejected"
  | "rejectedElsewhere"
  | "expired"
  | "superseded"
  | "vanished";

export type HeldCard = { proposal: InboxProposal; phase: CardPhase; settledAt?: number };

export type ActionOutcome =
  | { kind: "ok" }
  | { kind: "phase"; phase: CardPhase; message?: string }
  | { kind: "error"; message: string };

// ---------------------------------------------------------------------------
// Copy constants
// ---------------------------------------------------------------------------

export const APPROVER_KEY_PAGE_MSG =
  "Approvals aren't set up — the web server is missing a valid approver key. See the README approver-key step, then restart.";
export const APPROVER_KEY_ACTION_MSG =
  "Approvals aren't set up — the web server is missing a valid approver key.";
export const NETWORK_FAIL_MSG = "Couldn't reach monai. Try again.";
export const LEDGER_CHANGED_MSG =
  "Ledger changed since you reviewed; reload to see the updated card.";
export const ALL_SKIPPED_MSG = "Every row is skipped — reject this proposal instead";

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
const included = (rows: ProposalRow[]) => rows.filter((r) => r.skip !== true).length;
const skippedCount = (rows: ProposalRow[]) => rows.length - included(rows);

// Fixed (count-free) effect labels from the UI-SPEC "Approve Label Rules" table.
const FIXED_LABEL: Record<string, string> = {
  add_transfer: "Add 1 transfer",
  add_account: "Add account",
  edit_account: "Edit account",
  delete_account: "Delete account",
  rename_category: "Rename category",
  merge_category: "Merge category",
  add_holding: "Add holding",
  edit_holding: "Edit holding",
  delete_holding: "Delete holding",
  add_investment_transfer: "Move cash to investments",
  add_funded_buy: "Record funded buy",
  add_funded_sell: "Record funded sell",
  add_balance_adjustment: "Adjust balance",
};

// Counted verbs: "<Verb> N transaction(s)".
const COUNTED_VERB: Record<string, string> = {
  add_transaction: "Add",
  edit_transaction: "Edit",
  delete_transaction: "Delete",
};

/** Effect phrase without the skip clause; null for an unknown operation. */
function effectPhrase(operation: string, rows: ProposalRow[]): string | null {
  const verb = COUNTED_VERB[operation];
  if (verb) {
    const n = included(rows);
    return `${verb} ${n} ${plural(n, "transaction", "transactions")}`;
  }
  return FIXED_LABEL[operation] ?? null;
}

/** The Approve button text: says what approving will do. */
export function approveLabel(operation: string, rows: ProposalRow[]): string {
  const base = effectPhrase(operation, rows);
  if (base === null) return "Apply this change";
  const k = skippedCount(rows);
  return operation === "add_transaction" && k >= 1 ? `${base}, ${k} skipped` : base;
}

const accountOf = (r: ProposalRow): string | null => {
  const a = r.after?.account;
  return typeof a === "string" && a !== "" ? a : null;
};

/** Card heading: effect phrase (no skip clause) plus the accounts when known. */
export function cardTitle(operation: string, rows: ProposalRow[]): string {
  const base = effectPhrase(operation, rows) ?? operation.replace(/_/g, " ");
  const accounts: string[] = [];
  for (const r of rows) {
    if (r.skip === true) continue;
    const a = accountOf(r);
    if (a && !accounts.includes(a)) accounts.push(a);
  }
  if (accounts.length === 0) return base;
  if (accounts.length === 1) return `${base} to ${accounts[0]}`;
  if (accounts.length === 2) return `${base} to ${accounts[0]} and ${accounts[1]}`;
  if (accounts.length === 3) {
    return `${base} to ${accounts[0]}, ${accounts[1]} and ${accounts[2]}`;
  }
  return `${base} to ${accounts.slice(0, 3).join(", ")} and ${accounts.length - 3} more`;
}

/** Footer shown on an approved card. */
export function approvedFooter(operation: string, rows: ProposalRow[]): string {
  if (operation !== "add_transaction") return "Applied.";
  const k = skippedCount(rows);
  return k >= 1 ? `${included(rows)} added, ${k} skipped` : `${included(rows)} added`;
}

const enGbShort = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** "just now" / "N min ago" / "N h ago" / "N days ago" / local date past a week. */
export function relativeAge(createdMs: number, nowMs: number): string {
  const diff = Math.max(0, nowMs - createdMs);
  const min = Math.floor(diff / 60_000);
  if (diff < 60_000) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(diff / 3_600_000);
  if (h < 24) return `${h} h ago`;
  if (diff <= 7 * 86_400_000) {
    const d = Math.floor(diff / 86_400_000);
    return `${d} ${plural(d, "day", "days")} ago`;
  }
  return enGbShort.format(new Date(createdMs));
}

/** "expires in 47 h" / "expires in 12 min" / "expires in under a minute" / null when past. */
export function expirySentence(expiresMs: number, nowMs: number): string | null {
  const rem = expiresMs - nowMs;
  if (rem >= 3_600_000) return `expires in ${Math.floor(rem / 3_600_000)} h`;
  if (rem >= 60_000) return `expires in ${Math.floor(rem / 60_000)} min`;
  if (rem > 0) return "expires in under a minute";
  return null;
}

export function pendingStatus(expiresMs: number, nowMs: number): string {
  const s = expirySentence(expiresMs, nowMs);
  return s === null ? "Expired · ask again to redo this" : `Waiting for you · ${s}`;
}

const enGbFull = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

/** "7 Oct 2026" from YYYY-MM-DD (built from parts: ISO strings shift by timezone). */
export function fmtRowDate(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const s = String(value);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.slice(0, 10));
  if (!m) return s; // chat dates are unvalidated
  return enGbFull.format(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

const signedFmt = new Intl.NumberFormat("en-US", { signDisplay: "exceptZero" });

/** "-35,000" / "+250,000"; the raw value when not numeric. */
export function fmtSigned(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? signedFmt.format(Math.round(n)) : String(value);
}

/** An absolute amount, minus kept, no "+": "-250,000" / "5,000,000"; the raw value when not numeric. */
export function fmtAbsolute(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? fmtPlain(n) : String(value);
}

/** "50,000" (sign dropped); the raw value when not numeric. */
export function fmtUnsigned(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? fmtPlain(Math.abs(n)) : String(value);
}

/**
 * Unsigned amount next to an explicit currency, never rounded away: IDR has no
 * sub-unit so whole amounts print bare; other currencies keep 2+ decimals
 * ("1,234.56 USD"), so the approval line matches the applied amount (WR-08).
 */
export function fmtMoney(value: unknown, currency: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: currency === "IDR" ? 0 : 2,
    maximumFractionDigits: 8,
  }).format(Math.abs(n));
}

const hhmmFmt = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Local 24 h "HH:mm". */
export function hhmm(ms: number): string {
  return hhmmFmt.format(new Date(ms));
}

/** Sidebar badge text; null hides it. Offline shows an em dash. */
export function badgeText(pending: number | null, offline: boolean): string | null {
  if (offline) return "—";
  if (pending === null || pending <= 0) return null;
  return pending > 99 ? "99+" : String(pending);
}

/** Accessible name of the Inbox nav link. */
export function navInboxLabel(pending: number | null, offline: boolean): string {
  if (offline) return "Inbox, pending count unavailable";
  return pending !== null && pending > 0 ? `Inbox, ${pending} pending` : "Inbox";
}

export function duplicateChipText(n: number): string {
  return n === 1 ? "Possible duplicate" : `${n} possible duplicates`;
}

export function transactionFlagText(flag: Extract<DuplicateFlag, { kind: "transaction" }>): string {
  return `Matches an existing record: ${fmtRowDate(flag.date)}, ${fmtSigned(flag.amount)}, ${
    flag.merchant ?? "no merchant"
  }`;
}

export function proposalFlagText(flag: Extract<DuplicateFlag, { kind: "proposal" }>): string {
  return `Same as row ${flag.row + 1} of another waiting proposal`;
}

export function skipAriaLabel(index: number, row: ProposalRow): string {
  const merchant = row.after?.merchant;
  const who = typeof merchant === "string" && merchant !== "" ? merchant : "no merchant";
  return `${row.skip === true ? "Include" : "Skip"} row ${index + 1}: ${who}, ${fmtSigned(
    row.after?.amount
  )}`;
}

/** MCP proposals lock for Claude after 5 wrong codes; the owner can still approve. */
export function isLocked(p: Pick<InboxProposal, "channel" | "failed_attempts">): boolean {
  return p.channel === "mcp" && p.failed_attempts >= 5;
}

// ---------------------------------------------------------------------------
// State helpers
// ---------------------------------------------------------------------------

const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export const isUuid = (s: unknown): s is string => typeof s === "string" && UUID_RE.test(s);

/** A finite non-negative integer: the only shape trusted as a pending count. */
export const isPendingCount = (x: unknown): x is number =>
  typeof x === "number" && Number.isInteger(x) && x >= 0;

/** Reads `{pending: n}` from /proposals/counts; null means "treat the poll as failed". */
export function parsePendingCount(json: unknown): number | null {
  if (typeof json !== "object" || json === null || Array.isArray(json)) return null;
  const p = (json as { pending?: unknown }).pending;
  return isPendingCount(p) ? p : null;
}

/** Server clock minus local clock in ms, from a `Date` response header; 0 when unusable. */
export function serverOffset(dateHeader: string | null, localNowMs: number): number {
  if (!dateHeader) return 0;
  const t = Date.parse(dateHeader);
  return Number.isNaN(t) ? 0 : t - localNowMs;
}

/**
 * Copy only the boolean `skip` flag from a PATCH response onto the held rows.
 * The response carries no `duplicates`, so replacing rows would drop the chips.
 */
export function mergeSkip(held: ProposalRow[], resp: ProposalRow[]): ProposalRow[] {
  return held.map((row, i) => {
    const skip = resp[i]?.skip;
    return typeof skip === "boolean" ? { ...row, skip } : row;
  });
}

const createdOf = (c: HeldCard) => {
  const t = Date.parse(c.proposal.created_at);
  return Number.isNaN(t) ? 0 : t;
};

/**
 * Merge a poll result into the held cards: never replace a card with an
 * in-flight action, keep settled cards in their slot, and settle a live card
 * that disappeared with no local explanation (decided elsewhere, or expired).
 */
export function mergePoll(
  held: HeldCard[],
  server: InboxProposal[],
  busy: ReadonlySet<string>,
  nowMs: number
): { cards: HeldCard[]; expired: number; vanished: number } {
  const byId = new Map(server.map((p) => [p.id, p]));
  const heldIds = new Set(held.map((c) => c.proposal.id));
  let expired = 0;
  let vanished = 0;
  const cards: HeldCard[] = held.map((c) => {
    if (busy.has(c.proposal.id) || c.phase !== "live") return c;
    const fresh = byId.get(c.proposal.id);
    if (fresh) return { proposal: fresh, phase: "live" };
    if (nowMs < Date.parse(c.proposal.expires_at)) {
      vanished++;
      return { ...c, phase: "vanished", settledAt: nowMs };
    }
    expired++;
    return { ...c, phase: "expired", settledAt: nowMs };
  });
  for (const p of server) {
    if (!heldIds.has(p.id)) cards.push({ proposal: p, phase: "live" });
  }
  cards.sort((a, b) => createdOf(b) - createdOf(a) || (a.proposal.id < b.proposal.id ? -1 : 1));
  return { cards, expired, vanished };
}

export const liveCount = (cards: HeldCard[]) => cards.filter((c) => c.phase === "live").length;

const ELSEWHERE: Record<string, CardPhase> = {
  confirmed: "approvedElsewhere",
  rejected: "rejectedElsewhere",
  superseded: "superseded",
  expired: "expired",
};

/** Map an Approve/Reject/Skip HTTP failure (or success) to what the card should do. */
export function mapActionResponse(status: number, detail: string): ActionOutcome {
  if (status >= 200 && status < 300) return { kind: "ok" };
  if (status === 401 || status === 403 || status === 503) {
    return { kind: "error", message: APPROVER_KEY_ACTION_MSG };
  }
  if (status === 404) {
    return { kind: "phase", phase: "vanished", message: "This proposal no longer exists." };
  }
  if (status === 409) {
    const m = /^Proposal already (confirmed|rejected|superseded|expired)/.exec(detail);
    if (m) return { kind: "phase", phase: ELSEWHERE[m[1]] };
    return { kind: "error", message: `Couldn't apply: ${LEDGER_CHANGED_MSG}` };
  }
  if (status === 410) return { kind: "phase", phase: "expired" };
  return { kind: "error", message: `Couldn't apply: ${detail}` };
}

/** Rows shown on a card: all when short or expanded, else the first five plus every flagged row. */
export function visibleRowIndices(rows: ProposalRow[], expanded: boolean): number[] {
  const all = rows.map((_, i) => i);
  if (rows.length <= 8 || expanded) return all;
  return all.filter((i) => i < 5 || (rows[i].duplicates?.length ?? 0) > 0);
}
