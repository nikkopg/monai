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
  { method: "GET", path: /^proposals$/, search: /^(\?status=pending)?$/ },
  { method: "POST", path: new RegExp(`^proposals/${UUID}/approve$`), search: /^$/ },
  { method: "POST", path: new RegExp(`^proposals/${UUID}/reject$`), search: /^$/ },
  { method: "PATCH", path: new RegExp(`^proposals/${UUID}/rows/\\d{1,6}$`), search: /^$/ },
];

/** True when the proxy may attach MONAI_APPROVER_KEY to this request. */
export function approverHeaderAllowed(method: string, path: string, search: string): boolean {
  const m = method.toUpperCase();
  return RULES.some((r) => r.method === m && r.path.test(path) && r.search.test(search));
}
