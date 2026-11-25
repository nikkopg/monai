/** Sign out: POST /auth/logout clears the session cookie and returns to /login. */
import { NextRequest, NextResponse } from "next/server";

import { sameOrigin, SESSION_COOKIE } from "../../lib/basicAuth";

export async function POST(req: NextRequest) {
  if (!sameOrigin(req.headers)) {
    return new NextResponse("Sign-out must come from monai itself.", { status: 403, headers: { "Cache-Control": "no-store" } });
  }
  const res = new NextResponse(null, { status: 303, headers: { Location: "/login", "Cache-Control": "no-store" } });
  res.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    sameSite: "strict",
    path: "/",
    secure: req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https",
    maxAge: 0,
  });
  return res;
}
