import { test, expect } from "@playwright/test";
import {
  precheck,
  fileKind,
  localityLines,
  uploadErrorText,
  cardSentence,
  cardTrustLine,
  trustLine,
  chipText,
  pillStatus,
  placeholderFor,
  PURGED_SUFFIX,
  ACCEPT_ATTR,
  type AttachChip,
} from "../app/chat/attachLabels";
import { toolLabel } from "../app/chat/labels";
import { uploadOriginAllowed, buildForwardHeaders } from "../app/lib/approverAllowlist";

// ---------------------------------------------------------------------------
// Phase 39 Plan 11 — non-browser logic spec: pure modules only. Synthetic values.
// ---------------------------------------------------------------------------

const U = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01";
const CLOUD = { local: false, destination: "Ollama Cloud (gemma4:31b-cloud)" };
const CSV_LINE =
  "Parsed on this computer. Its text is sent to Ollama Cloud (gemma4:31b-cloud) when you ask about it.";
const IMG_LINE = "The image is sent to Ollama Cloud (gemma4:31b-cloud) to be read.";

test.describe("precheck", () => {
  const MIB = 10 * 1024 * 1024;
  test("exactly 10 MiB passes", () => {
    expect(precheck({ name: "march-statement.csv", size: MIB })).toBeNull();
  });
  test("10 MiB + 1 is refused with the size to one decimal", () => {
    expect(precheck({ name: "march-statement.csv", size: MIB + 1 })).toBe(
      "That file is 10.0 MB. The limit is 10 MB. Choose a smaller file."
    );
  });
  test("a non-allowed extension is refused", () => {
    expect(precheck({ name: "a.xlsx", size: 5 })).toBe(
      "monai reads CSV, PDF, PNG, JPEG and WebP files. Choose one of those."
    );
  });
  test("no extension is refused", () => {
    expect(precheck({ name: "statement", size: 5 })).not.toBeNull();
  });
  test("an empty file is refused", () => {
    expect(precheck({ name: "a.csv", size: 0 })).toBe("That file is empty. Choose another file.");
  });
  for (const n of ["A.PDF", "a.Png", "b.jpg", "b.JPEG", "c.webp", "d.CSV"]) {
    test(`${n} passes (case-insensitive)`, () => {
      expect(precheck({ name: n, size: 5 })).toBeNull();
    });
  }
  test("accept attribute lists every extension and mime", () => {
    expect(ACCEPT_ATTR).toBe(
      ".csv,.pdf,.png,.jpg,.jpeg,.webp,text/csv,application/pdf,image/png,image/jpeg,image/webp"
    );
  });
});

test.describe("fileKind", () => {
  test("maps extensions to client kinds", () => {
    expect(fileKind("a.CSV")).toBe("csv");
    expect(fileKind("a.pdf")).toBe("pdf");
    expect(fileKind("a.webp")).toBe("image");
    expect(fileKind("a.txt")).toBeNull();
  });
});

test.describe("localityLines", () => {
  test("pdf shows both lines, destination verbatim", () => {
    expect(localityLines(CLOUD, "pdf")).toEqual([
      { lead: "CSV and text PDF:", text: CSV_LINE },
      { lead: "Image or scan:", text: IMG_LINE },
    ]);
  });
  test("no file chosen shows both lines", () => {
    expect(localityLines(CLOUD, null)).toHaveLength(2);
  });
  test("csv shows only the csv line", () => {
    expect(localityLines(CLOUD, "csv")).toEqual([{ lead: "CSV and text PDF:", text: CSV_LINE }]);
  });
  test("image shows only the image line", () => {
    expect(localityLines(CLOUD, "image")).toEqual([{ lead: "Image or scan:", text: IMG_LINE }]);
  });
  test("local is one line whatever the kind", () => {
    for (const k of [null, "csv", "pdf", "image"] as const) {
      expect(localityLines({ local: true, destination: null }, k)).toEqual([
        { lead: "", text: "Stays on this computer." },
      ]);
    }
  });
});

test.describe("uploadErrorText", () => {
  test("413", () => {
    expect(uploadErrorText(413)).toBe("That file is over the 10 MB limit. Choose a smaller file.");
  });
  test("415", () => {
    expect(uploadErrorText(415)).toBe(
      "monai reads CSV, PDF, PNG, JPEG and WebP files. This one isn't any of those."
    );
  });
  for (const s of [401, 403]) {
    test(`${s} names the status`, () => {
      expect(uploadErrorText(s)).toBe(
        `Couldn't attach the file: the server refused it (${s}). Nothing was added to your records.`
      );
    });
  }
  test("422 uses the detail", () => {
    expect(uploadErrorText(422, "Choose an account that can take transactions.")).toBe(
      "Couldn't attach the file: Choose an account that can take transactions.. Nothing was added to your records."
    );
  });
  test("other status without detail falls back to HTTP n", () => {
    expect(uploadErrorText(500)).toBe(
      "Couldn't attach the file: HTTP 500. Nothing was added to your records."
    );
  });
  test("network", () => {
    expect(uploadErrorText("network")).toBe(
      "Couldn't attach the file: Network error. Nothing was added to your records."
    );
  });
});

test.describe("cardSentence", () => {
  test("pending is linked and uses the em dash", () => {
    const s = cardSentence(12, 0, "pending");
    expect(s).toEqual({ lead: "12 rows proposed, 0 flagged — ", tail: "Review in Inbox", linked: true });
    expect(s.lead).toContain("—");
    expect(s.lead).toContain(" — ");
  });
  test("undefined status is the in-view turn: pending", () => {
    expect(cardSentence(2, 1, undefined).tail).toBe("Review in Inbox");
  });
  test("one row is singular and k is always printed", () => {
    expect(cardSentence(1, 1, "pending").lead).toBe("1 row proposed, 1 flagged — ");
    expect(cardSentence(0, 0, "pending").lead).toBe("0 rows proposed, 0 flagged — ");
  });
  const tails: [string, string][] = [
    ["confirmed", "Approved in Inbox"],
    ["rejected", "Rejected in Inbox"],
    ["expired", "Expired"],
    ["superseded", "Replaced by a newer proposal"],
    ["missing", "Replaced by a newer proposal"],
  ];
  for (const [st, tail] of tails) {
    test(`${st} drops the link`, () => {
      expect(cardSentence(3, 0, st)).toMatchObject({ tail, linked: false });
    });
  }
});

test.describe("trust lines", () => {
  test("four variants", () => {
    expect(trustLine({ invariant: "balance verified" })).toBe(
      "Opening balance plus these rows matches the closing balance printed on the statement."
    );
    expect(trustLine({ invariant: "running balance verified" })).toBe(
      "Opening balance, every running balance and the closing balance match the statement."
    );
    expect(trustLine({ llm_read: true })).toBe(
      "Read by the model from an image. Check every row against the original."
    );
    expect(trustLine({ invariant: "none" })).toBe(
      "A CSV has no balance to check. Review the rows before approving."
    );
  });
  test("decided cards hide or replace the line", () => {
    const meta = { invariant: "none" };
    expect(cardTrustLine("pending", meta)).toBe(trustLine(meta));
    expect(cardTrustLine("confirmed", meta)).toBe(trustLine(meta));
    expect(cardTrustLine("rejected", meta)).toBeNull();
    expect(cardTrustLine("superseded", meta)).toBeNull();
    expect(cardTrustLine("missing", meta)).toBeNull();
    expect(cardTrustLine("expired", meta)).toBe("Ask me to propose the rows again.");
  });
});

const chip = (over: Partial<AttachChip>): AttachChip => ({
  localId: "c1",
  attachmentId: null,
  filename: "march-statement.csv",
  kind: "csv",
  state: "ok",
  summary: "",
  rowCount: 0,
  purgedAt: null,
  messageId: null,
  ...over,
});

test.describe("chipText", () => {
  test("uploading csv / image", () => {
    expect(chipText(chip({ state: "uploading" }))).toMatchObject({
      status: "Uploading…",
      detail: null,
      tone: "plain",
    });
    expect(chipText(chip({ state: "uploading", kind: "image" })).status).toBe("Reading the image…");
  });
  test("ok shows the server summary", () => {
    expect(chipText(chip({ state: "ok", summary: "42 rows. Parsed on this computer." }))).toMatchObject({
      status: "Ready",
      detail: "42 rows. Parsed on this computer.",
      tone: "plain",
    });
  });
  test("llm_read is warm", () => {
    expect(chipText(chip({ state: "llm_read", summary: "1 row read." }))).toMatchObject({
      status: "LLM-read",
      tone: "warm",
    });
  });
  test("one refused variant, reason verbatim", () => {
    expect(chipText(chip({ state: "refused", summary: "Closing balance is off by 12.500,00." }))).toMatchObject({
      status: "Can't propose rows",
      detail: "Closing balance is off by 12.500,00.",
      tone: "refused",
    });
  });
  test("needs_password", () => {
    expect(chipText(chip({ state: "needs_password" }))).toMatchObject({
      status: "Needs a password",
      detail: "Enter it in the Attach panel.",
      tone: "warm",
    });
  });
  test("failed shows the error", () => {
    expect(chipText(chip({ state: "failed", summary: "oops" }))).toMatchObject({
      status: "Upload failed",
      detail: "oops",
      tone: "refused",
    });
  });
  test("purged flag follows purgedAt", () => {
    expect(chipText(chip({})).purged).toBe(false);
    expect(chipText(chip({ purgedAt: "2026-10-25T00:00:00Z" })).purged).toBe(true);
    expect(PURGED_SUFFIX).toBe(" · original file removed");
  });
  test("pill reads kind and rows when ready, words otherwise", () => {
    expect(pillStatus(chip({ state: "ok", kind: "csv", rowCount: 42 }))).toBe("CSV · 42 rows");
    expect(pillStatus(chip({ state: "ok", kind: "pdf_scanned", rowCount: 1 }))).toBe("Scanned PDF · 1 row");
    expect(pillStatus(chip({ state: "refused" }))).toBe("Can't propose rows");
    expect(pillStatus(chip({ state: "llm_read" }))).toBe("LLM-read");
  });
});

test.describe("placeholderFor", () => {
  test("none keeps the existing placeholder", () => expect(placeholderFor(0)).toBeNull());
  test("one", () =>
    expect(placeholderFor(1)).toBe("Ask about this file, or ask me to propose its rows…"));
  test("two", () =>
    expect(placeholderFor(2)).toBe("Ask about these files, or ask me to propose their rows…"));
});

test.describe("uploadOriginAllowed", () => {
  const path = `threads/${U}/attachments`;
  const hdr = (h: Record<string, string>) => new Headers({ host: "127.0.0.1:3001", ...h });
  test("same-origin upload passes", () => {
    expect(uploadOriginAllowed("POST", path, hdr({ "sec-fetch-site": "same-origin" }))).toBe(true);
  });
  test("cross-site upload is refused", () => {
    expect(uploadOriginAllowed("POST", path, hdr({ "sec-fetch-site": "cross-site" }))).toBe(false);
  });
  test("foreign Origin is refused", () => {
    expect(uploadOriginAllowed("POST", path, hdr({ origin: "http://evil.example" }))).toBe(false);
  });
  test("non-loopback Host is refused", () => {
    expect(uploadOriginAllowed("POST", path, new Headers({ host: "evil.example" }))).toBe(false);
  });
  test("other paths and methods are untouched", () => {
    const evil = hdr({ "sec-fetch-site": "cross-site" });
    expect(uploadOriginAllowed("POST", "import", evil)).toBe(true);
    expect(uploadOriginAllowed("GET", path, evil)).toBe(true);
    expect(uploadOriginAllowed("POST", `threads/${U}/attachments/extra`, evil)).toBe(true);
  });
  test("same-origin upload still gets the API key injected", () => {
    const h = buildForwardHeaders(hdr({ "sec-fetch-site": "same-origin" }), "k", "", "POST", path, "");
    expect(h.get("MONAI_API_KEY")).toBe("k");
  });
});

test.describe("tool labels", () => {
  test("attachment tools", () => {
    expect(toolLabel("read_attachment")).toBe("Read attached file");
    expect(toolLabel("propose_statement_rows")).toBe("Propose file rows");
  });
});
