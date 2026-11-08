import type { CSSProperties } from "react";
import { safeNext } from "../lib/basicAuth";
import { btn, input, label, tokens } from "../styles";

export const metadata = { title: "Sign in · monai" };

const t = tokens.color;
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

// Server component on purpose: signing in is a plain HTML form POST, so it works
// with JavaScript off. Mockup: .planning/design/login-mock.html.
export default function LoginPage({ searchParams }: { searchParams: Record<string, string | string[] | undefined> }) {
  const error = first(searchParams.error) === "1";
  const next = safeNext(first(searchParams.next));
  const text = (size: number, color: string, extra: CSSProperties = {}): CSSProperties => ({ fontSize: size, color, ...extra });

  return (
    <div style={{ minHeight: "100vh", display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 28, boxSizing: "border-box" }}>
      <div
        style={{
          width: 480,
          maxWidth: "100%",
          boxSizing: "border-box",
          background: t.panel,
          border: `1px solid ${t.border2}`,
          borderRadius: tokens.radius.xl,
          boxShadow: tokens.shadow.panel,
          padding: "32px 44px",
        }}
      >
        <form method="post" action="/auth/login" style={{ width: "100%" }}>
          <input type="hidden" name="next" value={next} />
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 20 }}>
            <span style={{ fontFamily: tokens.font.serif, fontSize: 30, letterSpacing: "-0.5px", lineHeight: 1 }}>monai</span>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: t.green }} />
          </div>
          <div style={text(12, t.muted2, { letterSpacing: ".12em", textTransform: "uppercase", marginBottom: 4 })}>Sign in</div>
          <h1 style={{ fontFamily: tokens.font.serif, fontWeight: 400, fontSize: 40, lineHeight: 1.1, letterSpacing: "-0.5px", margin: "0 0 6px" }}>
            Welcome back
          </h1>
          <p style={text(14, t.muted3, { margin: "0 0 18px", lineHeight: 1.5 })}>Enter your monai password to open your ledger.</p>
          <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: tokens.radius.lg, padding: "20px 24px" }}>
            <label htmlFor="pw" style={{ ...label, color: t.muted3 }}>
              Password
            </label>
            <input
              id="pw"
              name="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              style={error ? { ...input, borderColor: t.terracotta } : input}
              {...(error ? { "aria-invalid": "true", "aria-describedby": "pw-err" } : {})}
            />
            {error && (
              <div id="pw-err" role="alert" style={text(12, t.terracottaText, { marginTop: 6 })}>
                {"That password didn't match. Try again."}
              </div>
            )}
            <label style={text(13, t.muted3, { display: "flex", alignItems: "center", gap: 8, margin: "12px 0 16px" })}>
              <input type="checkbox" name="remember" defaultChecked style={{ accentColor: t.green, width: 16, height: 16, margin: 0 }} />
              Keep me signed in for 30 days
            </label>
            <button type="submit" className="login-submit" style={{ ...btn, width: "100%" }}>
              Sign in
            </button>
          </div>
          <div style={{ marginTop: 14, padding: "12px 14px", background: t.footerCard, border: `1px solid ${t.border2}`, borderRadius: tokens.radius.md }}>
            <b style={text(13, t.text, { display: "block", fontWeight: 600, marginBottom: 2 })}>Local-first</b>
            <span style={text(12, t.muted3, { lineHeight: 1.45 })}>Your data stays on this machine.</span>
          </div>
        </form>
      </div>
    </div>
  );
}
