/**
 * HTTP Basic gate in front of every page and the /api proxy (Phase 40.1, D-08).
 * The proxy injects MONAI_API_KEY for any caller, so this runs first and lets a
 * request through only with MONAI_UI_PASSWORD. Fails closed (503) when that is
 * unset or reused from a backend key. Env is read per request, never inlined.
 */
import { NextRequest, NextResponse } from "next/server";

import { checkBasic } from "./app/lib/basicAuth";

// /_next/ is build assets, the image optimiser and dev HMR: no ledger data.
export const config = { matcher: "/((?!_next/|favicon.ico).*)" };

export async function middleware(req: NextRequest) {
  const verdict = await checkBasic(
    req.headers.get("authorization"),
    process.env.MONAI_UI_PASSWORD ?? "",
    process.env.MONAI_API_KEY ?? "",
    process.env.MONAI_APPROVER_KEY ?? ""
  );
  if (verdict === "ok") return NextResponse.next();
  if (verdict === "locked") {
    return new NextResponse(
      "monai UI locked: set MONAI_UI_PASSWORD in .env (it must differ from MONAI_API_KEY and MONAI_APPROVER_KEY), then restart the frontend",
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="monai", charset="UTF-8"', "Cache-Control": "no-store" },
  });
}
