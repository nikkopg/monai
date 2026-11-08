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

export async function middleware(req: NextRequest) {
  const verdict = await checkGateEnv(req);
  const denial = basicDenial(verdict);
  if (verdict === "locked") return new NextResponse(denial!.body, denial!.init);
  const { pathname, search, searchParams } = req.nextUrl;
  if (verdict === "ok") {
    if (pathname === "/login" && req.method === "GET") {
      return NextResponse.redirect(new URL(safeNext(searchParams.get("next")), req.nextUrl));
    }
    return NextResponse.next();
  }
  if (OPEN.has(pathname)) return NextResponse.next();
  if (pathname === "/api" || pathname.startsWith("/api/")) return new NextResponse(denial!.body, denial!.init);
  const to = req.nextUrl.clone();
  to.pathname = "/login";
  to.search = new URLSearchParams({ next: pathname + search }).toString();
  return NextResponse.redirect(to);
}
