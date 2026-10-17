const { PHASE_DEVELOPMENT_SERVER } = require("next/constants");

// Content-Security-Policy on every route (D-11). img-src and connect-src are
// the two exfiltration stops: answer markdown cannot load an image or call
// another host even if the renderer were bypassed. 'unsafe-inline' scripts
// remain because Next 14 App Router hydration needs them without a nonce
// middleware (nonce CSP deferred). 'unsafe-eval' is dev-only (React refresh).
module.exports = (phase) => {
  const dev = phase === PHASE_DEVELOPMENT_SERVER;
  const csp = [
    "default-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self'",
    `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  return {
    // The /api/* proxy is handled by the server-side catch-all route handler at
    // ui/app/api/[...proxy]/route.ts, which injects the MONAI_API_KEY header
    // server-side. The rewrites() block is intentionally removed — the route
    // handler now owns /api/* routing (D-07, T-01-06).
    async headers() {
      return [{ source: "/:path*", headers: [{ key: "Content-Security-Policy", value: csp }] }];
    },
  };
};
