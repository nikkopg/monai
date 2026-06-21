/**
 * Server-side catch-all proxy route handler.
 *
 * Proxies all /api/* requests to the FastAPI backend, injecting the
 * MONAI_API_KEY header server-side. The key is read from process.env
 * on the server — it never reaches the browser JS bundle (D-07, T-01-06).
 *
 * IMPORTANT: Never expose the key via a NEXT_PUBLIC_ prefixed env var — that
 * prefix bakes the value into the browser bundle. This file must remain a
 * server component (no "use client" directive).
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.MONAI_API || "http://127.0.0.1:8001";
const API_KEY = process.env.MONAI_API_KEY || "";

/**
 * Forward a Next.js request to the FastAPI backend with the injected API key.
 *
 * @param req     - Incoming Next.js request
 * @param segments - Catch-all path segments after /api/ (e.g. ["transactions"])
 */
async function forwardRequest(
  req: NextRequest,
  segments: string[]
): Promise<NextResponse> {
  // Reconstruct target URL: backend + path segments + original query string
  const path = segments.join("/");
  const search = req.nextUrl.search;
  const targetUrl = `${BACKEND}/${path}${search}`;

  // Copy incoming request headers and inject the API key
  const headers = new Headers(req.headers);
  headers.set("MONAI_API_KEY", API_KEY);
  // Remove the host header so the backend sees its own host, not the Next.js host
  headers.delete("host");

  // Read body for methods that carry one (not GET/HEAD)
  let body: ArrayBuffer | null = null;
  const method = req.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    body = await req.arrayBuffer();
  }

  const upstream = await fetch(targetUrl, {
    method,
    headers,
    body: body !== null ? body : undefined,
    // Do not follow redirects — pass them through to the client
    redirect: "manual",
  });

  // Stream response body back to the client
  const responseBody = await upstream.arrayBuffer();
  const responseHeaders = new Headers(upstream.headers);

  return new NextResponse(responseBody, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

// ---------------------------------------------------------------------------
// HTTP method exports — Next.js App Router requires named exports per method
// ---------------------------------------------------------------------------

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ proxy: string[] }> }
): Promise<NextResponse> {
  const { proxy } = await params;
  return forwardRequest(req, proxy);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ proxy: string[] }> }
): Promise<NextResponse> {
  const { proxy } = await params;
  return forwardRequest(req, proxy);
}

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ proxy: string[] }> }
): Promise<NextResponse> {
  const { proxy } = await params;
  return forwardRequest(req, proxy);
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ proxy: string[] }> }
): Promise<NextResponse> {
  const { proxy } = await params;
  return forwardRequest(req, proxy);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ proxy: string[] }> }
): Promise<NextResponse> {
  const { proxy } = await params;
  return forwardRequest(req, proxy);
}
