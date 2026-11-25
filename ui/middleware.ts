/**
 * Gate in front of every page and the /api proxy (Phase 40.1, D-08): HTTP Basic
 * or the signed session cookie from /auth/login. The proxy injects
 * MONAI_API_KEY for any caller, so this runs first and lets a request through
 * only with MONAI_UI_PASSWORD. Fails closed (503) when that is unset or reused
 * from a backend key. Unauthenticated pages go to /login; /api stays 401 with
 * the Basic challenge. Env is read per request, never inlined.
 */
import { NextRequest, NextResponse } from "next/server";

import { basicDenial, checkGateEnv, safeNext } from "./app/lib/basicAuth";

// /_next/ is build assets, the image optimiser and dev HMR: no ledger data.
export const config = { matcher: "/((?!_next/|favicon.ico).*)" };

// Exact paths only, nothing prefix-matched.
const OPEN = new Set(["/login", "/auth/login", "/auth/logout"]);

// Next 14's middleware adapter parses Location with no base, so a relative Location is a 500 (unlike the
// relative ones in app/auth/login/route.ts). req.nextUrl carries the bind host; Host is the one the browser used.
function redirectTo(req: NextRequest, path: string) {
  const url = new URL(path, req.nextUrl);
  const host = req.headers.get("host");
  if (host) {
    url.port = ""; // a host without a port would otherwise keep the bind port
    url.host = host;
  }
  return NextResponse.redirect(url);
}

export async function middleware(req: NextRequest) {
  const verdict = await checkGateEnv(req);
  const denial = basicDenial(verdict);
  if (verdict === "locked") return new NextResponse(denial!.body, denial!.init);
  const { pathname, search, searchParams } = req.nextUrl;
  if (verdict === "ok") {
    if (pathname === "/login" && req.method === "GET") {
      return redirectTo(req, safeNext(searchParams.get("next")));
    }
    return NextResponse.next();
  }
  if (OPEN.has(pathname)) return NextResponse.next();
  if (pathname === "/api" || pathname.startsWith("/api/")) return new NextResponse(denial!.body, denial!.init);
  return redirectTo(req, "/login?" + new URLSearchParams({ next: pathname + search }));
}
