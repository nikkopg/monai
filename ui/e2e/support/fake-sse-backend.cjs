// Test double for the production-proxy checks (phase 37 plan 09). A chunked SSE
// backend with FastAPI's headers, so `next start` can be exercised without the
// owner's containers. Synthetic data only. Not part of the app.
//   FAKE_SSE_PORT=18001 node ui/e2e/support/fake-sse-backend.cjs
const http = require("node:http");
const crypto = require("node:crypto");

const PORT = Number(process.env.FAKE_SSE_PORT || 18001);
const RUN_ID = "00000000-0000-4000-8000-0000000000f1";
const frame = (obj) => `data: ${typeof obj === "string" ? obj : JSON.stringify(obj)}\n\n`;
const json = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

// Upload echo (phase 39 plan 14): counts the hits so a refused cross-site POST can
// be shown never to have reached the backend.
let uploadHits = 0;

function streamTurn(res, closeEarly, onClose) {
  res.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
  });
  res.write(frame({ type: "run", run_id: RUN_ID }));
  res.write(frame({ type: "step", msg: "thinking…" }));
  let i = 0;
  const limit = closeEarly ? 3 : 8;
  const timer = setInterval(() => {
    if (i < limit) {
      res.write(frame({ type: "token", delta: `w${i} `, iteration: 0 }));
      i++;
      return;
    }
    clearInterval(timer);
    if (!closeEarly) {
      res.write(
        frame({ type: "answer", text: "w0 w1 w2 w3 w4 w5 w6 w7 done", trace: [], proposals: [] }),
      );
      res.write(frame("[DONE]"));
    }
    res.end();
  }, 400);
  onClose(() => clearInterval(timer));
}

http
  .createServer((req, res) => {
    const path = (req.url || "").split("?")[0];
    if (req.method === "POST" && path === "/query-stream") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => streamTurn(res, body.includes("close-early"), (fn) => res.on("close", fn)));
    } else if (req.method === "POST" && /^\/query-stream\/[^/]+\/cancel$/.test(path)) {
      json(res, 200, { rejected: [] });
    } else if (req.method === "POST" && /^\/threads\/[0-9a-f-]{36}\/attachments$/.test(path)) {
      uploadHits++;
      const hash = crypto.createHash("sha256");
      let bytes = 0;
      req.on("data", (c) => {
        hash.update(c);
        bytes += c.length;
      });
      req.on("end", () =>
        json(res, 200, {
          bytes,
          sha256: hash.digest("hex"),
          has_key: Boolean(req.headers["monai_api_key"]),
          content_type: req.headers["content-type"] || "",
        }),
      );
    } else if (req.method === "GET" && path === "/__upload_hits") {
      json(res, 200, { hits: uploadHits });
    } else if (req.method === "GET" && path === "/threads") {
      json(res, 200, []);
    } else {
      json(res, 404, { detail: "not found" });
    }
  })
  .listen(PORT, "127.0.0.1");
