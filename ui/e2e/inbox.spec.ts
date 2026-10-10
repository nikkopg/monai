import { test, expect, type Page } from "@playwright/test";
import {
  ALL_SKIPPED_MSG,
  APPROVER_KEY_ACTION_MSG,
  APPROVER_KEY_PAGE_MSG,
  LEDGER_CHANGED_MSG,
  NETWORK_FAIL_MSG,
  hhmm,
  type InboxProposal,
} from "../app/lib/inbox";
import {
  HOUR,
  MIN,
  NOW,
  chatTx,
  editProposal,
  ids,
  iso,
  mockInbox,
  proposal,
  transferProposal,
  txRow,
} from "./inbox-fixtures";

// ---------------------------------------------------------------------------
// Phase 33 plan 04 — hermetic Inbox spec (D-06). Every /api/proposals* call is
// mocked through mockInbox (counts included, RESEARCH Pitfall 5); synthetic
// values only. Request counts are never asserted absolutely (StrictMode mounts
// effects twice in `next dev`).
// ---------------------------------------------------------------------------

const live = (page: Page) => page.locator('[aria-live="polite"]');
const art = (page: Page, name: string) => page.getByRole("article", { name, exact: true });
const statusOf = (page: Page, id: string) => page.locator(`#inbox-status-${id}`);
const approveBtn = (scope: ReturnType<typeof art>) => scope.getByRole("button", { name: /^Approve/ });
const rejectBtn = (scope: ReturnType<typeof art>) =>
  scope.getByRole("button", { name: "Reject and discard" });

const T3 = "Add 3 transactions to Account A";
const flagTx = {
  kind: "transaction",
  id: 101,
  date: "2026-10-06",
  amount: "-120000.00",
  merchant: "Toko Contoh",
} as const;

/** Three rows on Account A; row 2 has a ledger flag, row 3 a proposal flag (row 2 of ids.b). */
const batch3 = (o: Partial<InboxProposal> = {}) =>
  proposal({
    payload: {
      operation: "add_transaction",
      rows: [
        txRow({ after: { notes: "Synthetic note" } }),
        txRow({
          after: { merchant: "Toko Contoh", amount: "-120000.00", category: "Groceries" },
          duplicates: [{ ...flagTx }],
        }),
        txRow({
          after: { merchant: "Gaji Contoh", amount: "250000.00" },
          duplicates: [{ kind: "proposal", id: ids.b, row: 1 }],
        }),
      ],
    },
    ...o,
  });

/** Another waiting proposal (two rows on Account B) that the batch3 proposal flag points at. */
const other = (o: Partial<InboxProposal> = {}) =>
  proposal({
    id: ids.b,
    created_at: iso(NOW - 10 * MIN),
    payload: {
      operation: "add_transaction",
      rows: [
        txRow({ after: { account: "Account B" } }),
        txRow({ after: { account: "Account B", merchant: "Toko Contoh" } }),
      ],
    },
    ...o,
  });

const oneRow = (o: Partial<InboxProposal> = {}) => proposal({ id: ids.c, ...o });

async function openInbox(page: Page) {
  await page.clock.setFixedTime(NOW);
  await page.goto("/inbox");
}

// ===========================================================================
// Task 1 — sidebar badge, list order, card rendering
// ===========================================================================

test.describe("nav badge", () => {
  const link = (page: Page, name: string) => page.getByRole("link", { name, exact: true });

  async function host(page: Page, init: Parameters<typeof mockInbox>[1]) {
    const inbox = await mockInbox(page, init);
    await page.clock.setFixedTime(NOW);
    await page.goto("/records");
    return inbox;
  }

  test("hidden at zero, links in order", async ({ page }) => {
    const inbox = await host(page, { counts: 0 });
    await expect.poll(() => inbox.hits.counts).toBeGreaterThan(0);
    await page.waitForTimeout(300);
    const texts = (await page.locator("nav a").allTextContents()).map((t) => t.trim());
    expect(texts).toEqual(["Cashflow", "Records", "Inbox", "Chat", "Investments", "Settings"]);
    await expect(link(page, "Inbox")).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveCount(0);
  });

  test("shows the digits", async ({ page }) => {
    await host(page, { counts: 3 });
    await expect(link(page, "Inbox, 3 pending")).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveText("3");
  });

  test("caps at 99+", async ({ page }) => {
    await host(page, { counts: 150 });
    await expect(link(page, "Inbox, 150 pending")).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveText("99+");
  });

  test("nothing before the first response", async ({ page }) => {
    const inbox = await host(page, { countsMode: "hang" });
    await expect.poll(() => inbox.hits.counts).toBeGreaterThan(0);
    await expect(link(page, "Inbox")).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveCount(0);
    await expect(page.getByText("—", { exact: true })).toHaveCount(0);
  });

  test("em dash after two failed counts", async ({ page }) => {
    const inbox = await mockInbox(page, { countsRaw: { pending: "3" } });
    await page.clock.install({ time: NOW });
    await page.goto("/records");
    await expect.poll(() => inbox.hits.counts).toBeGreaterThan(0);
    await page.waitForTimeout(300);
    await expect(page.locator(".nav-badge")).toHaveCount(0);
    await page.clock.runFor(60_000);
    await expect(page.locator(".nav-badge")).toHaveText("—");
    await expect(link(page, "Inbox, pending count unavailable")).toBeVisible();
  });

  test("visible on the collapsed sidebar", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("monai.sidebarCollapsed", "true"));
    await host(page, { counts: 3 });
    await expect(link(page, "Inbox, 3 pending")).toBeVisible();
    await expect(page.locator(".nav-badge")).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveText("3");
  });

  test("visible at 500 px wide", async ({ page }) => {
    await page.setViewportSize({ width: 500, height: 800 });
    await host(page, { counts: 3 });
    await expect(link(page, "Inbox, 3 pending")).toBeVisible();
    await expect(page.locator(".nav-badge")).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveText("3");
  });
});

test.describe("list order", () => {
  test("newest first across channels, id tie-break, chips outside the heading", async ({ page }) => {
    const rowsOf = (n: number, account: string) =>
      Array.from({ length: n }, () => txRow({ after: { account } }));
    const mk = (id: string, ago: number, n: number, account: string, o: Partial<InboxProposal> = {}) =>
      proposal({
        id,
        created_at: iso(NOW - ago * MIN),
        payload: { operation: "add_transaction", rows: rowsOf(n, account) },
        ...o,
      });
    const transfer = transferProposal({ id: ids.f, created_at: iso(NOW - 3 * MIN) });
    const tieC = mk(ids.c, 4, 3, "Account B");
    const tieB = mk(ids.b, 4, 1, "Account B");
    await mockInbox(page, {
      // served out of order on purpose; c before b
      list: [
        tieC,
        tieB,
        transfer,
        chatTx({
          id: ids.e,
          created_at: iso(NOW - 2 * MIN),
          payload: { operation: "add_transaction", rows: rowsOf(1, "Account A") },
        }),
        mk(ids.d, 1, 2, "Account A"),
      ],
    });
    await openInbox(page);
    await expect(page.locator("article h2")).toHaveText([
      "Add 2 transactions to Account A",
      "Add 1 transaction to Account A",
      "Add 1 transfer",
      "Add 1 transaction to Account B",
      "Add 3 transactions to Account B",
    ]);
    await expect(page.getByText("Claude", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("monai chat", { exact: true })).toBeVisible();
    const titles = await page.locator("article h2").allTextContents();
    const articles = page.locator("article");
    for (let k = 0; k < titles.length; k++) {
      await expect(articles.nth(k)).toHaveAccessibleName(titles[k]);
    }
  });
});

test.describe("badge sync", () => {
  test("the badge follows monai:inbox-count from the page", async ({ page }) => {
    const inbox = await mockInbox(page, {
      countsMode: "hang",
      list: [
        proposal({ id: ids.a }),
        proposal({
          id: ids.b,
          created_at: iso(NOW - 5 * MIN),
          payload: { operation: "add_transaction", rows: [txRow({ after: { account: "Account B" } })] },
        }),
      ],
    });
    await openInbox(page);
    const inboxLink = (n: number) => page.getByRole("link", { name: `Inbox, ${n} pending`, exact: true });
    await expect(inboxLink(2)).toBeVisible();
    await approveBtn(art(page, "Add 1 transaction to Account A")).click();
    await expect(inboxLink(1)).toBeVisible();
    expect(inbox.sent("POST", "/approve")).toHaveLength(1);
  });
});

test.describe("card rows", () => {
  test("rows table, chips, flag lines and the cross-proposal link", async ({ page }) => {
    const b = batch3();
    await mockInbox(page, { list: [b, other()] });
    await openInbox(page);
    const card = art(page, T3);
    await expect(card).toBeVisible();
    await expect(card.locator("caption")).toHaveText("Rows in this proposal");
    await expect(card.getByRole("columnheader")).toHaveText([
      "#",
      "Date",
      "Merchant",
      "Account",
      "Category",
      "Amount",
      "Skip",
    ]);
    await expect(card.getByRole("cell", { name: "7 Oct 2026" }).first()).toBeVisible();
    await expect(card.getByRole("cell", { name: "-35,000", exact: true })).toBeVisible();
    await expect(card.getByRole("cell", { name: "+250,000", exact: true })).toBeVisible();
    await expect(card.getByText("Uncategorized", { exact: true })).toHaveCount(2);
    await expect(card.getByText("Groceries", { exact: true })).toBeVisible();
    await expect(card.getByText("Synthetic note", { exact: true })).toBeVisible();
    await expect(card.getByText("Possible duplicate", { exact: true })).toHaveCount(2);
    await expect(
      card.getByText("Matches an existing record: 6 Oct 2026, -120,000, Toko Contoh")
    ).toBeVisible();
    await expect(card.getByText("Same as row 2 of another waiting proposal")).toBeVisible();
    await expect(card.getByRole("link", { name: "Go to that proposal" })).toHaveAttribute(
      "href",
      `#proposal-${ids.b}`
    );
    // Meta and status label
    await expect(card.getByText("Proposed 3 min ago")).toBeVisible();
    await expect(statusOf(page, ids.a)).toHaveText("Waiting for you · expires in 47 h");
  });

  test("proposal flag keeps the sentence but drops the link when the target is not on the page", async ({
    page,
  }) => {
    await mockInbox(page, { list: [batch3()] });
    await openInbox(page);
    const card = art(page, T3);
    await expect(card.getByText("Same as row 2 of another waiting proposal")).toBeVisible();
    await expect(card.getByRole("link", { name: "Go to that proposal" })).toHaveCount(0);
  });

  test("a long batch shows five rows plus flagged ones and expands", async ({ page }) => {
    const rows = Array.from({ length: 12 }, (_, i) =>
      txRow({
        after: { merchant: `Toko Contoh ${i + 1}` },
        duplicates: i === 9 ? [{ ...flagTx }] : [],
      })
    );
    await mockInbox(page, {
      list: [proposal({ payload: { operation: "add_transaction", rows } })],
    });
    await openInbox(page);
    const card = art(page, "Add 12 transactions to Account A");
    await expect(card.locator(".inbox-c-num")).toHaveText(["1", "2", "3", "4", "5", "10"]);
    await expect(card.getByText("6 rows hidden")).toBeVisible();
    const more = card.getByRole("button", { name: "Show all 12 rows" });
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await expect(more).toHaveAttribute("aria-controls", `inbox-rows-${ids.a}`);
    await more.click();
    await expect(card.locator(".inbox-row")).toHaveCount(12);
    const fewer = card.getByRole("button", { name: "Show fewer rows" });
    await expect(fewer).toHaveAttribute("aria-expanded", "true");
    await expect(fewer).toBeFocused();
    await expect(card.getByText("rows hidden")).toHaveCount(0);
  });

  test("transfer line, no Skip, effect-named Approve", async ({ page }) => {
    await mockInbox(page, { list: [transferProposal()] });
    await openInbox(page);
    const card = art(page, "Add 1 transfer");
    await expect(
      card.getByText("Transfer 50,000 from Account A to Account B on 7 Oct 2026")
    ).toBeVisible();
    await expect(card.getByRole("button", { name: /^Skip/ })).toHaveCount(0);
    await expect(card.getByRole("button", { name: "Approve: Add 1 transfer" })).toBeVisible();
  });

  test("edit proposal renders the shared before-to-after diff", async ({ page }) => {
    await mockInbox(page, { list: [editProposal()] });
    await openInbox(page);
    const card = art(page, "Edit 1 transaction");
    await expect(card.getByRole("button", { name: "Approve: Edit 1 transaction" })).toBeVisible();
    // ProposalDiff marks a changed field as old (removed tone) -> new (added tone); only the
    // changed key is listed, and no Skip control exists on a non-add_transaction card.
    const row = card.getByText("merchant:").locator("..");
    await expect(row).toHaveText("merchant: Kopi Contoh → Warung Contoh");
    const colour = (t: string) =>
      row.getByText(t, { exact: true }).evaluate((el) => getComputedStyle(el).color);
    expect(await colour("Kopi Contoh")).not.toBe(await colour("Warung Contoh"));
    await expect(card.getByText("amount:")).toHaveCount(0);
    await expect(card.getByRole("button", { name: /^Skip/ })).toHaveCount(0);
  });

  test("backend text renders as text, never markup", async ({ page }) => {
    const evil = "<img src=x onerror=alert(1)>";
    await mockInbox(page, {
      list: [proposal({ payload: { operation: "add_transaction", rows: [txRow({ after: { merchant: evil } })] } })],
    });
    await openInbox(page);
    const card = art(page, "Add 1 transaction to Account A");
    await expect(card.getByText(evil, { exact: true })).toBeVisible();
    await expect(card.locator("img")).toHaveCount(0);
  });
});

test.describe("code chip", () => {
  const CODE = "K7Q2MX";
  const mixed = () => [
    proposal({ id: ids.a }),
    chatTx({
      id: ids.b,
      created_at: iso(NOW - 6 * MIN),
      payload: { operation: "add_transaction", rows: [txRow({ after: { account: "Account B" } })] },
    }),
  ];

  test("shows one code on the MCP card only and copies it", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await mockInbox(page, { list: mixed() });
    await openInbox(page);
    const code = page.getByRole("code");
    await expect(code).toHaveCount(1);
    await expect(code).toHaveText(/^[0-9A-HJKMNP-TV-Z]{6}$/);
    await expect(art(page, "Add 1 transaction to Account B").getByRole("code")).toHaveCount(0);
    await expect(
      page.getByText("Tell Claude this code to approve it there. You don't need it to approve here.")
    ).toBeVisible();

    const copy = page.getByRole("button", { name: "Copy confirm code" });
    await expect(copy).toHaveText("Copy code");
    await copy.click();
    await expect(copy).toHaveText("Copied");
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(CODE);
    await expect(live(page)).toHaveText("Code copied");
    await expect(copy).toHaveText("Copy code", { timeout: 5_000 });
  });

  test("the code appears nowhere but the code element", async ({ page }) => {
    await mockInbox(page, { list: mixed() });
    await openInbox(page);
    await expect(page.getByRole("code")).toHaveText(CODE);
    const leaks = await page.evaluate((code) => {
      const found: string[] = [];
      document.querySelectorAll("*").forEach((el) => {
        for (const a of Array.from(el.attributes)) {
          if (a.value.includes(code)) found.push(`${el.tagName}[${a.name}]`);
        }
      });
      const stores = [localStorage, sessionStorage];
      for (const s of stores) {
        for (let k = 0; k < s.length; k++) {
          const key = s.key(k) as string;
          if (key.includes(code) || (s.getItem(key) ?? "").includes(code)) found.push(`storage:${key}`);
        }
      }
      return found;
    }, CODE);
    expect(leaks).toEqual([]);
    expect(page.url()).not.toContain(CODE);
  });

  test("a rejected clipboard write falls back to select-and-copy", async ({ page }) => {
    await page.addInitScript(() => {
      if (navigator.clipboard) {
        navigator.clipboard.writeText = () => Promise.reject(new Error("denied"));
      }
    });
    await mockInbox(page, { list: mixed() });
    await openInbox(page);
    const copy = page.getByRole("button", { name: "Copy confirm code" });
    await copy.click();
    await expect(page.getByText("Select the code and press Ctrl+C")).toBeVisible();
    await expect(page.getByRole("code")).toBeFocused();
    await expect(copy).toHaveText("Copy code");
  });
});

test.describe("locked", () => {
  test("five wrong codes lock Claude out but the owner can still approve", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [proposal({ failed_attempts: 5 })] });
    await openInbox(page);
    await expect(statusOf(page, ids.a)).toHaveText("Locked after 5 wrong codes · approve here");
    await expect(
      page.getByText("Claude can no longer approve this with the code. You still can.")
    ).toBeVisible();
    const approve = approveBtn(art(page, "Add 1 transaction to Account A"));
    await expect(approve).not.toHaveAttribute("aria-disabled", "true");
    await approve.click();
    await expect.poll(() => inbox.sent("POST", "/approve").length).toBe(1);
  });
});
