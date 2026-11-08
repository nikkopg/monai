/**
 * Form sign-in: POST /auth/login (not under /api, which is proxied to the
 * backend). A right password sets the signed session cookie and redirects to a
 * same-origin `next`; a wrong one goes back to /login?error=1. The password is
 * never logged, echoed or put in a URL. Locations are RELATIVE on purpose:
 * req.url can carry the bind host (127.0.0.1) while the browser used localhost.
 */
import { NextRequest, NextResponse } from "next/server";

import { basicDenial, isLocked, safeNext, sameOrigin, signSession, verifyPassword, SESSION_COOKIE } from "../../lib/basicAuth";

const NO_STORE = { "Cache-Control": "no-store" };
const DAY = 86400;

const redirect = (to: string) => new NextResponse(null, { status: 303, headers: { Location: to, ...NO_STORE } });

export async function POST(req: NextRequest) {
  if (!sameOrigin(req.headers)) return new NextResponse("Sign-in must come from monai itself.", { status: 403, headers: NO_STORE });
  const password = process.env.MONAI_UI_PASSWORD ?? "";
  if (isLocked(password, process.env.MONAI_API_KEY ?? "", process.env.MONAI_APPROVER_KEY ?? "")) {
    const d = basicDenial("locked")!;
    return new NextResponse(d.body, d.init);
  }
  let form: FormData | null = null;
  try {
    form = await req.formData();
  } catch {
    /* an unreadable body is an empty form */
  }
  const given = form?.get("password");
  const remember = form?.has("remember") ?? false;
  const next = safeNext(form?.get("next"));

  if (typeof given !== "string" || !(await verifyPassword(given, password))) {
    return redirect(`/login?error=1&next=${encodeURIComponent(next)}`);
  }
  const res = redirect(next);
  res.cookies.set(SESSION_COOKIE, await signSession(password, Math.floor(Date.now() / 1000) + (remember ? 30 * DAY : 12 * 3600)), {
    httpOnly: true,
    sameSite: "strict",
    path: "/",
    secure: req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https",
    ...(remember ? { maxAge: 30 * DAY } : {}),
  });
  return res;
}
