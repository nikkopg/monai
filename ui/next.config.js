/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy API calls to the FastAPI backend so the browser hits one origin.
  async rewrites() {
    const backend = process.env.MONAI_API || "http://127.0.0.1:8001";
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};
module.exports = nextConfig;
