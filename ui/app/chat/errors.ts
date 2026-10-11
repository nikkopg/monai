// Error copy (34-UI-SPEC section 2). Only these fixed strings are ever rendered
// for a failure; response `detail` and exception text never reach the DOM (D-02).
export const ERROR_COPY: Record<string, { title: string; body: string }> = {
  rate_limit: {
    title: "The model is rate-limited",
    body: "The provider asked monai to slow down. Wait a few seconds, then retry. Nothing was changed.",
  },
  provider_unavailable: {
    title: "The model provider is having trouble",
    body: "The provider returned a server error. Retry in a moment. Nothing was changed.",
  },
  timeout: {
    title: "The model took too long to answer",
    body: "The provider did not respond in time. Retry, or ask a narrower question. Nothing was changed.",
  },
  idle_timeout: {
    title: "The answer stalled",
    body: "No activity, so monai ended the run. Nothing was changed.",
  },
  auth: {
    title: "The model rejected monai's credentials",
    body: "The provider key is missing or invalid. Fix the key in the server settings, then retry.",
  },
  connection: {
    title: "monai can't reach the model",
    body: "The connection to the model provider failed. If you use Ollama, check that it is running, then retry.",
  },
  empty: {
    title: "The model returned no answer",
    body: "It replied with nothing and ran no tools. Retry or rephrase the question.",
  },
  stream_ended: {
    title: "The answer stopped early",
    body: "The connection closed before the answer finished. Nothing was changed.",
  },
  conflict: {
    title: "Another answer is already running",
    body: "This conversation already has a run in progress, possibly in another tab. Wait for it to finish, then ask again.",
  },
  unauthorized: {
    title: "Chat isn't authorized",
    body: "monai has no API key configured for this page. Set the server key, reload, and ask again.",
  },
  unknown: {
    title: "Something went wrong",
    body: "monai hit an unexpected error. Nothing was changed. Retry, and if it keeps happening check the server log.",
  },
};

// Upper bound on the Stop cancel request (WR-02).
export const CANCEL_TIMEOUT_MS = 10_000;

export const TRANSPORT_BODY =
  "The connection to monai failed. Check that the server is running, then retry.";

export type ChatError = {
  code: string;
  model: string | null;
  idleSeconds: number | null;
  transport?: boolean;
};

export function errorCopy(err: ChatError): { title: string; body: string } {
  const c = ERROR_COPY[err.code] ?? ERROR_COPY.unknown;
  if (err.transport) return { title: c.title, body: TRANSPORT_BODY };
  if (err.code === "idle_timeout" && err.idleSeconds !== null) {
    return {
      title: c.title,
      body: `No activity for ${Math.round(err.idleSeconds)} seconds, so monai ended the run. Nothing was changed.`,
    };
  }
  return c;
}
