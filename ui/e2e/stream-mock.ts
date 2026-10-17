import type { Page } from "@playwright/test";

// Browser-side streamed fetch mock. `route.fulfill` delivers a whole body at once,
// so timing-dependent chat behaviour (drafts, working notes, Stop) needs a real
// ReadableStream. Each script is a list of SSE events with a delay `at` (ms from
// the request); streams are handed out in order and the last script repeats.
// A string `data` such as "[DONE]" is sent raw, anything else as JSON.

export type StreamScript = { data: unknown; at: number }[];

export async function mockStreams(
  page: Page,
  scripts: StreamScript[],
  opts: { keepOpen?: boolean } = {},
) {
  await page.addInitScript(
    ({ scripts, keepOpen }) => {
      const w = window as unknown as { __queryBodies: unknown[] };
      w.__queryBodies = [];
      const real = window.fetch.bind(window);
      const enc = new TextEncoder();
      let n = 0;

      function respond(init?: RequestInit) {
        const script = scripts[Math.min(n++, scripts.length - 1)] ?? [];
        const timers: ReturnType<typeof setTimeout>[] = [];
        const stream = new ReadableStream({
          start(c) {
            let last = 0;
            for (const item of script) {
              last = Math.max(last, item.at);
              timers.push(
                setTimeout(() => {
                  const body = typeof item.data === "string" ? item.data : JSON.stringify(item.data);
                  c.enqueue(enc.encode(`data: ${body}\n\n`));
                }, item.at),
              );
            }
            if (!keepOpen) timers.push(setTimeout(() => c.close(), last + 1));
            // A real fetch rejects the reader with an AbortError on abort.
            init?.signal?.addEventListener("abort", () => {
              timers.forEach(clearTimeout);
              try {
                c.error(new DOMException("The operation was aborted.", "AbortError"));
              } catch {
                /* already closed */
              }
            });
          },
        });
        return Promise.resolve(
          new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } }),
        );
      }

      window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
        const href = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        const path = new URL(href, location.href).pathname;
        const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
        if (method === "POST" && path === "/api/query-stream") {
          try {
            w.__queryBodies.push(JSON.parse(String(init?.body ?? "null")));
          } catch {
            w.__queryBodies.push(null);
          }
          return respond(init);
        }
        if (method === "GET" && /^\/api\/threads\/[^/]+\/stream$/.test(path)) return respond(init);
        if (method === "POST" && /^\/api\/query-stream\/[^/]+\/cancel$/.test(path)) {
          return Promise.resolve(
            new Response('{"rejected": []}', {
              status: 200,
              headers: { "content-type": "application/json" },
            }),
          );
        }
        return real(input, init);
      };
    },
    { scripts, keepOpen: !!opts.keepOpen },
  );
}

/** Request bodies the page POSTed to /api/query-stream, in order. */
export function queryBodies(page: Page): Promise<unknown[]> {
  return page.evaluate(() => (window as unknown as { __queryBodies: unknown[] }).__queryBodies);
}
