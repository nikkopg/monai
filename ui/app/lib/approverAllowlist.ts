/**
 * Single source of which proxied requests may carry the approver key (D-04).
 *
 * Pure on purpose (imports nothing from Next) so a non-browser Playwright spec can
 * import it and pin the truth table. Everything is anchored against the exact
 * forwarded path and the exact query string, so trailing slashes, "..", extra
 * query params, non-UUID ids and case tricks all fall through to "no key".
 *
 * Deliberately absent: proposals/counts and proposals/UUID/confirm (the chat
 * token path must never gain approver scope).
 */

// Case-insensitive hex without the regex `i` flag, so the literal "proposals"
// segment stays case-sensitive.
const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

const RULES: { method: string; path: RegExp; search: RegExp }[] = [
  { method: "GET", path: /^proposals$/, search: /^\?status=pending$/ },
  { method: "POST", path: new RegExp(`^proposals/${UUID}/approve$`), search: /^$/ },
  { method: "POST", path: new RegExp(`^proposals/${UUID}/reject$`), search: /^$/ },
  { method: "PATCH", path: new RegExp(`^proposals/${UUID}/rows/\\d{1,6}$`), search: /^$/ },
];

/** True when the proxy may attach MONAI_APPROVER_KEY to this request. */
export function approverHeaderAllowed(method: string, path: string, search: string): boolean {
  const m = method.toUpperCase();
  return RULES.some((r) => r.method === m && r.path.test(path) && r.search.test(search));
}

// The app is served on loopback only (README "listen on 127.0.0.1"; SSH tunnels
// keep the 127.0.0.1 Host). Any other Host means DNS rebinding or a foreign proxy.
const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

const hostnameOf = (origin: string): string | null => {
  try {
    return new URL(origin).hostname.toLowerCase();
  } catch {
    return null; // includes the opaque "null" origin
  }
};

/**
 * True for a same-origin browser request (or a non-browser client) to a
 * loopback Host. Blocks DNS rebinding (the browser sends the attacker's Host)
 * and cross-site form posts (Sec-Fetch-Site cross-site/same-site, or a foreign
 * Origin from browsers without Fetch Metadata).
 */
export function isLocalSameOrigin(incoming: Headers): boolean {
  const host = (incoming.get("host") ?? "").replace(/:\d+$/, "").toLowerCase();
  if (!LOCAL_HOSTS.has(host)) return false;
  const site = incoming.get("sec-fetch-site");
  if (site !== null && site !== "same-origin" && site !== "none") return false;
  const origin = incoming.get("origin");
  if (origin !== null) {
    const o = hostnameOf(origin);
    if (o === null || !LOCAL_HOSTS.has(o)) return false;
  }
  return true;
}

const UPLOAD_PATH = new RegExp(`^threads/${UUID}/attachments$`);

/**
 * False for a cross-site POST to the attachment upload route (RESEARCH A3). The
 * proxy injects MONAI_API_KEY on every request, so a foreign form post must not
 * reach this route; the check runs before the body is read. Everything else is
 * untouched (`/api/import` has the same gap, a recorded follow-up in 39-DESIGN).
 */
export function uploadOriginAllowed(method: string, path: string, incoming: Headers): boolean {
  if (method.toUpperCase() !== "POST" || !UPLOAD_PATH.test(path)) return true;
  return isLocalSameOrigin(incoming);
}

const EXT_SERVERS_PATH = /^mcp-servers(\/|$)/;
const THREAD_SERVERS_PATH = new RegExp(`^threads/${UUID}/mcp-servers$`);
const EXT_DECISION_PATH = new RegExp(`^threads/${UUID}/ext-calls/${UUID}$`);

/**
 * False for a cross-site request that would create or change an external MCP
 * server (including its stdio command), a thread's server set, or an approval
 * (PC-08). The proxy injects MONAI_API_KEY on every request, so a foreign page
 * must not drive these routes with it; the check runs before the body is read.
 * Reads (GET) and every unrelated path are untouched.
 */
export function extOriginAllowed(method: string, path: string, incoming: Headers): boolean {
  const m = method.toUpperCase();
  const guarded =
    (m !== "GET" && EXT_SERVERS_PATH.test(path)) ||
    (m === "PUT" && THREAD_SERVERS_PATH.test(path)) ||
    (m === "POST" && EXT_DECISION_PATH.test(path));
  return guarded ? isLocalSameOrigin(incoming) : true;
}

/**
 * Marker the Inbox sends on its own list/approve/reject/skip calls. Not a
 * secret (the allowlist and the same-origin check still apply); it only stops
 * the chat card's Reject, which hits an allowlisted path, from picking up
 * approver scope (WR-03).
 */
export const INBOX_SURFACE_HEADER = { "X-Monai-Surface": "inbox" } as const;

const fromInbox = (incoming: Headers) => incoming.get("x-monai-surface") === "inbox";

/**
 * The headers the proxy forwards upstream. Pure so the strip-then-inject order
 * is unit-tested: the API key is always set, the incoming Host is dropped, any
 * client-supplied approver header is deleted BEFORE the server's key is set, and
 * the key is attached only when it is non-empty, the Inbox sent the request,
 * the request is a local same-origin one, and it is allowlisted. The incoming
 * Authorization header (the UI Basic password) is dropped, never forwarded.
 */
export function buildForwardHeaders(
  incoming: Headers,
  apiKey: string,
  approverKey: string,
  method: string,
  path: string,
  search: string
): Headers {
  const headers = new Headers(incoming);
  headers.set("MONAI_API_KEY", apiKey);
  // The backend sees its own host, not the Next.js host.
  headers.delete("host");
  // Node's fetch (undici) throws on an Expect header, which curl adds to bodies
  // over 1 MB; the proxy already holds the whole body, so drop it (else a 502).
  headers.delete("expect");
  // The browser's Basic credential is the UI password; it must never reach the backend.
  headers.delete("authorization");
  // A client-supplied approver header is never forwarded (D-03, T-33-01).
  headers.delete("MONAI_APPROVER_KEY");
  if (
    approverKey &&
    fromInbox(incoming) &&
    isLocalSameOrigin(incoming) &&
    approverHeaderAllowed(method, path, search)
  ) {
    headers.set("MONAI_APPROVER_KEY", approverKey);
  }
  return headers;
}
