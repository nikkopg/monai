/**
 * HTTP Basic gate in front of every page and the /api proxy (Phase 40.1, D-08).
 * The proxy injects MONAI_API_KEY for any caller, so this runs first and lets a
 * request through only with MONAI_UI_PASSWORD. Fails closed (503) when that is
 * unset or reused from a backend key. Env is read per request, never inlined.
 */
import { NextRequest, NextResponse } from "next/server";

import { basicDenial, checkBasicEnv } from "./app/lib/basicAuth";

// /_next/ is build assets, the image optimiser and dev HMR: no ledger data.
export const config = { matcher: "/((?!_next/|favicon.ico).*)" };

export async function middleware(req: NextRequest) {
  const denial = basicDenial(await checkBasicEnv(req.headers.get("authorization")));
  return denial ? new NextResponse(denial.body, denial.init) : NextResponse.next();
}
