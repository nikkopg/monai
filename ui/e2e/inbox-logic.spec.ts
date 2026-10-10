import { test, expect } from "@playwright/test";
import { approverHeaderAllowed } from "../app/lib/approverAllowlist";
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
  type ProposalRow,
} from "../app/lib/inbox";

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
  ];
  for (const [m, p, s] of denied) {
    test(`denies ${m} ${p}${s}`.replace(U, "<uuid>"), () => {
      expect(approverHeaderAllowed(m, p, s)).toBe(false);
    });
  }
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
