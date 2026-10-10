import { test, expect } from "@playwright/test";
import { approverHeaderAllowed, buildForwardHeaders } from "../app/lib/approverAllowlist";
import {
  approveLabel,
  cardTitle,
  approvedFooter,
  relativeAge,
  expirySentence,
  pendingStatus,
  fmtRowDate,
  fmtSigned,
  fmtUnsigned,
  hhmm,
  badgeText,
  navInboxLabel,
  duplicateChipText,
  transactionFlagText,
  proposalFlagText,
  skipAriaLabel,
  isLocked,
  isUuid,
  isPendingCount,
  parsePendingCount,
  serverOffset,
  mergeSkip,
  mergePoll,
  liveCount,
  mapActionResponse,
  visibleRowIndices,
  APPROVER_KEY_ACTION_MSG,
  LEDGER_CHANGED_MSG,
  ALL_SKIPPED_MSG,
  type ProposalRow,
  type InboxProposal,
  type HeldCard,
  type DuplicateFlag,
} from "../app/lib/inbox";
import { tokens } from "../app/styles";

// ---------------------------------------------------------------------------
// Phase 33 Plan 01 — non-browser logic spec (D-05): pure modules only, no page
// fixture. Synthetic values throughout.
// ---------------------------------------------------------------------------

const U = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01";
const UPPER = U.toUpperCase();

test.describe("allowlist", () => {
  const allowed: [string, string, string][] = [
    ["GET", "proposals", ""],
    ["GET", "proposals", "?status=pending"],
    ["POST", `proposals/${U}/approve`, ""],
    ["POST", `proposals/${U}/reject`, ""],
    ["PATCH", `proposals/${U}/rows/0`, ""],
    ["PATCH", `proposals/${U}/rows/123456`, ""],
    ["post", `proposals/${U}/approve`, ""],
    ["POST", `proposals/${UPPER}/approve`, ""],
  ];
  for (const [m, p, s] of allowed) {
    test(`allows ${m} ${p}${s}`.replace(U, "<uuid>"), () => {
      expect(approverHeaderAllowed(m, p, s)).toBe(true);
    });
  }

  const denied: [string, string, string][] = [
    ["GET", "proposals/counts", ""],
    ["POST", `proposals/${U}/confirm`, ""],
    ["GET", "proposals", "?status=expired"],
    ["GET", "proposals", "?status=pending&x=1"],
    ["GET", "proposals", "?x=1"],
    ["GET", `proposals/${U}/approve`, ""],
    ["DELETE", `proposals/${U}`, ""],
    ["POST", `proposals/${U}/approve/`, ""],
    ["POST", `proposals/${U}/approve`, "?x=1"],
    ["POST", "proposals/abc/approve", ""],
    ["POST", `proposals/../proposals/${U}/approve`, ""],
    ["PATCH", `proposals/${U}/rows/abc`, ""],
    ["PATCH", `proposals/${U}/rows/1234567`, ""],
    ["HEAD", "proposals", ""],
    ["POST", `PROPOSALS/${U}/approve`, ""],
    ["GET", "transactions", ""],
    ["POST", `proposals/${U}/approve\n`, ""],
    ["POST", `proposals/${U}/approve%0a`, ""],
    ["POST", `proposals%2F${U}%2Fapprove`, ""],
    ["POST", `proposals/${U}/approve%2e`, ""],
    ["POST", `proposals/%2e%2e/proposals/${U}/approve`, ""],
    ["PATCH", `proposals/${U}/rows/\uFF11`, ""],
  ];
  for (const [m, p, s] of denied) {
    test(`denies ${JSON.stringify(m + " " + p + s).replace(U, "<uuid>")}`, () => {
      expect(approverHeaderAllowed(m, p, s)).toBe(false);
    });
  }
});

test.describe("forward headers", () => {
  const FORGED = "forged-approver-synthetic";
  const SERVER = "server-approver-synthetic";
  const incoming = () =>
    new Headers({
      host: "127.0.0.1:3001",
      MONAI_APPROVER_KEY: FORGED,
      MONAI_API_KEY: "client-api-synthetic",
      accept: "application/json",
    });
  const approve = ["POST", `proposals/${U}/approve`, ""] as const;

  test("forged header on an allowlisted path with the server key unset reaches the backend as absent", () => {
    const h = buildForwardHeaders(incoming(), "api-synthetic", "", ...approve);
    expect(h.has("MONAI_APPROVER_KEY")).toBe(false);
  });
  test("forged header on an allowlisted path is replaced by the server key, never concatenated", () => {
    const h = buildForwardHeaders(incoming(), "api-synthetic", SERVER, ...approve);
    expect(h.get("MONAI_APPROVER_KEY")).toBe(SERVER);
  });
  test("forged header on a denied path is stripped", () => {
    const h = buildForwardHeaders(incoming(), "api-synthetic", SERVER, "POST", `proposals/${U}/confirm`, "");
    expect(h.has("MONAI_APPROVER_KEY")).toBe(false);
  });
  test("API key is always the server's, host is dropped, other headers pass through", () => {
    const h = buildForwardHeaders(incoming(), "api-synthetic", "", "GET", "transactions", "");
    expect(h.get("MONAI_API_KEY")).toBe("api-synthetic");
    expect(h.has("host")).toBe(false);
    expect(h.get("accept")).toBe("application/json");
  });
});

// ---------------------------------------------------------------------------
// Display helpers (Task 2)
// ---------------------------------------------------------------------------

const BASE = Date.parse("2026-10-09T04:00:00Z");
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

const rowsOf = (n: number, skipped = 0, account = "Account A"): ProposalRow[] =>
  Array.from({ length: n }, (_, i) => ({
    after: { account, merchant: "Kopi Contoh", amount: "-35000.00", date: "2026-10-07" },
    ...(i < skipped ? { skip: true } : {}),
  }));

test.describe("approve label", () => {
  test("add_transaction counts included rows and the skip clause", () => {
    expect(approveLabel("add_transaction", rowsOf(14, 2))).toBe("Add 12 transactions, 2 skipped");
    expect(approveLabel("add_transaction", rowsOf(1))).toBe("Add 1 transaction");
    expect(approveLabel("add_transaction", rowsOf(12))).toBe("Add 12 transactions");
  });
  test("counted and fixed operations", () => {
    expect(approveLabel("add_transfer", rowsOf(1))).toBe("Add 1 transfer");
    expect(approveLabel("edit_transaction", rowsOf(1))).toBe("Edit 1 transaction");
    expect(approveLabel("edit_transaction", rowsOf(3))).toBe("Edit 3 transactions");
    expect(approveLabel("delete_transaction", rowsOf(2))).toBe("Delete 2 transactions");
    for (const [op, label] of [
      ["add_account", "Add account"],
      ["edit_account", "Edit account"],
      ["delete_account", "Delete account"],
      ["rename_category", "Rename category"],
      ["merge_category", "Merge category"],
      ["add_holding", "Add holding"],
      ["edit_holding", "Edit holding"],
      ["delete_holding", "Delete holding"],
      ["add_investment_transfer", "Move cash to investments"],
      ["add_funded_buy", "Record funded buy"],
      ["add_funded_sell", "Record funded sell"],
      ["add_balance_adjustment", "Adjust balance"],
      ["frobnicate_thing", "Apply this change"],
    ]) {
      expect(approveLabel(op, [])).toBe(label);
    }
  });
});

test.describe("card title", () => {
  test("account suffix variants", () => {
    expect(cardTitle("add_transaction", rowsOf(12))).toBe("Add 12 transactions to Account A");
    const two = [...rowsOf(1, 0, "Account A"), ...rowsOf(1, 0, "Account B")];
    expect(cardTitle("add_transaction", two)).toBe("Add 2 transactions to Account A and Account B");
    const three = [...two, ...rowsOf(1, 0, "Account C")];
    expect(cardTitle("add_transaction", three)).toBe(
      "Add 3 transactions to Account A, Account B and Account C"
    );
    const five = [...three, ...rowsOf(1, 0, "Account D"), ...rowsOf(1, 0, "Account E")];
    expect(cardTitle("add_transaction", five)).toBe(
      "Add 5 transactions to Account A, Account B, Account C and 2 more"
    );
  });
  test("skipped rows reduce the count but add no clause", () => {
    expect(cardTitle("add_transaction", rowsOf(14, 2))).toBe("Add 12 transactions to Account A");
  });
  test("transfer and unknown operation", () => {
    expect(cardTitle("add_transfer", [{ after: {} }])).toBe("Add 1 transfer");
    expect(cardTitle("frobnicate_thing", [])).toBe("frobnicate thing");
  });
  test("approved footer", () => {
    expect(approvedFooter("add_transaction", rowsOf(12, 2))).toBe("10 added, 2 skipped");
    expect(approvedFooter("add_transaction", rowsOf(3))).toBe("3 added");
    expect(approvedFooter("delete_account", [])).toBe("Applied.");
  });
});

test.describe("relative time", () => {
  test("fixed formats", () => {
    expect(relativeAge(BASE - 30_000, BASE)).toBe("just now");
    expect(relativeAge(BASE - 3 * MIN, BASE)).toBe("3 min ago");
    expect(relativeAge(BASE - 59 * MIN, BASE)).toBe("59 min ago");
    expect(relativeAge(BASE - 5 * HOUR, BASE)).toBe("5 h ago");
    expect(relativeAge(BASE - 25 * HOUR, BASE)).toBe("1 day ago");
    expect(relativeAge(BASE - 2 * DAY, BASE)).toBe("2 days ago");
    expect(relativeAge(BASE - 7 * DAY, BASE)).toBe("7 days ago");
  });
  test("older than a week shows the local date", () => {
    const created = BASE - 8 * DAY;
    const expected = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(
      new Date(created)
    );
    expect(relativeAge(created, BASE)).toBe(expected);
  });
});

test.describe("expiry", () => {
  test("sentences", () => {
    expect(expirySentence(BASE + 47 * HOUR + 5 * MIN, BASE)).toBe("expires in 47 h");
    expect(expirySentence(BASE + 12 * MIN + 10_000, BASE)).toBe("expires in 12 min");
    expect(expirySentence(BASE + 30_000, BASE)).toBe("expires in under a minute");
    expect(expirySentence(BASE, BASE)).toBeNull();
    expect(expirySentence(BASE - 1000, BASE)).toBeNull();
  });
  test("pending status", () => {
    expect(pendingStatus(BASE + 47 * HOUR, BASE)).toBe("Waiting for you · expires in 47 h");
    expect(pendingStatus(BASE - 1, BASE)).toBe("Expired · ask again to redo this");
  });
});

test.describe("format", () => {
  test("row date", () => {
    expect(fmtRowDate("2026-10-07")).toBe("7 Oct 2026");
    expect(fmtRowDate("2026-10-07T10:00:00")).toBe("7 Oct 2026");
    expect(fmtRowDate("yesterday")).toBe("yesterday");
    expect(fmtRowDate(null)).toBe("—");
  });
  test("amounts", () => {
    expect(fmtSigned("-35000.00")).toBe("-35,000");
    expect(fmtSigned("250000.00")).toBe("+250,000");
    expect(fmtSigned("abc")).toBe("abc");
    expect(fmtUnsigned("-50000.00")).toBe("50,000");
  });
});

test.describe("badge", () => {
  test("badge text", () => {
    expect(badgeText(null, false)).toBeNull();
    expect(badgeText(0, false)).toBeNull();
    expect(badgeText(3, false)).toBe("3");
    expect(badgeText(99, false)).toBe("99");
    expect(badgeText(100, false)).toBe("99+");
    expect(badgeText(3, true)).toBe("—");
    expect(badgeText(null, true)).toBe("—");
  });
  test("nav label", () => {
    expect(navInboxLabel(0, false)).toBe("Inbox");
    expect(navInboxLabel(null, false)).toBe("Inbox");
    expect(navInboxLabel(1, false)).toBe("Inbox, 1 pending");
    expect(navInboxLabel(3, false)).toBe("Inbox, 3 pending");
    expect(navInboxLabel(3, true)).toBe("Inbox, pending count unavailable");
    expect(navInboxLabel(null, true)).toBe("Inbox, pending count unavailable");
  });
});

test.describe("flags", () => {
  test("chip and flag text", () => {
    expect(duplicateChipText(1)).toBe("Possible duplicate");
    expect(duplicateChipText(2)).toBe("2 possible duplicates");
    const flag = { kind: "transaction", id: 1, date: "2026-09-12", amount: "-35000.00", merchant: "Kopi Contoh" } as const;
    // Same Intl call as production: current ICU renders September as "Sept" in en-GB.
    const d12 = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(
      new Date(2026, 8, 12)
    );
    expect(transactionFlagText(flag)).toBe(`Matches an existing record: ${d12}, -35,000, Kopi Contoh`);
    expect(transactionFlagText({ ...flag, merchant: null })).toBe(
      `Matches an existing record: ${d12}, -35,000, no merchant`
    );
    expect(proposalFlagText({ kind: "proposal", id: U, row: 3 })).toBe(
      "Same as row 4 of another waiting proposal"
    );
  });
  test("skip aria label", () => {
    const row = rowsOf(1)[0];
    expect(skipAriaLabel(2, row)).toBe("Skip row 3: Kopi Contoh, -35,000");
    expect(skipAriaLabel(2, { ...row, skip: true })).toBe("Include row 3: Kopi Contoh, -35,000");
    expect(skipAriaLabel(2, { after: { amount: "-35000.00" } })).toBe(
      "Skip row 3: no merchant, -35,000"
    );
  });
  test("locked", () => {
    expect(isLocked({ channel: "mcp", failed_attempts: 5 })).toBe(true);
    expect(isLocked({ channel: "mcp", failed_attempts: 4 })).toBe(false);
    expect(isLocked({ channel: "chat", failed_attempts: 9 })).toBe(false);
  });
  test("hhmm is 24 h local", () => {
    const expected = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(BASE));
    expect(hhmm(BASE)).toBe(expected);
    expect(hhmm(BASE)).toMatch(/^\d{2}:\d{2}$/);
  });
});

// ---------------------------------------------------------------------------
// Merge, mapping, windowing, guards, contrast (Task 3)
// ---------------------------------------------------------------------------

const prop = (id: string, createdMs: number, expiresMs = BASE + 40 * HOUR): InboxProposal => ({
  id,
  operation: "add_transaction",
  payload: { rows: rowsOf(2) },
  status: "pending",
  expires_at: new Date(expiresMs).toISOString(),
  created_at: new Date(createdMs).toISOString(),
  confirmed_at: null,
  channel: "mcp",
  supersedes_id: null,
  failed_attempts: 0,
});
const live = (p: InboxProposal): HeldCard => ({ proposal: p, phase: "live" });
const noBusy: ReadonlySet<string> = new Set();

test.describe("skip merge", () => {
  test("copies only skip and keeps held duplicates", () => {
    const dup: DuplicateFlag = { kind: "proposal", id: U, row: 0 };
    const held: ProposalRow[] = [{ after: { merchant: "A" }, duplicates: [dup] }, { after: { merchant: "B" } }];
    const resp: ProposalRow[] = [{ after: { merchant: "CHANGED" }, skip: true }];
    const out = mergeSkip(held, resp);
    expect(out[0].skip).toBe(true);
    expect(out[0].duplicates).toEqual([dup]);
    expect(out[0].after).toEqual({ merchant: "A" });
    expect(out[1]).toBe(held[1]);
  });
});

test.describe("poll merge", () => {
  const a = prop("a", BASE - 3 * HOUR);
  const b = prop("b", BASE - 2 * HOUR);
  const c = prop("c", BASE - 1 * HOUR);

  test("new server proposals appear live, newest first", () => {
    const out = mergePoll([], [a, b, c], noBusy, BASE);
    expect(out.cards.map((x) => x.proposal.id)).toEqual(["c", "b", "a"]);
    expect(out.cards.every((x) => x.phase === "live")).toBe(true);
    expect(liveCount(out.cards)).toBe(3);
  });
  test("a live card takes the fresh server proposal", () => {
    const fresh = { ...a, payload: { rows: rowsOf(3) } };
    const out = mergePoll([live(a)], [fresh], noBusy, BASE);
    expect(out.cards[0].proposal).toBe(fresh);
  });
  test("busy cards and settled cards are untouched", () => {
    const held: HeldCard[] = [live(a), { proposal: b, phase: "approved", settledAt: BASE }];
    const out = mergePoll(held, [{ ...a, failed_attempts: 2 }, { ...b, failed_attempts: 2 }], new Set(["a"]), BASE);
    expect(out.cards.find((x) => x.proposal.id === "a")).toBe(held[0]);
    expect(out.cards.find((x) => x.proposal.id === "b")).toBe(held[1]);
    const gone = mergePoll(held, [], new Set(["a"]), BASE);
    expect(gone.cards).toHaveLength(2);
    expect(gone.vanished + gone.expired).toBe(0);
  });
  test("a live card missing from the server vanishes before expiry, expires after", () => {
    const early = mergePoll([live(a)], [], noBusy, BASE);
    expect(early.cards[0].phase).toBe("vanished");
    expect(early.vanished).toBe(1);
    expect(early.expired).toBe(0);
    const late = mergePoll([live(a)], [], noBusy, BASE + 41 * HOUR);
    expect(late.cards[0].phase).toBe("expired");
    expect(late.expired).toBe(1);
    expect(late.vanished).toBe(0);
  });
  test("ties break by id ascending", () => {
    const x = prop("x", BASE);
    const y = prop("y", BASE);
    expect(mergePoll([], [y, x], noBusy, BASE).cards.map((k) => k.proposal.id)).toEqual(["x", "y"]);
  });
});

test.describe("action mapping", () => {
  test("success", () => {
    expect(mapActionResponse(200, "")).toEqual({ kind: "ok" });
    expect(mapActionResponse(201, "")).toEqual({ kind: "ok" });
  });
  test("approver-key statuses", () => {
    for (const s of [401, 403, 503]) {
      expect(mapActionResponse(s, "whatever")).toEqual({ kind: "error", message: APPROVER_KEY_ACTION_MSG });
    }
    expect(APPROVER_KEY_ACTION_MSG).toBe(
      "Approvals aren't set up — the web server is missing a valid approver key."
    );
  });
  test("404, 409, 410", () => {
    expect(mapActionResponse(404, "x")).toEqual({
      kind: "phase",
      phase: "vanished",
      message: "This proposal no longer exists.",
    });
    expect(mapActionResponse(409, "Proposal already confirmed")).toEqual({ kind: "phase", phase: "approvedElsewhere" });
    expect(mapActionResponse(409, "Proposal already rejected")).toEqual({ kind: "phase", phase: "rejectedElsewhere" });
    expect(mapActionResponse(409, "Proposal already superseded")).toEqual({ kind: "phase", phase: "superseded" });
    expect(mapActionResponse(409, "Proposal already expired")).toEqual({ kind: "phase", phase: "expired" });
    expect(mapActionResponse(409, "something else")).toEqual({
      kind: "error",
      message: "Couldn't apply: " + LEDGER_CHANGED_MSG,
    });
    expect(mapActionResponse(410, "gone")).toEqual({ kind: "phase", phase: "expired" });
  });
  test("422 and 500 carry the server detail", () => {
    expect(mapActionResponse(422, ALL_SKIPPED_MSG)).toEqual({
      kind: "error",
      message: "Couldn't apply: Every row is skipped — reject this proposal instead",
    });
    expect(mapActionResponse(500, "boom")).toEqual({ kind: "error", message: "Couldn't apply: boom" });
  });
});

test.describe("windowing", () => {
  const mk = (n: number, flagged: number[] = []): ProposalRow[] =>
    rowsOf(n).map((r, i) =>
      flagged.includes(i) ? { ...r, duplicates: [{ kind: "proposal", id: U, row: 0 } as DuplicateFlag] } : r
    );
  test("short or expanded shows everything", () => {
    expect(visibleRowIndices(mk(8), false)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(visibleRowIndices(mk(12), true)).toHaveLength(12);
  });
  test("long collapsed shows first five plus flagged rows", () => {
    expect(visibleRowIndices(mk(12, [9]), false)).toEqual([0, 1, 2, 3, 4, 9]);
    expect(visibleRowIndices(mk(12, [1, 10]), false)).toEqual([0, 1, 2, 3, 4, 10]);
  });
});

test.describe("guards", () => {
  test("isUuid", () => {
    expect(isUuid(U)).toBe(true);
    expect(isUuid(UPPER)).toBe(true);
    expect(isUuid("abc")).toBe(false);
    expect(isUuid("")).toBe(false);
    expect(isUuid(U + "x")).toBe(false);
  });
  test("pending count", () => {
    expect(isPendingCount(0)).toBe(true);
    expect(isPendingCount(7)).toBe(true);
    for (const bad of [-1, 1.5, NaN, "3", null]) expect(isPendingCount(bad)).toBe(false);
    expect(parsePendingCount({ pending: 4 })).toBe(4);
    expect(parsePendingCount({ pending: "4" })).toBeNull();
    expect(parsePendingCount([])).toBeNull();
    expect(parsePendingCount(null)).toBeNull();
  });
  test("serverOffset", () => {
    expect(serverOffset("Fri, 09 Oct 2026 06:00:00 GMT", BASE)).toBe(2 * HOUR);
    expect(serverOffset(null, BASE)).toBe(0);
    expect(serverOffset("not a date", BASE)).toBe(0);
  });
});

test.describe("contrast", () => {
  // WCAG relative luminance; test-only (axe substitute, D-07).
  const full = (hex: string) =>
    hex.length === 4 ? "#" + [1, 2, 3].map((i) => hex[i] + hex[i]).join("") : hex;
  const lum = (hex: string) => {
    const h = full(hex);
    const [r, g, b] = [1, 3, 5]
      .map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: string, b: string) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const c = tokens.color;
  const text: [string, string, string][] = [
    ["ink", c.ink, c.card], ["ink", c.ink, c.panel], ["ink", c.ink, c.tintWarm], ["ink", c.ink, c.tintNeutral],
    ["muted3", c.muted3, c.card], ["muted3", c.muted3, c.panel], ["muted3", c.muted3, c.inputBg],
    ["muted3", c.muted3, c.tintNeutral], ["muted3", c.muted3, c.sidebar],
    ["green", c.green, c.card], ["green", c.green, c.panel],
    ["#fff", "#fff", c.green], ["#fff", "#fff", c.terracotta],
    ["terracotta", c.terracotta, c.card], ["terracotta", c.terracotta, c.panel],
  ];
  for (const [name, fg, bg] of text) {
    test(`${name} ${fg} on ${bg} >= 4.5`, () => {
      expect(ratio(fg, bg)).toBeGreaterThanOrEqual(4.5);
    });
  }
  test("green focus ring >= 3 on panel and card", () => {
    expect(ratio(c.green, c.panel)).toBeGreaterThanOrEqual(3);
    expect(ratio(c.green, c.card)).toBeGreaterThanOrEqual(3);
  });
  test("terracotta on tintWarm fails (why the UI-SPEC bans it)", () => {
    expect(ratio(c.terracotta, c.tintWarm)).toBeLessThan(4.5);
  });
});
