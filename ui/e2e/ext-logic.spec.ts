import { test, expect } from "@playwright/test";
import {
  parseExt,
  isExt,
  unpinned,
  countdownText,
  isLastMinute,
  canonicalArgs,
  joinSteps,
  cardState,
  cardStatus,
  stepSuffix,
  decisionLabel,
  receiptLabel,
  footerServers,
  noticeSentence,
  mergeCallEvent,
  announce,
  type ExtCall,
  type CardState,
} from "../app/chat/extLabels";
import { extOriginAllowed } from "../app/lib/approverAllowlist";

// ---------------------------------------------------------------------------
// Phase 41 Plan 08 — non-browser logic spec: pure modules only. Synthetic values.
// ---------------------------------------------------------------------------

const U = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01";
const C = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee02";

function call(over: Partial<ExtCall> = {}): ExtCall {
  return {
    id: "c1",
    message_id: null,
    server_slug: "zz-notes",
    tool: "search_notes",
    args: { query: "x" },
    destination: "notes.example.com",
    leaves_machine: true,
    reason: null,
    approval: "pending",
    decided_via: null,
    expires_at: "2026-01-01T00:10:00Z",
    receipt: null,
    error_class: null,
    ...over,
  };
}

test.describe("parseExt", () => {
  test("splits on the first double underscore", () => {
    expect(parseExt("ext__zz-notes__search_notes")).toEqual({ slug: "zz-notes", tool: "search_notes" });
    expect(parseExt("ext__zz-notes__a__b")).toEqual({ slug: "zz-notes", tool: "a__b" });
  });
  test("non-external names are null", () => {
    expect(parseExt("spending_total")).toBeNull();
    expect(isExt("spending_total")).toBe(false);
    expect(isExt("ext__zz-notes__search_notes")).toBe(true);
  });
});

test.describe("unpinned", () => {
  test("pinned versions", () => {
    expect(unpinned("npx", ["-y", "@example/notes-mcp@1.2.3"])).toBeNull();
    expect(unpinned("uvx", ["mcp-server-example==1.2.3"])).toBeNull();
  });
  test("unpinned versions return the package", () => {
    expect(unpinned("npx", ["@example/notes-mcp"])).toBe("@example/notes-mcp");
    expect(unpinned("npx", ["@example/notes-mcp@latest"])).toBe("@example/notes-mcp@latest");
    expect(unpinned("npx", ["notes-mcp@^1.2.0"])).toBe("notes-mcp@^1.2.0");
    expect(unpinned("uvx", ["mcp-server-example"])).toBe("mcp-server-example");
  });
});

test.describe("countdown", () => {
  test("m:ss and zero", () => {
    expect(countdownText(582000)).toBe("Auto-denies in 9:42");
    expect(countdownText(0)).toBe("Auto-denying…");
  });
  test("last minute flag", () => {
    expect(isLastMinute(60000)).toBe(true);
    expect(isLastMinute(61000)).toBe(false);
  });
});

test.describe("canonicalArgs", () => {
  test("key order never matters", () => {
    expect(canonicalArgs({ b: 1, a: { d: [2, { f: 1, e: 0 }], c: "x" } })).toBe(
      canonicalArgs({ a: { c: "x", d: [2, { e: 0, f: 1 }] }, b: 1 })
    );
  });
  test("different values differ", () => {
    expect(canonicalArgs({ a: 1 })).not.toBe(canonicalArgs({ a: 2 }));
  });
});

test.describe("cardState and sentences", () => {
  const cases: [Partial<ExtCall> | null, CardState][] = [
    [{ approval: "pending" }, "pending"],
    [{ approval: "approved", receipt: null }, "running"],
    [{ approval: "approved", receipt: "pending" }, "running"],
    [{ approval: "approved", receipt: "confirmed" }, "sent"],
    [{ approval: "approved", receipt: "failed", error_class: "TimeoutError" }, "failed"],
    [{ approval: "approved", receipt: "unknown" }, "unknown"],
    [{ approval: "denied", decided_via: "user" }, "denied"],
    [{ approval: "denied", decided_via: "stop" }, "stopped"],
    [{ approval: "expired" }, "expired"],
    [{ approval: "denied", decided_via: "expiry" }, "expired"],
    [null, "missing"],
  ];
  for (const [over, want] of cases) {
    test(`${JSON.stringify(over)} -> ${want}`, () => {
      expect(cardState(over ? call(over) : null)).toBe(want);
    });
  }
  test("busy only applies to a pending call", () => {
    expect(cardState(call(), true)).toBe("busy");
    expect(cardState(call({ approval: "approved" }), true)).toBe("running");
  });

  test('"Sent to" is only ever produced for a confirmed receipt', () => {
    const states: CardState[] = ["pending", "busy", "running", "sent", "failed", "unknown", "denied", "stopped", "expired", "missing"];
    expect(cardStatus("sent", call())).toBe("Sent to zz-notes.");
    for (const s of states.filter((x) => x !== "sent")) expect(cardStatus(s, call())).not.toContain("Sent to");
    const all: Partial<ExtCall>[] = [
      { approval: "pending" },
      { approval: "approved", receipt: null },
      { approval: "approved", receipt: "pending" },
      { approval: "approved", receipt: "failed", error_class: "E" },
      { approval: "approved", receipt: "unknown" },
      { approval: "denied", decided_via: "user" },
      { approval: "denied", decided_via: "stop" },
      { approval: "expired" },
    ];
    for (const o of all) {
      expect(stepSuffix(call(o))).not.toContain("Sent to");
      expect(receiptLabel(call(o))).not.toContain("Sent to");
      expect(announce.terminal(call(o))).not.toContain("Sent to");
    }
    expect(stepSuffix(call({ approval: "approved", receipt: "confirmed" }))).toBe(" · Sent to zz-notes");
    expect(receiptLabel(call({ approval: "approved", receipt: "confirmed" }))).toBe("Sent to zz-notes");
  });

  test("step suffixes", () => {
    expect(stepSuffix(call())).toBe(" · waiting for your answer");
    expect(stepSuffix(call({ approval: "denied", decided_via: "user" }))).toBe(" · denied");
    expect(stepSuffix(call({ approval: "denied", decided_via: "stop" }))).toBe(" · denied (stopped)");
    expect(stepSuffix(call({ approval: "expired" }))).toBe(" · expired, denied");
    expect(stepSuffix(call({ approval: "approved" }))).toBe(" · in progress");
    expect(stepSuffix(call({ approval: "approved", receipt: "failed" }))).toBe(" · failed");
    expect(stepSuffix(call({ approval: "approved", receipt: "unknown" }))).toBe(" · outcome unknown");
    expect(stepSuffix(null)).toBe("");
  });

  test("failed sentence carries the error class", () => {
    expect(cardStatus("failed", call({ error_class: "TimeoutError" }))).toBe(
      "Allowed, but the call to zz-notes failed (TimeoutError). Don't assume it happened."
    );
  });

  test("decision labels", () => {
    expect(decisionLabel(call({ approval: "approved", decided_via: "user" }))).toBe("You allowed it");
    expect(decisionLabel(call({ approval: "denied", decided_via: "user" }))).toBe("You denied it");
    expect(decisionLabel(call({ approval: "approved", decided_via: "policy" }))).toBe("Allowed by your Always rule");
    expect(decisionLabel(call({ approval: "denied", decided_via: "expiry" }))).toBe("Timed out, so denied");
    expect(decisionLabel(call({ approval: "denied", decided_via: "stop" }))).toBe("Denied because the run was stopped");
  });
});

test.describe("footerServers", () => {
  test("approved calls only, unique, first-use order", () => {
    const calls = [
      call({ id: "1", server_slug: "zz-files", approval: "approved", receipt: "failed" }),
      call({ id: "2", server_slug: "zz-notes", approval: "approved", receipt: "unknown" }),
      call({ id: "3", server_slug: "zz-files", approval: "approved", receipt: "confirmed" }),
      call({ id: "4", server_slug: "zz-maps", approval: "denied", decided_via: "user" }),
    ];
    expect(footerServers(calls)).toEqual(["zz-files", "zz-notes"]);
  });
  test("empty when everything was denied or expired", () => {
    expect(footerServers([call({ approval: "denied" }), call({ id: "2", approval: "expired" })])).toEqual([]);
  });
});

test.describe("noticeSentence", () => {
  test("tools_changed has a Settings link", () => {
    expect(noticeSentence({ code: "tools_changed", server: "zz-notes" })).toEqual({
      text: "zz-notes changed its tools; review them in ",
      linkText: "Settings",
      tail: ".",
    });
  });
  test("other codes", () => {
    expect(noticeSentence({ code: "unreachable", server: "zz-notes" }).text).toBe(
      "Couldn't reach zz-notes, so its tools were left out of this answer."
    );
    expect(noticeSentence({ code: "cap", limit: 8 }).text).toContain("first 8 external tools");
    expect(noticeSentence({ code: "cap" }).text).toContain("first 16 external tools");
    expect(noticeSentence({ code: "too_many_tools", server: "zz-notes" }).text).toBe(
      "zz-notes offers too many tools (over 200), so none of them were used."
    );
    expect(noticeSentence({ code: "blocked", server: "zz-notes" }).text).toBe(
      "monai blocked a call to zz-notes because its arguments contained a monai secret."
    );
  });
  test("an unknown code renders the event's own message", () => {
    expect(noticeSentence({ code: "novel", message: "Fixed words." }).text).toBe("Fixed words.");
  });
});

test.describe("joinSteps", () => {
  const a = call({ id: "a", args: { query: "one" } });
  const b = call({ id: "b", args: { query: "two" } });
  const step = (query: string) => ({ tool: "ext__zz-notes__search_notes", args: { query } });

  test("same tool, different args map to the equal-args call", () => {
    expect(joinSteps([step("two"), step("one")], [a, b])).toEqual([b, a]);
  });
  test("a repeated identical step maps to the same call", () => {
    expect(joinSteps([step("one"), step("one")], [a, b])).toEqual([a, a]);
  });
  test("no match and non-ext steps are null", () => {
    expect(joinSteps([step("three"), { tool: "spending_total", args: {} }], [a, b])).toEqual([null, null]);
  });
  test("key order in args does not matter", () => {
    const k = call({ id: "k", args: { x: 1, y: 2 } });
    expect(joinSteps([{ tool: "ext__zz-notes__search_notes", args: { y: 2, x: 1 } }], [k])).toEqual([k]);
  });
});

test.describe("mergeCallEvent", () => {
  const req = {
    type: "approval_required" as const,
    call_id: "c1",
    server: "zz-notes",
    tool: "search_notes",
    args: { query: "x" },
    destination: "notes.example.com",
    leaves_machine: true,
    expires_at: "2026-01-01T00:10:00Z",
  };
  test("approval_required adds a pending call; ext_call updates it", () => {
    const one = mergeCallEvent([], req);
    expect(one).toHaveLength(1);
    expect(one[0].approval).toBe("pending");
    const two = mergeCallEvent(one, { type: "ext_call", call_id: "c1", approval: "approved", decided_via: "user", receipt: "confirmed" });
    expect(two[0]).toMatchObject({ approval: "approved", decided_via: "user", receipt: "confirmed" });
  });
  test("a replayed approval_required never turns a decided call back to pending", () => {
    const decided = mergeCallEvent(mergeCallEvent([], req), { type: "ext_call", call_id: "c1", approval: "denied", decided_via: "user" });
    expect(mergeCallEvent(decided, req)[0].approval).toBe("denied");
  });
  test("ext_call for an unknown id is ignored", () => {
    expect(mergeCallEvent([], { type: "ext_call", call_id: "zz", approval: "approved" })).toEqual([]);
  });
});

test.describe("announce", () => {
  test("appearance and one minute", () => {
    const c = call();
    const t = Date.parse(c.expires_at) - 600_000;
    expect(announce.appeared(c, t)).toBe(
      "Approval needed: zz-notes wants to run search_notes. It is denied automatically in 10 minutes."
    );
    expect(announce.oneMinute(c)).toBe("One minute left to answer search_notes on zz-notes.");
  });
});

test.describe("extOriginAllowed", () => {
  const same = new Headers({ host: "127.0.0.1:3001", origin: "http://127.0.0.1:3001", "sec-fetch-site": "same-origin" });
  const evil = new Headers({ host: "127.0.0.1:3001", origin: "http://evil.example", "sec-fetch-site": "cross-site" });
  const guarded: [string, string][] = [
    ["POST", "mcp-servers"],
    ["PUT", `mcp-servers/${U}`],
    ["DELETE", `mcp-servers/${U}`],
    ["POST", `mcp-servers/${U}/test`],
    ["PUT", `mcp-servers/${U}/enabled`],
    ["PUT", `mcp-servers/${U}/tools/x`],
    ["PUT", `threads/${U}/mcp-servers`],
    ["POST", `threads/${U}/ext-calls/${C}`],
  ];
  test("GET mcp-servers is allowed from anywhere", () => {
    expect(extOriginAllowed("GET", "mcp-servers", evil)).toBe(true);
  });
  for (const [m, p] of guarded) {
    test(`${m} ${p} is refused cross-site and allowed same-origin`, () => {
      expect(extOriginAllowed(m, p, evil)).toBe(false);
      expect(extOriginAllowed(m, p, same)).toBe(true);
    });
  }
  test("unrelated paths are untouched", () => {
    expect(extOriginAllowed("POST", "transactions", evil)).toBe(true);
    expect(extOriginAllowed("GET", `threads/${U}`, evil)).toBe(true);
    expect(extOriginAllowed("POST", `threads/${U}/stream`, evil)).toBe(true);
  });
});
