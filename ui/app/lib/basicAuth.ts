/**
 * Pure HTTP Basic verdict for the UI gate (Phase 40.1, D-08..D-10). Compares
 * SHA-256 digests of both sides (fixed length, so no length leak) with an
 * XOR-accumulate and no early exit; only Edge-runtime built-ins, no node:crypto.
 */
const enc = new TextEncoder();
const sha = async (s: string) => new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(s)));
const same = (a: Uint8Array, b: Uint8Array) => a.reduce((d, x, i) => d | (x ^ b[i]), 0) === 0;

export type BasicVerdict = "ok" | "unauthorized" | "locked";
export const BASIC_USER = "monai";

export async function checkBasic(
  authz: string | null,
  password: string,
  apiKey: string,
  approverKey: string
): Promise<BasicVerdict> {
  // Fail closed: an unset password, or one reused from a backend key, locks the UI.
  if (!password || (apiKey && password === apiKey) || (approverKey && password === approverKey)) {
    return "locked";
  }
  const m = /^Basic (.+)$/i.exec(authz ?? "");
  let user = "";
  let pass = "";
  try {
    const d = atob(m?.[1] ?? "");
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
  const okPass = same(await sha(pass), await sha(password));
  return okUser && okPass ? "ok" : "unauthorized";
}
