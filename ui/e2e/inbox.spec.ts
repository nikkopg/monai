import { test, expect, type Page } from "@playwright/test";
import {
  ALL_SKIPPED_MSG,
  APPROVER_KEY_ACTION_MSG,
  APPROVER_KEY_PAGE_MSG,
  LEDGER_CHANGED_MSG,
  NETWORK_FAIL_MSG,
  hhmm,
  type InboxProposal,
  type ProposalRow,
} from "../app/lib/inbox";
import {
  MIN,
  NOW,
  balanceAdjustmentProposal,
  chatTx,
  editProposal,
  ids,
  investmentTransferProposal,
  iso,
  mockInbox,
  proposal,
  transferProposal,
  txRow,
  type InboxMock,
  type Responder,
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

  test("balance adjustment line, no Skip, effect-named Approve", async ({ page }) => {
    await mockInbox(page, { list: [balanceAdjustmentProposal()] });
    await openInbox(page);
    const card = art(page, "Adjust balance");
    await expect(card.getByText("Set account #3 balance to -250,000")).toBeVisible();
    await expect(card.getByRole("button", { name: /^Skip/ })).toHaveCount(0);
    await expect(card.getByRole("button", { name: "Approve: Adjust balance" })).toBeVisible();
    await expect(card).not.toContainText("[object Object]");
  });

  test("investment transfer line with notes, never an object dump", async ({ page }) => {
    await mockInbox(page, { list: [investmentTransferProposal()] });
    await openInbox(page);
    const card = art(page, "Move cash to investments");
    await expect(
      card.getByText("Move 500,000 IDR from Account A to platform #2 on 7 Oct 2026")
    ).toBeVisible();
    await expect(card.getByText("Setoran contoh")).toBeVisible();
    await expect(card.getByRole("button", { name: /^Skip/ })).toHaveCount(0);
    await expect(
      card.getByRole("button", { name: "Approve: Move cash to investments" })
    ).toBeVisible();
    await expect(card).not.toContainText("[object Object]");
  });

  test("an unknown row shape falls back to key: value lines", async ({ page }) => {
    await mockInbox(page, {
      list: [
        chatTx({
          id: ids.f,
          operation: "add_future_thing",
          payload: {
            operation: "add_future_thing",
            rows: [{ widget: "Contoh", nested: { a: 1 } } as unknown as ProposalRow],
          },
        }),
      ],
    });
    await openInbox(page);
    const card = art(page, "add future thing");
    await expect(card).toContainText("widget: Contoh");
    await expect(card).toContainText('nested: {"a":1}');
    await expect(card).not.toContainText("[object Object]");
    await expect(card.getByRole("button", { name: "Approve: Apply this change" })).toBeVisible();
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

// ===========================================================================
// Task 2 — actions, label recompute, discard, State Matrix
// ===========================================================================

/** Collects every value the live region ever held (a later poll may overwrite the last one). */
async function liveLog(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __live: string[] };
    w.__live = [];
    new MutationObserver(() => {
      const t = document.querySelector('[aria-live="polite"]')?.textContent ?? "";
      if (t && w.__live[w.__live.length - 1] !== t) w.__live.push(t);
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
}
const heard = (page: Page) =>
  page.evaluate(() => (window as unknown as { __live: string[] }).__live);

/** After a `clock.install`, stop time once data is on screen so later runFor steps are exact. */
async function freeze(page: Page) {
  await page.clock.pauseAt((await page.evaluate(() => Date.now())) + 100);
}

const byId = (page: Page, id: string) => page.locator(`#proposal-${id}`);

/** Three plain rows on Account A (no duplicate flags). */
const plain3 = (o: Partial<InboxProposal> = {}) =>
  proposal({
    payload: {
      operation: "add_transaction",
      rows: [
        txRow(),
        txRow({ after: { merchant: "Toko Contoh", amount: "-120000.00" } }),
        txRow({ after: { merchant: "Gaji Contoh", amount: "250000.00" } }),
      ],
    },
    ...o,
  });

test.describe("approve label", () => {
  test("skip and include recompute the Approve label", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [batch3()] });
    await openInbox(page);
    const card = byId(page, ids.a);
    await expect(approveBtn(card)).toHaveAccessibleName("Approve: Add 3 transactions");

    await card.getByRole("button", { name: "Skip row 2: Toko Contoh, -120,000" }).click();
    await expect(approveBtn(card)).toHaveAccessibleName("Approve: Add 2 transactions, 1 skipped");
    const sent = inbox.sent("PATCH", "/rows/1");
    expect(sent).toHaveLength(1);
    expect(sent[0].body).toEqual({ skip: true });
    expect(new URL(sent[0].url).pathname).toBe(`/api/proposals/${ids.a}/rows/1`);

    const row = card.locator(".inbox-row").nth(1);
    await expect(row.getByText("Skipped", { exact: true })).toBeVisible();
    await expect
      .poll(() =>
        row.getByText("Toko Contoh", { exact: true }).evaluate((el) => getComputedStyle(el).textDecorationLine)
      )
      .toContain("line-through");
    const include = card.getByRole("button", { name: "Include row 2: Toko Contoh, -120,000" });
    await expect(include).toBeFocused();
    await expect(live(page)).toHaveText("Row 2 skipped. Approve will add 2 transactions, 1 skipped");

    await include.click();
    await expect(approveBtn(card)).toHaveAccessibleName("Approve: Add 3 transactions");
    await expect(live(page)).toHaveText("Row 2 included. Approve will add 3 transactions");
  });

  test("singular wording", async ({ page }) => {
    await mockInbox(page, {
      list: [proposal({ payload: { operation: "add_transaction", rows: [txRow(), txRow()] } })],
    });
    await openInbox(page);
    const card = byId(page, ids.a);
    await card.getByRole("button", { name: "Skip row 1: Kopi Contoh, -35,000" }).click();
    await expect(approveBtn(card)).toHaveAccessibleName("Approve: Add 1 transaction, 1 skipped");
  });

  test("all rows skipped blocks Approve", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [oneRow()] });
    await openInbox(page);
    const card = byId(page, ids.c);
    await card.getByRole("button", { name: "Skip row 1: Kopi Contoh, -35,000" }).click();
    const approve = approveBtn(card);
    await expect(approve).toContainText("Nothing left to add");
    await expect(approve).toHaveAttribute("aria-disabled", "true");
    await expect(approve).toHaveAttribute("aria-describedby", `inbox-allskipped-${ids.c}`);
    await expect(page.locator(`#inbox-allskipped-${ids.c}`)).toContainText(ALL_SKIPPED_MSG);
    await expect(live(page)).toHaveText(`Row 1 skipped. ${ALL_SKIPPED_MSG}`);
    await approve.click({ force: true });
    await page.waitForTimeout(300);
    expect(inbox.sent("POST", "/approve")).toHaveLength(0);
  });

  test("a server 422 is shown verbatim", async ({ page }) => {
    await mockInbox(page, {
      list: [oneRow()],
      respond: { approve: { status: 422, detail: ALL_SKIPPED_MSG } },
    });
    await openInbox(page);
    const card = byId(page, ids.c);
    await approveBtn(card).click();
    await expect(card.getByRole("alert")).toContainText(ALL_SKIPPED_MSG);
  });
});

test.describe("skip merge", () => {
  test("a skip keeps the duplicate chip although the PATCH response has none", async ({ page }) => {
    await mockInbox(page, { list: [batch3(), other()] });
    await openInbox(page);
    const card = byId(page, ids.a);
    await expect(card.getByText("Possible duplicate", { exact: true })).toHaveCount(2);
    await card.getByRole("button", { name: "Skip row 2: Toko Contoh, -120,000" }).click();
    await expect(card.getByRole("button", { name: "Include row 2: Toko Contoh, -120,000" })).toBeVisible();
    await expect(card.getByText("Possible duplicate", { exact: true })).toHaveCount(2);
    await expect(
      card.getByText("Matches an existing record: 6 Oct 2026, -120,000, Toko Contoh")
    ).toBeVisible();
  });
});

test.describe("approve", () => {
  test("applies, settles, focuses the status and announces", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [plain3(), other()] });
    await openInbox(page);
    const card = byId(page, ids.a);
    await expect(page.getByText(/2 waiting\./)).toBeVisible();
    const release = inbox.hold("approve");
    await approveBtn(card).click();
    await expect(statusOf(page, ids.a)).toHaveText("Applying…");
    await expect(approveBtn(card)).toContainText("…");
    await expect(rejectBtn(card)).toHaveAttribute("aria-disabled", "true");
    release();
    await expect(statusOf(page, ids.a)).toHaveText("✓ Approved · " + hhmm(NOW));
    await expect(card.getByText("3 added", { exact: true })).toBeVisible();
    await expect(statusOf(page, ids.a)).toBeFocused();
    await expect(live(page)).toHaveText("Proposal approved: Add 3 transactions");
    await expect(page.getByText(/1 waiting\./)).toBeVisible();
    const sent = inbox.sent("POST", "/approve");
    expect(sent).toHaveLength(1);
    expect(sent[0].body).toBeNull();
    expect(new URL(sent[0].url).pathname).toBe(`/api/proposals/${ids.a}/approve`);
  });

  test("a skipped row is reported in the footer and announcement", async ({ page }) => {
    await mockInbox(page, { list: [plain3()] });
    await openInbox(page);
    const card = byId(page, ids.a);
    await card.getByRole("button", { name: "Skip row 2: Toko Contoh, -120,000" }).click();
    await expect(approveBtn(card)).toHaveAccessibleName("Approve: Add 2 transactions, 1 skipped");
    await approveBtn(card).click();
    await expect(card.getByText("2 added, 1 skipped", { exact: true })).toBeVisible();
    await expect(live(page)).toHaveText("Proposal approved: Add 2 transactions, 1 skipped");
  });
});

test.describe("reject", () => {
  test("rejects at once when nothing is skipped", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [oneRow()] });
    await openInbox(page);
    const card = byId(page, ids.c);
    await rejectBtn(card).click();
    await expect(statusOf(page, ids.c)).toHaveText("Rejected · nothing changed");
    await expect(statusOf(page, ids.c)).toBeFocused();
    await expect(live(page)).toHaveText("Proposal rejected. Nothing changed.");
    const sent = inbox.sent("POST", "/reject");
    expect(sent).toHaveLength(1);
    expect(sent[0].body).toBeNull();
  });
});

test.describe("discard", () => {
  const skippedCard = () =>
    proposal({
      payload: {
        operation: "add_transaction",
        rows: [txRow({ skip: true }), txRow({ after: { merchant: "Toko Contoh" } })],
      },
    });

  test("two-step discard when rows are skipped", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [skippedCard()] });
    await openInbox(page);
    const card = byId(page, ids.a);
    await rejectBtn(card).click();
    await expect(card.getByText("Discard this proposal and your skip choices on 1 row?")).toBeVisible();
    await expect(card.getByRole("button", { name: "Keep it" })).toBeFocused();
    expect(inbox.sent("POST", "/reject")).toHaveLength(0);

    await page.keyboard.press("Escape");
    await expect(card.getByRole("button", { name: "Keep it" })).toHaveCount(0);
    await expect(rejectBtn(card)).toBeFocused();
    expect(inbox.sent("POST", "/reject")).toHaveLength(0);

    await rejectBtn(card).click();
    await card.getByRole("button", { name: "Discard proposal" }).click();
    await expect(statusOf(page, ids.a)).toHaveText("Rejected · nothing changed");
    expect(inbox.sent("POST", "/reject")).toHaveLength(1);
  });
});

test.describe("states", () => {
  test("loading", async ({ page }) => {
    await mockInbox(page, { listMode: "hang" });
    await openInbox(page);
    await expect(page.getByRole("status").filter({ hasText: "Loading your inbox…" })).toBeVisible();
  });

  test("empty", async ({ page }) => {
    await mockInbox(page, { list: [] });
    await openInbox(page);
    await expect(page.getByRole("heading", { name: "All caught up." })).toBeVisible();
    await expect(
      page.getByText("Proposals from Claude and chat land here. Nothing is waiting for you.")
    ).toBeVisible();
    await expect(live(page)).toHaveText("Inbox is empty");
  });

  test("error with Try again", async ({ page }) => {
    const inbox = await mockInbox(page, { listMode: 500 });
    await openInbox(page);
    const alert = page
      .getByRole("alert")
      .filter({ hasText: "Couldn't load your inbox — check the backend is running and try again." });
    await expect(alert).toBeVisible();
    inbox.listMode = "ok";
    inbox.list = [oneRow()];
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(byId(page, ids.c)).toBeVisible();
    await expect(alert).toHaveCount(0);
  });

  test("D-02 page-level approver-key alert for an MCP card without a code", async ({ page }) => {
    await mockInbox(page, { list: [proposal({ code: undefined })] });
    await openInbox(page);
    await expect(
      page.getByRole("alert").filter({ hasText: APPROVER_KEY_PAGE_MSG })
    ).toBeVisible();
    await expect(byId(page, ids.a)).toBeVisible();
    await expect(page.getByRole("code")).toHaveCount(0);
  });

  test("D-02 no page alert for a chat-only list", async ({ page }) => {
    await mockInbox(page, { list: [chatTx()] });
    await openInbox(page);
    await expect(byId(page, ids.a)).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Approvals aren't set up" })).toHaveCount(0);
  });

  const keyCases: [string, "approve" | "reject", Responder][] = [
    ["approve 401", "approve", { status: 401 }],
    ["approve 503", "approve", { status: 503 }],
    ["reject 403", "reject", { status: 403 }],
  ];
  for (const [name, action, resp] of keyCases) {
    test(`D-02 card-level approver-key line: ${name}`, async ({ page }) => {
      await mockInbox(page, { list: [oneRow()], respond: { [action]: resp } });
      await openInbox(page);
      const card = byId(page, ids.c);
      await (action === "approve" ? approveBtn(card) : rejectBtn(card)).click();
      await expect(card.getByRole("alert")).toHaveText(APPROVER_KEY_ACTION_MSG);
      await expect(statusOf(page, ids.c)).toContainText("Waiting for you");
      await expect(approveBtn(card)).not.toHaveAttribute("aria-disabled", "true");
    });
  }

  const settleCases: [string, Responder, string, string?][] = [
    ["404", { status: 404, detail: "Proposal not found" }, "Decided elsewhere", "This proposal no longer exists."],
    ["409 confirmed", { status: 409, detail: "Proposal already confirmed" }, "✓ Approved elsewhere"],
    ["409 rejected", { status: 409, detail: "Proposal already rejected" }, "Rejected elsewhere · nothing changed"],
    ["409 expired", { status: 409, detail: "Proposal already expired" }, "Expired · ask again to redo this"],
    ["410", { status: 410, detail: "Gone" }, "Expired · ask again to redo this"],
  ];
  for (const [name, resp, status, alert] of settleCases) {
    test(`approve answered ${name}`, async ({ page }) => {
      await mockInbox(page, { list: [oneRow()], respond: { approve: resp } });
      await openInbox(page);
      const card = byId(page, ids.c);
      await approveBtn(card).click();
      await expect(statusOf(page, ids.c)).toHaveText(status);
      await expect(approveBtn(card)).toHaveCount(0);
      if (alert) await expect(card.getByRole("alert")).toHaveText(alert);
    });
  }

  test("approve answered 409 superseded links to the newer card", async ({ page }) => {
    await mockInbox(page, {
      list: [
        proposal({ id: ids.a, created_at: iso(NOW - 10 * MIN) }),
        proposal({
          id: ids.b,
          supersedes_id: ids.a,
          created_at: iso(NOW - 1 * MIN),
          payload: { operation: "add_transaction", rows: [txRow({ after: { account: "Account B" } })] },
        }),
      ],
      respond: { approve: { status: 409, detail: "Proposal already superseded" } },
    });
    await openInbox(page);
    const card = byId(page, ids.a);
    await approveBtn(card).click();
    await expect(statusOf(page, ids.a)).toContainText("Replaced by a newer version");
    await expect(statusOf(page, ids.a).getByRole("link", { name: "Go to the new one" })).toHaveAttribute(
      "href",
      `#proposal-${ids.b}`
    );
  });

  const errorCases: [string, Responder, string][] = [
    ["409 with any other detail", { status: 409, detail: "stale" }, `Couldn't apply: ${LEDGER_CHANGED_MSG}`],
    ["422 verbatim", { status: 422, detail: "Amount must not be zero" }, "Couldn't apply: Amount must not be zero"],
    ["a network failure", { status: 0, abort: true }, `Couldn't apply: ${NETWORK_FAIL_MSG}`],
  ];
  for (const [name, resp, alert] of errorCases) {
    test(`approve answered ${name} stays waiting`, async ({ page }) => {
      await mockInbox(page, { list: [oneRow()], respond: { approve: resp } });
      await openInbox(page);
      const card = byId(page, ids.c);
      await approveBtn(card).click();
      await expect(card.getByRole("alert")).toHaveText(alert);
      await expect(statusOf(page, ids.c)).toContainText("Waiting for you");
      await expect(approveBtn(card)).not.toHaveAttribute("aria-disabled", "true");
      await expect(approveBtn(card)).toContainText("Add 1 transaction");
    });
  }

  test("a card past its expiry settles as expired on the 30 s tick", async ({ page }) => {
    await liveLog(page);
    await mockInbox(page, { list: [oneRow({ expires_at: iso(NOW + 90_000) })] });
    await page.clock.install({ time: NOW });
    await page.goto("/inbox");
    const card = byId(page, ids.c);
    await expect(card).toBeVisible();
    await freeze(page);
    await page.clock.runFor(120_000);
    await expect(statusOf(page, ids.c)).toHaveText("Expired · ask again to redo this");
    await expect(approveBtn(card)).toHaveCount(0);
    await expect.poll(() => heard(page)).toContain("A proposal expired");
  });

  test("a card that vanished from the server shows Decided elsewhere", async ({ page }) => {
    await liveLog(page);
    const inbox = await mockInbox(page, { list: [oneRow()] });
    await page.clock.install({ time: NOW });
    await page.goto("/inbox");
    await expect(byId(page, ids.c)).toBeVisible();
    await freeze(page);
    inbox.list = [];
    await page.clock.runFor(10_000);
    await expect(statusOf(page, ids.c)).toHaveText("Decided elsewhere");
    await expect.poll(() => heard(page)).toContain("A proposal was decided elsewhere");
  });

  test("a card that vanished after its expiry shows Expired instead", async ({ page }) => {
    await liveLog(page);
    const inbox = await mockInbox(page, { list: [oneRow({ expires_at: iso(NOW + 5_000) })] });
    await page.clock.install({ time: NOW });
    await page.goto("/inbox");
    await expect(byId(page, ids.c)).toBeVisible();
    await freeze(page);
    inbox.list = [];
    await page.clock.runFor(10_000);
    await expect(statusOf(page, ids.c)).toHaveText("Expired · ask again to redo this");
    await expect.poll(() => heard(page)).toContain("A proposal expired");
  });

  test("the server clock offset from the Date header shifts the countdown", async ({ page }) => {
    await mockInbox(page, { list: [oneRow()], dateHeader: new Date(NOW + 2 * 3_600_000).toUTCString() });
    await openInbox(page);
    await expect(statusOf(page, ids.c)).toHaveText("Waiting for you · expires in 45 h");
  });
});

// ===========================================================================
// Plan 05 Task 1 — poll hygiene and offline under a controlled clock (D-06)
//
// The page clock is installed, then paused once data is on screen. openFrozen
// then lets exactly one successful poll land inside the paused clock, so every
// later schedule is exact and the specs can step to "1 ms before" and "exactly
// at" a due time. A page-side log records each list request (start/settle on
// the page clock); request counts are never asserted absolutely (StrictMode).
// ===========================================================================

type PollRec = { start: number; end: number | null };
const BANNER = "inbox-offline-banner";
const banner = (page: Page) => page.locator(`#${BANNER}`);

async function pollLog(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __polls: { start: number; end: number | null }[] };
    w.__polls = [];
    const real = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const p = real(input, init);
      if (url.includes("/api/proposals?status=pending")) {
        const rec: { start: number; end: number | null } = { start: Date.now(), end: null };
        w.__polls.push(rec);
        const done = () => {
          rec.end = Date.now();
        };
        p.then(done, done);
      }
      return p;
    };
  });
}

const polls = (page: Page) =>
  page.evaluate(() => (window as unknown as { __polls: PollRec[] }).__polls);
const lastPoll = async (page: Page) => {
  const l = await polls(page);
  return { n: l.length, rec: l[l.length - 1] };
};
const clockNow = (page: Page) => page.evaluate(() => Date.now());
const runTo = async (page: Page, target: number) =>
  page.clock.runFor(Math.max(0, target - (await clockNow(page))));

/** The latest request has settled (a real-time pause lets the body read and state updates finish). */
async function settled(page: Page) {
  await expect.poll(async () => (await lastPoll(page)).rec?.end ?? null).not.toBeNull();
  await page.waitForTimeout(150);
}

async function openFrozen(page: Page, init: Partial<InboxMock>) {
  const inbox = await mockInbox(page, init);
  await pollLog(page);
  await page.clock.install({ time: NOW });
  await page.goto("/inbox");
  await expect(page.locator("article").first()).toBeVisible();
  await freeze(page);
  const base = inbox.hits.list;
  await page.clock.runFor(10_000);
  await expect.poll(() => inbox.hits.list).toBe(base + 1);
  await settled(page);
  return inbox;
}

/** 1 ms before the due time nothing is requested; exactly at it, one request starts. */
async function nextPoll(page: Page, delay: number) {
  const before = await lastPoll(page);
  const due = (before.rec.end as number) + delay;
  await runTo(page, due - 1);
  expect((await polls(page)).length, `no request before ${delay} ms`).toBe(before.n);
  await runTo(page, due);
  const after = await polls(page);
  expect(after.length, `one request at ${delay} ms`).toBe(before.n + 1);
  expect(after[before.n].start).toBe(due);
  return after[before.n];
}

const setVisibility = (page: Page, state: "hidden" | "visible") =>
  page.evaluate((s) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => s });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);

test.describe("poll", () => {
  test("one request in flight; an 8 s timeout is a failure", async ({ page }) => {
    const inbox = await openFrozen(page, { list: [oneRow()] });
    const h0 = inbox.hits.list;
    inbox.listMode = "hang";
    const first = await nextPoll(page, 10_000);
    await expect.poll(() => inbox.hits.list).toBe(h0 + 1);
    const n = (await polls(page)).length;

    // Still pending 1 ms short of the timeout: a trigger while pending is a no-op, nothing failed.
    await runTo(page, first.start + 7_999);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    expect((await polls(page)).length).toBe(n);
    expect((await lastPoll(page)).rec.end).toBeNull();
    await expect(banner(page)).toHaveCount(0);

    await runTo(page, first.start + 8_000);
    await settled(page);
    expect((await lastPoll(page)).rec.end).toBe(first.start + 8_000);
    await expect(banner(page)).toHaveCount(0); // one failure is not offline

    // Backoff 20 s from the failure, then a second timeout flips to offline.
    const second = await nextPoll(page, 20_000);
    await runTo(page, second.start + 8_000);
    await settled(page);
    await expect(banner(page)).toBeVisible();
  });

  test("backoff 10, 20, 40, 60, 60 s, then success resets to 10 s", async ({ page }) => {
    const inbox = await openFrozen(page, { list: [oneRow()] });
    inbox.listMode = "abort";
    for (const delay of [10_000, 20_000, 40_000, 60_000, 60_000]) {
      await nextPoll(page, delay);
      await settled(page);
    }
    await expect(banner(page)).toBeVisible();
    inbox.listMode = "ok";
    await nextPoll(page, 60_000);
    await settled(page);
    await expect(banner(page)).toHaveCount(0);
    await nextPoll(page, 10_000);
  });

  test("nothing polls after leaving /inbox", async ({ page }) => {
    const inbox = await openFrozen(page, { list: [oneRow()] });
    await page.getByRole("link", { name: "Records", exact: true }).click();
    // Next's client navigation does not complete on a paused clock: let time flow, then stop it again.
    await page.clock.resume();
    await expect(page).toHaveURL(/\/records$/, { timeout: 30_000 });
    await freeze(page);
    await page.waitForTimeout(300);
    const server = inbox.hits.list;
    const client = (await polls(page)).length;
    await page.clock.runFor(60_000);
    await page.waitForTimeout(300);
    expect(inbox.hits.list).toBe(server);
    expect((await polls(page)).length).toBe(client);
  });

  test("paused while hidden, exactly one request on return", async ({ page }) => {
    const inbox = await openFrozen(page, { list: [oneRow()] });
    await setVisibility(page, "hidden");
    expect(await page.evaluate(() => document.visibilityState)).toBe("hidden");
    const n = (await polls(page)).length;
    const h = inbox.hits.list;
    await page.clock.runFor(60_000);
    await page.waitForTimeout(300);
    expect((await polls(page)).length).toBe(n);
    expect(inbox.hits.list).toBe(h);

    await setVisibility(page, "visible"); // no clock advance
    expect(await page.evaluate(() => document.visibilityState)).toBe("visible");
    expect((await polls(page)).length).toBe(n + 1);
    await expect.poll(() => inbox.hits.list).toBe(h + 1);
    await settled(page);
    await nextPoll(page, 10_000); // the interval resumes
  });

  test("a poll never overwrites a card with an in-flight approve; mutations are not polled", async ({
    page,
  }) => {
    const inbox = await openFrozen(page, { list: [oneRow()] });
    const card = byId(page, ids.c);
    const release = inbox.hold("approve");
    await approveBtn(card).click();
    await expect(statusOf(page, ids.c)).toHaveText("Applying…");
    inbox.list = [
      oneRow({
        payload: { operation: "add_transaction", rows: [txRow({ after: { merchant: "Kopi Baru" } })] },
      }),
    ];
    await nextPoll(page, 10_000);
    await settled(page);
    await expect(card.getByText("Kopi Contoh", { exact: true })).toBeVisible();
    await expect(card.getByText("Kopi Baru")).toHaveCount(0);
    await expect(statusOf(page, ids.c)).toHaveText("Applying…");

    release();
    await expect(statusOf(page, ids.c)).toHaveText(/^✓ Approved · /);
    await page.clock.runFor(60_000);
    await page.waitForTimeout(300);
    expect(inbox.sent("POST", "/approve")).toHaveLength(1);
  });
});

test.describe("offline", () => {
  const two = () =>
    proposal({
      id: ids.c,
      payload: {
        operation: "add_transaction",
        rows: [txRow(), txRow({ after: { merchant: "Toko Contoh" } })],
      },
    });
  const bannerText = (at: number) => `Can't reach monai · retrying (last update ${hhmm(at)})`;

  test("two failed polls gate the card; the next success clears it", async ({ page }) => {
    const inbox = await openFrozen(page, { list: [two()] });
    const lastOk = (await lastPoll(page)).rec.end as number;
    inbox.listMode = "abort";
    await nextPoll(page, 10_000);
    await settled(page);
    await expect(banner(page)).toHaveCount(0);
    await nextPoll(page, 20_000);
    await settled(page);

    await expect(banner(page)).toHaveText(bannerText(lastOk));
    const card = byId(page, ids.c);
    const skips = card.getByRole("button", { name: /^Skip row/ });
    await expect(skips).toHaveCount(2);
    const gated = [approveBtn(card), rejectBtn(card), ...(await skips.all())];
    for (const b of gated) {
      await expect(b).toHaveAttribute("aria-disabled", "true");
      await expect(b).toHaveAttribute("aria-describedby", "inbox-offline-banner");
    }
    await approveBtn(card).click({ force: true });
    await page.waitForTimeout(300);
    expect(inbox.sent("POST", "/approve")).toHaveLength(0);
    await expect(
      page.getByRole("link", { name: "Inbox, pending count unavailable", exact: true })
    ).toBeVisible();
    await expect(page.locator(".nav-badge")).toHaveText("—");
    await expect(live(page)).toHaveText("Can't reach monai. Retrying.");

    inbox.listMode = "ok";
    await nextPoll(page, 40_000);
    await settled(page);
    await expect(banner(page)).toHaveCount(0);
    await expect(approveBtn(card)).not.toHaveAttribute("aria-disabled", "true");
    await expect(live(page)).toHaveText("Back online.");
    await expect(page.getByRole("link", { name: "Inbox, 1 pending", exact: true })).toBeVisible();
  });

  test("the window offline and online events", async ({ page, context }) => {
    const inbox = await openFrozen(page, { list: [two()] });
    const lastOk = (await lastPoll(page)).rec.end as number;
    await context.setOffline(true);
    await expect(banner(page)).toHaveText(bannerText(lastOk));
    const h = inbox.hits.list;
    await context.setOffline(false);
    await expect.poll(() => inbox.hits.list).toBe(h + 1);
    await expect(banner(page)).toHaveCount(0);
    await expect(live(page)).toHaveText("Back online.");
  });
});

// ===========================================================================
// Plan 05 Task 2 — keyboard, structure (axe substitute, D-07), narrow layout,
// chat card (QA-02 chat half)
// ===========================================================================

// UI-SPEC tokens as computed-style strings (ui/app/styles.ts).
const RGB = {
  green: "rgb(47, 111, 79)",
  muted3: "rgb(111, 104, 87)",
  ink: "rgb(35, 32, 27)",
  tintNeutral: "rgb(238, 241, 236)",
  white: "rgb(255, 255, 255)",
  chatDim: "rgb(164, 156, 140)",
};
const css = (loc: ReturnType<Page["locator"]>, prop: string) =>
  loc.evaluate((el, p) => getComputedStyle(el).getPropertyValue(p), prop);

test.describe("keyboard", () => {
  const twoRows = () =>
    proposal({
      id: ids.c,
      payload: { operation: "add_transaction", rows: [txRow(), txRow({ after: { merchant: "Toko Contoh" } })] },
    });

  test("tab order, focus ring, Space toggles a skip, Enter approves", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [twoRows()] });
    await openInbox(page);
    const card = byId(page, ids.c);
    const copy = card.getByRole("button", { name: "Copy confirm code" });
    const skip1 = card.getByRole("button", { name: /^Skip row 1:/ });
    const skip2 = card.getByRole("button", { name: /^Skip row 2:/ });
    const approve = approveBtn(card);
    const reject = rejectBtn(card);

    await copy.focus();
    await expect(copy).toBeFocused();
    for (const next of [skip1, skip2, approve, reject]) {
      await page.keyboard.press("Tab");
      await expect(next).toBeFocused();
      if (next === skip1) {
        expect(await css(next, "outline-width")).toBe("2px");
        expect(await css(next, "outline-style")).toBe("solid");
        expect(await css(next, "outline-color")).toBe(RGB.green);
        expect(await css(next, "outline-offset")).toBe("2px");
      }
    }
    for (const prev of [approve, skip2, skip1]) {
      await page.keyboard.press("Shift+Tab");
      await expect(prev).toBeFocused();
    }

    await page.keyboard.press("Space");
    await expect.poll(() => inbox.sent("PATCH", "/rows/0").length).toBe(1);
    const include1 = card.getByRole("button", { name: /^Include row 1:/ });
    await expect(include1).toBeFocused();

    await page.keyboard.press("Tab"); // Skip row 2
    await page.keyboard.press("Tab"); // Approve
    await expect(approve).toBeFocused();
    await page.keyboard.press("Enter");
    await expect.poll(() => inbox.sent("POST", "/approve").length).toBe(1);
    await expect(statusOf(page, ids.c)).toBeFocused();
    await expect(live(page)).toHaveText("Proposal approved: Add 1 transaction, 1 skipped");
  });

  test("no single-key shortcut approves or rejects", async ({ page }) => {
    const inbox = await mockInbox(page, { list: [twoRows()] });
    await openInbox(page);
    await expect(byId(page, ids.c)).toBeVisible();
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    for (const key of ["a", "r", "Enter"]) await page.keyboard.press(key);
    await page.waitForTimeout(300);
    expect(inbox.sent("POST", "/approve")).toHaveLength(0);
    expect(inbox.sent("POST", "/reject")).toHaveLength(0);
  });
});

test.describe("a11y structure", () => {
  const LIVE = '[role="status"][aria-live="polite"][aria-atomic="true"]';

  test("one persistent polite atomic live region, from the loading state on", async ({ page }) => {
    const inbox = await mockInbox(page, { listMode: "hang" });
    await openInbox(page);
    await expect(page.getByRole("status").filter({ hasText: "Loading your inbox…" })).toBeVisible();
    await expect(page.locator(LIVE)).toHaveCount(1);
    inbox.listMode = "ok";
    inbox.list = [oneRow()];
    await page.reload(); // the hung request is still in flight; start over with data
    await expect(byId(page, ids.c)).toBeVisible();
    await expect(page.locator(LIVE)).toHaveCount(1);
  });

  test("headings, list, article names, table", async ({ page }) => {
    await mockInbox(page, {
      list: [batch3(), other(), chatTx({ id: ids.d, created_at: iso(NOW - 20 * MIN) }), transferProposal({ id: ids.e, created_at: iso(NOW - 30 * MIN) })],
    });
    await openInbox(page);
    await expect(page.locator("article")).toHaveCount(4);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Inbox");

    const shape = await page.evaluate(() => {
      const arts = Array.from(document.querySelectorAll("article"));
      const lists = new Set(arts.map((a) => a.closest("ul")));
      return {
        allInLi: arts.every((a) => a.parentElement?.tagName === "LI"),
        lists: lists.size,
        listIsUl: arts.every((a) => a.closest("ul")?.tagName === "UL"),
      };
    });
    expect(shape).toEqual({ allInLi: true, lists: 1, listIsUl: true });

    const titles = await page.locator("article h2").allTextContents();
    expect(titles).toHaveLength(4);
    const articles = page.locator("article");
    for (let k = 0; k < titles.length; k++) {
      await expect(articles.nth(k)).toHaveAccessibleName(titles[k]);
    }

    const table = byId(page, ids.a).locator("table");
    await expect(table.locator("caption")).toHaveText("Rows in this proposal");
    await expect(table.locator('th[scope="col"]')).toHaveCount(7);
  });

  test("UI-SPEC token colours; no opacity fade on an expired card; skipped is a word", async ({
    page,
  }) => {
    await mockInbox(page, {
      list: [
        proposal({ id: ids.a }),
        proposal({
          id: ids.b,
          created_at: iso(NOW - 5 * MIN),
          payload: { operation: "add_transaction", rows: [txRow({ skip: true }), txRow()] },
        }),
      ],
      respond: { approve: { status: 410, detail: "Gone" } },
    });
    await openInbox(page);
    const card = byId(page, ids.a);
    await expect(card).toBeVisible();

    expect(await css(card.getByText(/^Proposed /), "color")).toBe(RGB.muted3);
    const chip = card.getByText("Claude", { exact: true });
    expect(await css(chip, "color")).toBe(RGB.muted3);
    expect(await css(chip, "background-color")).toBe(RGB.tintNeutral);
    expect(await css(statusOf(page, ids.a), "color")).toBe(RGB.ink);
    const approve = approveBtn(card);
    expect(await css(approve, "background-color")).toBe(RGB.green);
    expect(await css(approve, "color")).toBe(RGB.white);

    await expect(byId(page, ids.b).getByText("Skipped", { exact: true })).toBeVisible();

    await approve.click(); // answered 410: the card settles as expired
    await expect(statusOf(page, ids.a)).toHaveText("Expired · ask again to redo this");
    const opacities = await card.evaluate((el) => [
      getComputedStyle(el).opacity,
      ...Array.from(el.querySelectorAll("*")).map((n) => getComputedStyle(n).opacity),
    ]);
    expect(new Set(opacities)).toEqual(new Set(["1"]));
  });
});

test.describe("narrow", () => {
  test("below 900 px the table stacks per row", async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 900 });
    await mockInbox(page, { list: [batch3()] });
    await openInbox(page);
    const card = byId(page, ids.a);
    await expect(card).toBeVisible();

    const thead = card.locator("thead");
    await expect(thead.locator("th")).toHaveCount(7);
    const box = await thead.boundingBox();
    expect(box === null || box.height <= 1).toBe(true);

    const row = card.locator(".inbox-row").first();
    expect(await css(row, "display")).toBe("grid");
    const amount = await row.locator(".inbox-c-amount").boundingBox();
    const skip = await row.getByRole("button", { name: /^Skip row 1:/ }).boundingBox();
    expect(amount && skip).toBeTruthy();
    expect((skip as { y: number }).y).toBeGreaterThanOrEqual(
      (amount as { y: number; height: number }).y + (amount as { height: number }).height - 1
    );

    const footer = await card.locator(".inbox-footer").boundingBox();
    const approve = await approveBtn(card).boundingBox();
    expect((approve as { width: number }).width).toBeGreaterThanOrEqual(
      0.9 * (footer as { width: number }).width
    );
  });
});

test.describe("chat card", () => {
  const TOKEN = "tok-synthetic";
  const pid = ids.h;

  async function chatSetup(page: Page) {
    const inbox = await mockInbox(page, { list: [] }); // counts + catch-all; nothing else is unmocked
    const answer = {
      type: "answer",
      text: "I can add that.",
      proposals: [{ id: pid, token: TOKEN }],
      trace: [
        {
          tool: "propose_add_transaction",
          args: {},
          result: {
            proposal_id: pid,
            proposal_token: TOKEN,
            payload: {
              operation: "add_transaction",
              rows: [
                {
                  before: null,
                  after: {
                    date: "2026-10-07",
                    amount: "-35000.00",
                    account: "Account A",
                    merchant: "Kopi Contoh",
                    category: null,
                    notes: null,
                    currency: "IDR",
                    is_transfer: false,
                  },
                },
              ],
            },
          },
        },
      ],
    };
    await page.route(/\/api\/query-stream$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          `data: ${JSON.stringify({ type: "step", msg: "thinking…" })}\n\n` +
          `data: ${JSON.stringify(answer)}\n\n` +
          "data: [DONE]\n\n",
      })
    );
    const posts: { path: string; body: unknown }[] = [];
    await page.route(/\/api\/proposals\/[0-9a-f-]{36}\/(confirm|reject)$/, (route) => {
      const req = route.request();
      posts.push({ path: new URL(req.url()).pathname, body: req.postDataJSON() });
      return route.fulfill({ json: { id: pid, status: req.url().endsWith("/confirm") ? "confirmed" : "rejected" } });
    });
    await page.goto("/chat");
    await page.getByPlaceholder("Ask anything about your finances…").fill("Add a synthetic coffee");
    await page.getByPlaceholder("Ask anything about your finances…").press("Enter");
    await expect(page.getByText("Proposed propose add transaction")).toBeVisible();
    return { inbox, posts };
  }

  test("still shows the shared diff in the chat colour and approves with its token", async ({ page }) => {
    const { posts } = await chatSetup(page);
    await expect(page.getByText("Kopi Contoh", { exact: true })).toBeVisible();
    expect(await css(page.getByText("merchant:", { exact: true }), "color")).toBe(RGB.chatDim);

    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByText("Applied successfully.")).toBeVisible();
    expect(posts).toEqual([{ path: `/api/proposals/${pid}/confirm`, body: { token: "tok-synthetic" } }]);
  });

  test("Reject still says nothing changed", async ({ page }) => {
    const { posts } = await chatSetup(page);
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await expect(page.getByText("Rejected — no changes made.")).toBeVisible();
    expect(posts.map((p) => p.path)).toEqual([`/api/proposals/${pid}/reject`]);
  });
});
