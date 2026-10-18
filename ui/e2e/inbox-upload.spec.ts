import { test, expect } from "@playwright/test";
import {
  assumptionLines,
  invariantBadge,
  rowProvenance,
  sourceLabel,
  sourceLine,
  uploadFlaggedCount,
  uploadMeta,
  visibleRowIndices,
  type UploadMeta,
} from "../app/lib/inbox";
import { chatTx, uploadProposal } from "./inbox-fixtures";

// ---------------------------------------------------------------------------
// Phase 39 plan 13 — Inbox upload cards (D-21, D-23). Synthetic values only.
// ---------------------------------------------------------------------------

const meta = (o: Partial<UploadMeta> = {}): UploadMeta => ({
  filename: "f.pdf",
  kind: "pdf_text",
  row_count: 3,
  invariant: "none",
  llm_read: false,
  assumptions: [],
  ...o,
});

test.describe("upload helpers", () => {
  test("sourceLabel", () => {
    expect(sourceLabel("upload")).toBe("Upload");
    expect(sourceLabel("mcp")).toBe("Claude");
    expect(sourceLabel("chat")).toBe("monai chat");
  });

  test("uploadMeta is null off the upload channel", () => {
    expect(uploadMeta(chatTx())).toBeNull();
    expect(uploadMeta(uploadProposal("pdf"))?.filename).toBe("march-statement.pdf");
  });

  test("balance verified badge", () => {
    expect(
      invariantBadge(meta({ invariant: "balance verified", opening: "5000000.00", closing: "5034500.00" }), 3, "IDR")
    ).toEqual({
      text: "Balance verified",
      tone: "green",
      sentence: "Opening 5,000,000 + 3 rows = closing 5,034,500, as printed on the statement.",
    });
  });

  test("running balance badge", () => {
    const b = invariantBadge(
      meta({ invariant: "running balance verified", opening: "5000000.00", closing: "5034500.00" }),
      3,
      "IDR"
    );
    expect(b.text).toBe("Running balance verified");
    expect(b.tone).toBe("green");
    expect(b.sentence).toBe(
      "Opening 5,000,000 + 3 rows = closing 5,034,500, and every row's running balance matches."
    );
  });

  test("a negative opening keeps its sign", () => {
    const b = invariantBadge(
      meta({ invariant: "balance verified", opening: "-250000.00", closing: "10000.00" }),
      1,
      "IDR"
    );
    expect(b.sentence).toBe("Opening -250,000 + 1 rows = closing 10,000, as printed on the statement.");
  });

  test("LLM-read wins over any invariant", () => {
    const b = invariantBadge(meta({ llm_read: true, invariant: "balance verified" }), 1, "IDR");
    expect(b).toEqual({
      text: "LLM-read",
      tone: "warm",
      sentence: "Read by the model from an image. No balance check was possible. Compare each row with the original.",
    });
  });

  test("CSV badge", () => {
    expect(invariantBadge(meta({ kind: "csv" }), 2, "IDR")).toEqual({
      text: "No balance check",
      tone: "neutral",
      sentence: "A CSV has no balance to verify. Review the rows before approving.",
    });
  });

  test("assumptionLines", () => {
    const a = ['Amounts read with "." as the thousands separator and "," as decimals.', "Dates read day first."];
    expect(assumptionLines(meta({ assumptions: a }))).toEqual(a);
    expect(assumptionLines(meta())).toEqual([]);
  });

  test("rowProvenance", () => {
    const rows = uploadProposal("image").payload.rows;
    expect(rowProvenance(rows[0])).toEqual([
      { chip: "LLM-read", line: "Read by the model. Check the date and amount against the original." },
    ]);
    const csv = uploadProposal("csv").payload.rows;
    expect(rowProvenance(csv[0])).toEqual([{ chip: "Format assumed", line: "Dates read day first." }]);
    expect(rowProvenance(csv[1])).toEqual([]);
  });

  test("sourceLine only on flagged rows with a raw line", () => {
    const pdf = uploadProposal("pdf").payload.rows;
    expect(sourceLine(pdf[0])).toBe("From the file: 01/03 GAJI CONTOH 50,000.00"); // duplicate-flagged
    expect(sourceLine(pdf[1])).toBeNull(); // plain
    const image = uploadProposal("image").payload.rows;
    expect(sourceLine(image[0])).toBe("From the file: TOKO CONTOH 35.000");
    expect(sourceLine({ ...image[0], after: { ...image[0].after, raw_line: "" } })).toBeNull();
  });

  test("uploadFlaggedCount matches the server's flagged_count", () => {
    for (const v of ["pdf", "csv", "image"] as const) {
      const p = uploadProposal(v);
      expect(uploadFlaggedCount(p.payload.rows)).toBe(p.payload.attachment?.flagged_count);
    }
  });

  test("a long card keeps every provenance-flagged row visible", () => {
    const flagged = uploadProposal("image").payload.rows[0];
    const plain = uploadProposal("pdf").payload.rows[1];
    const rows = Array.from({ length: 12 }, (_, i) => (i === 9 ? flagged : plain));
    expect(visibleRowIndices(rows, false)).toEqual([0, 1, 2, 3, 4, 9]);
  });
});
