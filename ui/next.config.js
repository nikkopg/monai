/** @type {import('next').NextConfig} */
const nextConfig = {
  // The /api/* proxy is handled by the server-side catch-all route handler at
  // ui/app/api/[...proxy]/route.ts, which injects the MONAI_API_KEY header
  // server-side. The rewrites() block is intentionally removed — the route
  // handler now owns /api/* routing (D-07, T-01-06).
};
module.exports = nextConfig;
