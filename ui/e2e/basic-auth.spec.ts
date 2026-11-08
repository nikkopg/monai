import { test, expect } from "@playwright/test";
import { NextRequest } from "next/server";
import { GET } from "../app/api/[...proxy]/route";
import { POST as loginPost } from "../app/auth/login/route";
import { POST as logoutPost } from "../app/auth/logout/route";
import { middleware } from "../middleware";
import { checkBasic, safeNext, signSession, verifySession, SESSION_COOKIE } from "../app/lib/basicAuth";
import { UI_PASSWORD } from "../playwright.config";

// Synthetic values only.
const PW = "pw-synthetic";
const API = "api-synthetic";
const APPR = "appr-synthetic";
const basic = (u: string, p: string) => "Basic " + btoa(`${u}:${p}`);

test.describe("helper", () => {
  test("right user and password is ok", async () => {
    expect(await checkBasic(basic("monai", PW), PW, API, APPR)).toBe("ok");
  });
  test("scheme is case-insensitive", async () => {
    expect(await checkBasic("basic " + btoa(`monai:${PW}`), PW, API, APPR)).toBe("ok");
  });
  test("wrong password, wrong user, missing or garbage header are unauthorized", async () => {
    expect(await checkBasic(basic("monai", "nope"), PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic(basic("admin", PW), PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic(null, PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("", PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("Basic !!!", PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("Basic " + btoa("nocolon"), PW, API, APPR)).toBe("unauthorized");
    expect(await checkBasic("Bearer " + PW, PW, API, APPR)).toBe("unauthorized");
  });
  test("an unset password is locked whatever the header", async () => {
    expect(await checkBasic(basic("monai", ""), "", API, APPR)).toBe("locked");
    expect(await checkBasic(null, "", API, APPR)).toBe("locked");
  });
  test("a password equal to either key is locked even with matching credentials", async () => {
    expect(await checkBasic(basic("monai", API), API, API, APPR)).toBe("locked");
    expect(await checkBasic(basic("monai", APPR), APPR, API, APPR)).toBe("locked");
  });
  test("a non-ASCII password matches as UTF-8", async () => {
    const pw = "pässwörd-日本-synthetic"; // pii-ok synthetic
    const utf8 = (u: string, p: string) =>
      "Basic " + btoa(String.fromCharCode.apply(null, Array.from(new TextEncoder().encode(`${u}:${p}`))));
    expect(await checkBasic(utf8("monai", pw), pw, API, APPR)).toBe("ok");
    expect(await checkBasic(utf8("monai", "pässwörd"), pw, API, APPR)).toBe("unauthorized");
  });
  test("empty keys do not lock a set password", async () => {
    expect(await checkBasic(basic("monai", PW), PW, "", "")).toBe("ok");
  });
});

// Route-level check (CR-01 defence in depth): the proxy refuses on its own, so
// the key is never injected if the middleware is skipped. A reachable backend
// would answer 200/404, never 401/503, so these cannot pass by accident.
test.describe("proxy route", () => {
  const call = (authz?: string) =>
    GET(new NextRequest("http://localhost/api/accounts", { headers: authz ? { authorization: authz } : {} }), {
      params: Promise.resolve({ proxy: ["accounts"] }),
    });
  test("refuses without credentials and when locked", async () => {
    const prev = process.env.MONAI_UI_PASSWORD;
    try {
      process.env.MONAI_UI_PASSWORD = PW;
      const r = await call();
      expect(r.status).toBe(401);
      expect(r.headers.get("www-authenticate")).toContain('Basic realm="monai"');
      expect((await call(basic("monai", "nope"))).status).toBe(401);
      process.env.MONAI_UI_PASSWORD = "";
      expect((await call()).status).toBe(503);
    } finally {
      if (prev === undefined) delete process.env.MONAI_UI_PASSWORD;
      else process.env.MONAI_UI_PASSWORD = prev;
    }
  });
  test("accepts a valid session cookie, refuses a tampered or expired one", async () => {
    const prev = process.env.MONAI_UI_PASSWORD;
    const now = Math.floor(Date.now() / 1000);
    // An already-aborted signal: the gate passes, then fetch aborts in-process
    // (499), so nothing leaves for the live backend on :8001.
    const withCookie = (v: string, signal?: AbortSignal) =>
      GET(new NextRequest("http://localhost/api/accounts", { headers: { cookie: `${SESSION_COOKIE}=${v}` }, signal }), {
        params: Promise.resolve({ proxy: ["accounts"] }),
      });
    try {
      process.env.MONAI_UI_PASSWORD = PW;
      const good = await signSession(PW, now + 600);
      expect((await withCookie(good, AbortSignal.abort())).status).toBe(499);
      expect((await withCookie(good.slice(0, -1) + (good.endsWith("A") ? "B" : "A"))).status).toBe(401);
      expect((await withCookie(await signSession(PW, now - 5))).status).toBe(401);
    } finally {
      if (prev === undefined) delete process.env.MONAI_UI_PASSWORD;
      else process.env.MONAI_UI_PASSWORD = prev;
    }
  });
});

test.describe("session token", () => {
  const now = 1_800_000_000;
  test("a fresh token verifies; tampering, expiry, rotation and junk do not", async () => {
    const t = await signSession(PW, now + 100);
    expect(await verifySession(t, PW, now)).toBe(true);
    const [exp, mac] = t.split(".");
    const flip = mac.slice(0, -1) + (mac.endsWith("A") ? "B" : "A");
    expect(await verifySession(`${exp}.${flip}`, PW, now)).toBe(false);
    expect(await verifySession(`${Number(exp) + 1}.${mac}`, PW, now)).toBe(false);
    expect(await verifySession(t, PW, now + 100)).toBe(false);
    expect(await verifySession(t, "other-synthetic", now)).toBe(false);
    for (const bad of ["", "abc", "123", "123.", ".abc", "1.2.3", "x1." + mac, `${exp}.${mac}A`, `${exp}.${mac.slice(1)}`, `${exp}.${"é".repeat(43)}`]) {
      expect(await verifySession(bad, PW, now), JSON.stringify(bad)).toBe(false);
    }
  });
});

test.describe("safeNext", () => {
  test("keeps same-origin paths, rejects everything else", () => {
    for (const ok of ["/cashflow", "/records?x=1#h"]) expect(safeNext(ok)).toBe(ok);
    const bad = [null, undefined, 5, "", "cashflow", "//evil.example", "/\\evil.example", "\\\\evil.example", "/\\/evil.example",
      "https://evil.example", "http:/evil.example", "javascript:alert(1)", " /cashflow", "/\tx", "/a\nb", "/\u0000x", "/café",
      "/login", "/login?next=/x", "/auth/login", "/" + "a".repeat(2100)];
    for (const b of bad) expect(safeNext(b), JSON.stringify(b)).toBe("/cashflow");
  });
});

// Middleware called directly; env restored in finally.
test.describe("middleware", () => {
  const run = async (path: string, init: { headers?: Record<string, string>; method?: string } = {}, pw: string | null = PW) => {
    const prev = process.env.MONAI_UI_PASSWORD;
    try {
      if (pw === null) delete process.env.MONAI_UI_PASSWORD;
      else process.env.MONAI_UI_PASSWORD = pw;
      return await middleware(new NextRequest(`http://localhost${path}`, init));
    } finally {
      if (prev === undefined) delete process.env.MONAI_UI_PASSWORD;
      else process.env.MONAI_UI_PASSWORD = prev;
    }
  };
  const ck = async (exp: number, pw = PW) => ({ cookie: `${SESSION_COOKIE}=${await signSession(pw, exp)}` });
  const future = () => Math.floor(Date.now() / 1000) + 600;

  test("valid cookie or Basic passes", async () => {
    expect((await run("/records", { headers: await ck(future()) })).headers.get("x-middleware-next")).toBe("1");
    expect((await run("/records", { headers: { authorization: basic("monai", PW) } })).headers.get("x-middleware-next")).toBe("1");
  });
  test("unauthenticated pages redirect to /login with next; /api stays 401", async () => {
    const r = await run("/records?x=1");
    expect(r.status).toBe(307);
    const loc = new URL(r.headers.get("location")!);
    expect(loc.pathname + loc.search).toBe("/login?next=%2Frecords%3Fx%3D1");
    const a = await run("/api/accounts");
    expect(a.status).toBe(401);
    expect(a.headers.get("www-authenticate")).toContain('Basic realm="monai"');
  });
  test("expired or tampered cookie redirects", async () => {
    expect((await run("/records", { headers: await ck(Math.floor(Date.now() / 1000) - 5) })).status).toBe(307);
    const c = await ck(future());
    expect((await run("/records", { headers: { cookie: c.cookie + "x" } })).status).toBe(307);
    expect((await run("/records", { headers: await ck(future(), "other-synthetic") })).status).toBe(307);
  });
  test("an unset or key-reused password locks everything, /login included", async () => {
    for (const path of ["/records", "/api/accounts", "/login"]) {
      expect((await run(path, {}, null)).status, path).toBe(503);
      expect((await run(path, {}, "")).status, path).toBe(503);
    }
    const prev = process.env.MONAI_API_KEY;
    process.env.MONAI_API_KEY = PW;
    try {
      expect((await run("/records")).status).toBe(503);
    } finally {
      if (prev === undefined) delete process.env.MONAI_API_KEY;
      else process.env.MONAI_API_KEY = prev;
    }
  });
  test("sign-in paths pass unauthenticated, variants do not", async () => {
    expect((await run("/login")).headers.get("x-middleware-next")).toBe("1");
    expect((await run("/auth/login", { method: "POST" })).headers.get("x-middleware-next")).toBe("1");
    expect((await run("/auth/logout", { method: "POST" })).headers.get("x-middleware-next")).toBe("1");
    expect((await run("/login/")).status).toBe(307);
    expect((await run("/Login")).status).toBe(307);
    expect((await run("/auth/login/x")).status).toBe(307);
  });
  test("authenticated /login redirects to a sanitised next", async () => {
    const headers = await ck(future());
    expect(new URL((await run("/login?next=/records", { headers })).headers.get("location")!).pathname).toBe("/records");
    expect(new URL((await run("/login?next=//evil.example", { headers })).headers.get("location")!).pathname).toBe("/cashflow");
  });
});

test.describe("login route", () => {
  const send = async (fields: Record<string, string>, headers: Record<string, string> = { origin: "http://localhost", host: "localhost" }, pw: string | null = PW, url = "http://localhost/auth/login") => {
    const prev = process.env.MONAI_UI_PASSWORD;
    try {
      if (pw === null) delete process.env.MONAI_UI_PASSWORD;
      else process.env.MONAI_UI_PASSWORD = pw;
      return await loginPost(new NextRequest(url, { method: "POST", headers, body: new URLSearchParams(fields) }));
    } finally {
      if (prev === undefined) delete process.env.MONAI_UI_PASSWORD;
      else process.env.MONAI_UI_PASSWORD = prev;
    }
  };
  test("right password with remember sets a 30-day signed cookie", async () => {
    const r = await send({ password: PW, remember: "on", next: "/records?x=1" });
    expect(r.status).toBe(303);
    expect(r.headers.get("location")).toBe("/records?x=1");
    const sc = r.headers.get("set-cookie")!;
    expect(sc).toContain("HttpOnly");
    expect(sc.toLowerCase()).toContain("samesite=strict");
    expect(sc).toContain("Path=/");
    expect(sc).toContain("Max-Age=2592000");
    expect(sc).not.toContain("Secure");
    const token = new RegExp(`${SESSION_COOKIE}=([^;]+)`).exec(sc)![1];
    expect(await verifySession(token, PW)).toBe(true);
    const exp = Number(token.split(".")[0]);
    expect(exp - Date.now() / 1000).toBeGreaterThan(29 * 86400);
  });
  test("without remember: session cookie with a 12h signed expiry", async () => {
    const r = await send({ password: PW });
    const sc = r.headers.get("set-cookie")!;
    expect(sc).not.toMatch(/max-age|expires/i);
    expect(r.headers.get("location")).toBe("/cashflow");
    const token = new RegExp(`${SESSION_COOKIE}=([^;]+)`).exec(sc)![1];
    const left = Number(token.split(".")[0]) - Date.now() / 1000;
    expect(left).toBeGreaterThan(11 * 3600);
    expect(left).toBeLessThanOrEqual(12 * 3600 + 5);
  });
  test("Secure on https", async () => {
    expect((await send({ password: PW }, undefined, PW, "https://localhost/auth/login")).headers.get("set-cookie")).toContain("Secure");
    const h = { origin: "http://localhost", host: "localhost", "x-forwarded-proto": "https" };
    expect((await send({ password: PW }, h)).headers.get("set-cookie")).toContain("Secure");
  });
  test("wrong password goes back to /login, no cookie, password echoed nowhere", async () => {
    const wrong = "wrong-synthetic-secret";
    const r = await send({ password: wrong, next: "/records" });
    expect(r.status).toBe(303);
    expect(r.headers.get("location")).toBe("/login?error=1&next=%2Frecords");
    expect(r.headers.get("set-cookie")).toBeNull();
    expect(Array.from(r.headers.values()).join("\n")).not.toContain(wrong);
  });
  test("foreign or missing origin is 403; same-host Referer is accepted", async () => {
    expect((await send({ password: PW }, { origin: "http://evil.example", host: "localhost" })).status).toBe(403);
    expect((await send({ password: PW }, { origin: "null", host: "localhost" })).status).toBe(403);
    const none = await send({ password: PW }, { host: "localhost" });
    expect(none.status).toBe(403);
    expect(none.headers.get("set-cookie")).toBeNull();
    expect((await send({ password: PW }, { referer: "http://localhost/login", host: "localhost" })).status).toBe(303);
    expect((await send({ password: PW }, { referer: "http://evil.example/login", host: "localhost" })).status).toBe(403);
  });
  test("locked answers 503", async () => {
    const r = await send({ password: PW }, undefined, "");
    expect(r.status).toBe(503);
    expect(await r.text()).toContain("monai UI locked");
  });
});

test.describe("logout route", () => {
  const out = (headers: Record<string, string>) => logoutPost(new NextRequest("http://localhost/auth/logout", { method: "POST", headers }));
  test("same-origin clears the cookie and goes to /login", async () => {
    const r = await out({ origin: "http://localhost", host: "localhost" });
    expect(r.status).toBe(303);
    expect(r.headers.get("location")).toBe("/login");
    const sc = r.headers.get("set-cookie")!;
    expect(sc).toContain(`${SESSION_COOKIE}=;`);
    expect(sc).toContain("Max-Age=0");
    expect(sc).toContain("HttpOnly");
    expect(sc.toLowerCase()).toContain("samesite=strict");
    expect(sc).toContain("Path=/");
  });
  test("foreign or missing origin is 403 without touching the cookie", async () => {
    for (const h of [{ origin: "http://evil.example", host: "localhost" }, { host: "localhost" }] as Record<string, string>[]) {
      const r = await out(h);
      expect(r.status).toBe(403);
      expect(r.headers.get("set-cookie")).toBeNull();
    }
  });
});

// Node fetch, not the `request`/`page` fixtures: those answer the challenge from
// the config credentials and would pass for the wrong reason. Never request /api
// with credentials here: the dev proxy defaults to the live backend on 8001.
test.describe("server", () => {
  test.setTimeout(60_000);
  const get = (baseURL: string | undefined, path: string, authz?: string) =>
    fetch(new URL(path, baseURL), { headers: authz ? { authorization: authz } : {}, redirect: "manual" });

  const toLogin = (r: Response) => {
    expect(r.status).toBe(307);
    const loc = new URL(r.headers.get("location")!);
    expect(loc.pathname).toBe("/login");
    expect(loc.searchParams.get("next")).toBe("/");
  };
  test("no credentials on a page redirects to /login", async ({ baseURL }) => {
    toLogin(await get(baseURL, "/"));
  });
  test("/api without credentials keeps the Basic challenge", async ({ baseURL }) => {
    const r = await get(baseURL, "/api/accounts");
    expect(r.status).toBe(401);
    expect(r.headers.get("www-authenticate")).toContain('Basic realm="monai"');
  });
  test("wrong password and wrong username redirect to /login", async ({ baseURL }) => {
    toLogin(await get(baseURL, "/", basic("monai", "nope")));
    toLogin(await get(baseURL, "/", basic("admin", UI_PASSWORD)));
  });
  test("right credentials get the page", async ({ baseURL }) => {
    expect((await get(baseURL, "/chat", basic("monai", UI_PASSWORD))).status).toBe(200);
  });
  test("/api without credentials is 401 before the proxy runs", async ({ baseURL }) => {
    expect((await get(baseURL, "/api/accounts")).status).toBe(401);
  });
  // CVE-2025-29927: this header made old Next skip the middleware entirely.
  const BYPASS = { "x-middleware-subrequest": "middleware:middleware:middleware:middleware:middleware" };
  test("the x-middleware-subrequest bypass header does not skip the gate", async ({ baseURL }) => {
    const fetchBypass = (path: string) => fetch(new URL(path, baseURL), { headers: BYPASS, redirect: "manual" });
    toLogin(await fetchBypass("/"));
    expect((await fetchBypass("/api/accounts")).status).toBe(401);
  });
  test("GET /auth/logout is 405", async ({ baseURL }) => {
    expect((await get(baseURL, "/auth/logout", basic("monai", UI_PASSWORD))).status).toBe(405);
  });
  // Sign in over HTTP like a browser would, then use the cookie. Pages only:
  // the dev proxy defaults to the live backend, so never /api with a valid cookie.
  test("sign-in round trip: cookie opens pages and bounces /login", async ({ baseURL }) => {
    const origin = new URL(baseURL!).origin;
    const r = await fetch(new URL("/auth/login", baseURL), {
      method: "POST",
      headers: { origin },
      body: new URLSearchParams({ password: UI_PASSWORD, next: "/chat" }),
      redirect: "manual",
    });
    expect(r.status).toBe(303);
    expect(r.headers.get("location")).toBe("/chat");
    const cookie = r.headers.get("set-cookie")!.split(";")[0];
    expect((await fetch(new URL("/records", baseURL), { headers: { cookie }, redirect: "manual" })).status).toBe(200);
    const l = await fetch(new URL("/login", baseURL), { headers: { cookie }, redirect: "manual" });
    expect(l.status).toBe(307);
    expect(new URL(l.headers.get("location")!).pathname).toBe("/cashflow");
  });
});
