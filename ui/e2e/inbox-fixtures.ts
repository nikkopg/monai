// ---------------------------------------------------------------------------
// Phase 33 Inbox e2e helpers: synthetic proposal builders plus a page.route
// controller that mocks every /api/proposals* call (counts, list, approve,
// reject, row skip). Not a spec. Synthetic values only (public repo).
//
// Routes are regexes, never globs (a glob `?` is one character). A catch-all
// /api/ route is registered first (lowest priority) so no request can escape to
// a real backend through the Next proxy.
// ---------------------------------------------------------------------------

import type { Page, Route } from "@playwright/test";
import type { DuplicateFlag, InboxProposal, ProposalRow } from "../app/lib/inbox";

export const NOW = Date.parse("2026-10-09T04:00:00Z");
export const MIN = 60_000;
export const HOUR = 3_600_000;
export const iso = (ms: number) => new Date(ms).toISOString();

export const ids = {
  a: "aaaaaaaa-0000-4000-8000-000000000001",
  b: "aaaaaaaa-0000-4000-8000-000000000002",
  c: "aaaaaaaa-0000-4000-8000-000000000003",
  d: "aaaaaaaa-0000-4000-8000-000000000004",
  e: "aaaaaaaa-0000-4000-8000-000000000005",
  f: "aaaaaaaa-0000-4000-8000-000000000006",
  g: "aaaaaaaa-0000-4000-8000-000000000007",
  h: "aaaaaaaa-0000-4000-8000-000000000008",
  i: "aaaaaaaa-0000-4000-8000-000000000009",
};

/** An add_transaction row (before: null). `after` overrides merge over the defaults. */
export function txRow(
  o: { after?: Record<string, unknown>; duplicates?: DuplicateFlag[]; skip?: boolean } = {}
): ProposalRow {
  return {
    before: null,
    after: {
      date: "2026-10-07",
      amount: "-35000.00",
      account: "Account A",
      category: null,
      merchant: "Kopi Contoh",
      notes: null,
      currency: "IDR",
      is_transfer: false,
      ...o.after,
    },
    duplicates: o.duplicates ?? [],
    ...(o.skip === undefined ? {} : { skip: o.skip }),
  };
}

export function proposal(o: Partial<InboxProposal> = {}): InboxProposal {
  const operation = o.operation ?? "add_transaction";
  return {
    id: ids.a,
    operation,
    payload: { operation, rows: [txRow()] },
    status: "pending",
    expires_at: iso(NOW + 47 * HOUR + 5 * MIN),
    created_at: iso(NOW - 3 * MIN),
    confirmed_at: null,
    channel: "mcp",
    supersedes_id: null,
    failed_attempts: 0,
    code: "K7Q2MX",
    ...o,
  };
}

export const chatTx = (o: Partial<InboxProposal> = {}) =>
  proposal({ channel: "chat", code: undefined, expires_at: iso(NOW + 12 * MIN), ...o });

export const transferProposal = (o: Partial<InboxProposal> = {}) =>
  proposal({
    operation: "add_transfer",
    payload: {
      operation: "add_transfer",
      rows: [
        {
          before: null,
          after: {
            leg_a: { account: "Account A", amount: "-50000.00", date: "2026-10-07" },
            leg_b: { account: "Account B", amount: "50000.00" },
          },
          duplicates: [],
        },
      ],
    },
    ...o,
  });

export const editProposal = (o: Partial<InboxProposal> = {}) =>
  proposal({
    operation: "edit_transaction",
    payload: {
      operation: "edit_transaction",
      rows: [
        {
          id: 7,
          before: { merchant: "Kopi Contoh", amount: "-35000.00" },
          after: { merchant: "Warung Contoh", amount: "-35000.00" },
        },
      ],
    },
    ...o,
  });

// ---------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------

export type Mode = "ok" | "abort" | "hang" | number;
export type Responder = { status: number; detail?: string; abort?: boolean };
export type Kind = "approve" | "reject" | "skip" | "list" | "counts";
export type Req = { method: string; url: string; body: unknown };

export type InboxMock = {
  list: InboxProposal[];
  listMode: Mode;
  dateHeader?: string;
  /** Served as {pending: counts}; defaults to list.length when undefined. */
  counts?: number;
  /** When set, served verbatim as the counts JSON body. */
  countsRaw?: unknown;
  countsMode: "ok" | "hang" | "abort";
  hits: { list: number; counts: number };
  requests: Req[];
  respond: { approve?: Responder; reject?: Responder; skip?: Responder };
  /** Make the next response of this kind wait until the returned function is called. */
  hold(kind: Kind): () => void;
  /** Logged requests whose path ends with the given suffix (e.g. "/approve"). */
  sent(method: string, suffix: string): Req[];
};

const stripDuplicates = (p: InboxProposal): InboxProposal => {
  const copy: InboxProposal = JSON.parse(JSON.stringify(p));
  copy.payload.rows = copy.payload.rows.map((r) => {
    delete r.duplicates;
    return r;
  });
  return copy;
};

export async function mockInbox(page: Page, init: Partial<InboxMock> = {}): Promise<InboxMock> {
  const gates: Partial<Record<Kind, Promise<void>>> = {};
  const mock: InboxMock = {
    list: [],
    listMode: "ok",
    countsMode: "ok",
    hits: { list: 0, counts: 0 },
    requests: [],
    respond: {},
    hold(kind) {
      let release!: () => void;
      gates[kind] = new Promise<void>((r) => {
        release = r;
      });
      return release;
    },
    sent(method, suffix) {
      return mock.requests.filter((r) => r.method === method && new URL(r.url).pathname.endsWith(suffix));
    },
    ...init,
  };

  const wait = async (kind: Kind) => {
    const g = gates[kind];
    if (g) {
      delete gates[kind];
      await g;
    }
  };
  const log = (route: Route) => {
    const req = route.request();
    let body: unknown = null;
    try {
      body = req.postData() ? JSON.parse(req.postData() as string) : null;
    } catch {
      body = null;
    }
    mock.requests.push({ method: req.method(), url: req.url(), body });
  };
  const answer = async (route: Route, r: Responder) => {
    if (r.abort) return route.abort();
    return route.fulfill({
      status: r.status,
      json: r.detail === undefined ? {} : { detail: r.detail },
    });
  };
  const find = (route: Route) => {
    const id = /\/proposals\/([0-9a-fA-F-]{36})/.exec(route.request().url())?.[1];
    return mock.list.find((p) => p.id === id);
  };

  // Lowest priority: anything under /api/ nobody mocked fails loudly, never reaches a backend.
  await page.route(/\/api\//, (route) =>
    route.fulfill({ status: 500, json: { detail: "unmocked request" } })
  );

  await page.route(/\/api\/proposals\/counts$/, async (route) => {
    mock.hits.counts++;
    await wait("counts");
    if (mock.countsMode === "abort") return route.abort();
    if (mock.countsMode === "hang") return new Promise<void>(() => {});
    return route.fulfill({
      json: mock.countsRaw !== undefined ? mock.countsRaw : { pending: mock.counts ?? mock.list.length },
    });
  });

  await page.route(/\/api\/proposals(\?|$)/, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    mock.hits.list++;
    await wait("list");
    const mode = mock.listMode;
    if (mode === "abort") return route.abort();
    if (mode === "hang") return new Promise<void>(() => {});
    if (typeof mode === "number") return route.fulfill({ status: mode, json: { detail: "boom" } });
    return route.fulfill({
      json: mock.list,
      headers: mock.dateHeader ? { date: mock.dateHeader } : {},
    });
  });

  await page.route(/\/api\/proposals\/[0-9a-fA-F-]{36}\/(approve|reject)$/, async (route) => {
    log(route);
    const kind = route.request().url().endsWith("/approve") ? "approve" : "reject";
    await wait(kind);
    const cfg = mock.respond[kind];
    if (cfg) return answer(route, cfg);
    const p = find(route);
    if (!p) return answer(route, { status: 404, detail: "Proposal not found" });
    mock.list = mock.list.filter((x) => x.id !== p.id);
    return route.fulfill({
      json: { ...stripDuplicates(p), status: kind === "approve" ? "confirmed" : "rejected" },
    });
  });

  await page.route(/\/api\/proposals\/[0-9a-fA-F-]{36}\/rows\/\d+$/, async (route) => {
    log(route);
    await wait("skip");
    if (mock.respond.skip) return answer(route, mock.respond.skip);
    const p = find(route);
    const i = Number(/\/rows\/(\d+)$/.exec(route.request().url())?.[1]);
    const body = mock.requests[mock.requests.length - 1].body as { skip?: boolean } | null;
    if (!p || !p.payload.rows[i]) return answer(route, { status: 404, detail: "Proposal not found" });
    p.payload.rows[i].skip = body?.skip === true; // persisted, like the backend
    return route.fulfill({ json: stripDuplicates(p) });
  });

  return mock;
}
