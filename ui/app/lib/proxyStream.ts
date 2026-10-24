/**
 * Which upstream paths the proxy must stream instead of buffering, and which
 * statuses must not carry a body. Lives in a lib module because a Next route
 * file may export only route handlers and config.
 */

const THREAD_STREAM = /^threads\/[0-9a-fA-F-]{36}\/stream$/;

/** SSE endpoints: the chat turn and the thread re-attach (36 D-18a). */
export function isStreamPath(path: string): boolean {
  return path === "query-stream" || THREAD_STREAM.test(path);
}

/** The Fetch spec forbids a body on these; `new Response(buf, {status: 204})` throws. */
export function isNullBodyStatus(status: number): boolean {
  return status === 204 || status === 205 || status === 304;
}
