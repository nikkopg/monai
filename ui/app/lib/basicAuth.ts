/**
 * UI gate: HTTP Basic or a signed session cookie (Phase 40.1, D-08..D-10).
 * Compares SHA-256 digests of both sides (fixed length, so no length leak) with
 * an XOR-accumulate and no early exit; only Edge-runtime built-ins, no node:crypto.
 */
import type { NextRequest } from "next/server";

const enc = new TextEncoder();
const sha = async (s: string) => new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(s)));
const same = (a: Uint8Array, b: Uint8Array) => a.reduce((d, x, i) => d | (x ^ b[i]), 0) === 0;

export type BasicVerdict = "ok" | "unauthorized" | "locked";
export const BASIC_USER = "monai";

// Fail closed: an unset password, or one reused from a backend key, locks the UI.
export const isLocked = (password: string, apiKey: string, approverKey: string) =>
  !password || (!!apiKey && password === apiKey) || (!!approverKey && password === approverKey);

export async function verifyPassword(given: string, password: string): Promise<boolean> {
  return same(await sha(given), await sha(password));
}

export async function checkBasic(
  authz: string | null,
  password: string,
  apiKey: string,
  approverKey: string
): Promise<BasicVerdict> {
  if (isLocked(password, apiKey, approverKey)) return "locked";
  const m = /^Basic (.+)$/i.exec(authz ?? "");
  let user = "";
  let pass = "";
  try {
    // atob yields a binary string: rebuild the bytes and decode them as UTF-8
    // so a non-ASCII password matches what the browser encoded.
    const d = new TextDecoder().decode(Uint8Array.from(atob(m?.[1] ?? ""), (c) => c.charCodeAt(0)));
    const i = d.indexOf(":");
    if (i >= 0) {
      user = d.slice(0, i);
      pass = d.slice(i + 1);
    }
  } catch {
    /* garbage decodes to empty credentials */
  }
  // Both digest pairs are computed before combining, so nothing short-circuits.
  const okUser = same(await sha(user), await sha(BASIC_USER));
  const okPass = await verifyPassword(pass, password);
  return okUser && okPass ? "ok" : "unauthorized";
}

/**
 * The 401/503 response init for a non-ok verdict, shared by the middleware and
 * the /api proxy route so the route still refuses if the middleware is skipped
 * (CVE-2025-29927 defence in depth). Returns null for "ok".
 */
export function basicDenial(verdict: BasicVerdict): { body: string; init: ResponseInit } | null {
  if (verdict === "ok") return null;
  if (verdict === "locked") {
    return {
      body: "monai UI locked: set MONAI_UI_PASSWORD in .env (it must differ from MONAI_API_KEY and MONAI_APPROVER_KEY), then restart the frontend",
      init: { status: 503, headers: { "Cache-Control": "no-store" } },
    };
  }
  return {
    body: "Authentication required",
    init: { status: 401, headers: { "WWW-Authenticate": 'Basic realm="monai", charset="UTF-8"', "Cache-Control": "no-store" } },
  };
}

// ---------------------------------------------------------------------------
// Session cookie: "<exp>.<mac>", exp = Unix seconds, mac = base64url(HMAC-SHA256(exp)).
// The key is PBKDF2-derived from MONAI_UI_PASSWORD so a stolen cookie does not
// make offline password guessing cheap; changing the password invalidates every
// cookie. The password itself is never in the cookie.
// ---------------------------------------------------------------------------
export const SESSION_COOKIE = "monai_session";

let keySlot: { pw: string; key: Promise<CryptoKey> } | null = null;
function sessionKey(password: string): Promise<CryptoKey> {
  if (keySlot?.pw !== password) {
    const key = crypto.subtle
      .importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"])
      .then((base) =>
        crypto.subtle.deriveKey(
          { name: "PBKDF2", hash: "SHA-256", salt: enc.encode("monai-ui-session-v1"), iterations: 600000 },
          base,
          { name: "HMAC", hash: "SHA-256" },
          false,
          ["sign"]
        )
      );
    keySlot = { pw: password, key };
  }
  return keySlot.key;
}

export async function signSession(password: string, expSec: number): Promise<string> {
  const exp = String(expSec);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", await sessionKey(password), enc.encode(exp)));
  return `${exp}.${btoa(String.fromCharCode.apply(null, Array.from(mac))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}`;
}

export async function verifySession(
  token: string,
  password: string,
  nowSec = Math.floor(Date.now() / 1000)
): Promise<boolean> {
  try {
    const m = /^(\d{1,15})\.[A-Za-z0-9_-]{43}$/.exec(token);
    if (!m || Number(m[1]) <= nowSec) return false;
    return same(await sha(token), await sha(await signSession(password, Number(m[1]))));
  } catch {
    return false;
  }
}

/** A redirect target that can only be a same-origin path (never /login or /auth/*, to avoid loops). */
export function safeNext(raw: unknown): string {
  const dflt = "/cashflow";
  if (typeof raw !== "string" || raw.length > 2048 || !/^[\x21-\x7E]+$/.test(raw) || raw.includes("\\")) return dflt;
  if (raw[0] !== "/" || raw[1] === "/") return dflt;
  try {
    const u = new URL(raw, "http://n.invalid");
    if (u.origin !== "http://n.invalid" || u.pathname === "/login" || u.pathname.startsWith("/auth/")) return dflt;
  } catch {
    return dflt;
  }
  return raw;
}

/** CSRF guard for the form POSTs: Origin (Referer only when Origin is absent) must be the Host. */
export function sameOrigin(headers: Headers): boolean {
  const host = (headers.get("host") ?? "").toLowerCase();
  const src = headers.get("origin") ?? headers.get("referer");
  if (!host || !src) return false;
  try {
    return new URL(src).host.toLowerCase() === host;
  } catch {
    return false; // includes Origin "null"
  }
}

export async function checkGate(
  authz: string | null,
  cookie: string | undefined,
  password: string,
  apiKey: string,
  approverKey: string,
  nowSec?: number
): Promise<BasicVerdict> {
  if (isLocked(password, apiKey, approverKey)) return "locked";
  if (cookie && (await verifySession(cookie, password, nowSec))) return "ok";
  return checkBasic(authz, password, apiKey, approverKey);
}

/** Verdict for a request from the process env, read per request. */
export const checkGateEnv = (req: NextRequest) =>
  checkGate(
    req.headers.get("authorization"),
    req.cookies.get(SESSION_COOKIE)?.value,
    process.env.MONAI_UI_PASSWORD ?? "",
    process.env.MONAI_API_KEY ?? "",
    process.env.MONAI_APPROVER_KEY ?? ""
  );
