import { test, expect, type Page } from "@playwright/test";
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
import { NOW, chatTx, mockInbox, uploadProposal } from "./inbox-fixtures";

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

// ---------------------------------------------------------------------------
// Rendered card
// ---------------------------------------------------------------------------

async function open(page: Page, variant: "pdf" | "csv" | "image", title: string) {
  const inbox = await mockInbox(page, { list: [uploadProposal(variant)] });
  await page.clock.setFixedTime(NOW);
  await page.goto("/inbox");
  const card = page.getByRole("article", { name: title, exact: true });
  await expect(card).toBeVisible();
  return { inbox, card };
}

test.describe("upload card", () => {
  test("pdf: source, file line, running-balance badge, duplicate flag kept", async ({ page }) => {
    const { card } = await open(page, "pdf", "Add 3 transactions to Account A");
    await expect(card.getByText("Upload", { exact: true })).toBeVisible();
    await expect(card.getByTestId("inbox-upload-file")).toHaveText("march-statement.pdf");
    await expect(card).toContainText("PDF · 3 rows");
    await expect(card.getByTestId("inbox-invariant-badge")).toHaveText("Running balance verified");
    await expect(card).toContainText(
      "Opening 5,000,000 + 3 rows = closing 5,034,500, and every row's running balance matches."
    );
    await expect(card.getByText("Possible duplicate")).toBeVisible();
    // the source line sits on the flagged row only
    await expect(card.getByText("From the file:")).toHaveCount(1);
    await expect(card.getByText("From the file: 01/03 GAJI CONTOH 50,000.00")).toBeVisible();
    await expect(card.getByText("Format assumed")).toHaveCount(0);
    await expect(card.getByText("LLM-read")).toHaveCount(0);
  });

  test("csv: no balance check, batch and row 'Format assumed'", async ({ page }) => {
    const { card } = await open(page, "csv", "Add 2 transactions to Account A");
    await expect(card.getByTestId("inbox-upload-file")).toHaveText("export-contoh.csv");
    await expect(card).toContainText("CSV · 2 rows");
    await expect(card.getByTestId("inbox-invariant-badge")).toHaveText("No balance check");
    await expect(card).toContainText("A CSV has no balance to verify. Review the rows before approving.");
    // one batch chip in the header, one on the flagged row
    await expect(card.getByText("Format assumed", { exact: true })).toHaveCount(2);
    await expect(card.getByText("Dates read day first.")).toHaveCount(2);
    await expect(card.getByText("From the file: 07/10/2026;Kopi Contoh;-35000")).toBeVisible();
    await expect(card.getByText("From the file:")).toHaveCount(1);
  });

  test("image: LLM-read badge and row block", async ({ page }) => {
    const { card } = await open(page, "image", "Add 1 transaction to Account A");
    await expect(card).toContainText("Image · 1 rows");
    await expect(card.getByTestId("inbox-invariant-badge")).toHaveText("LLM-read");
    await expect(card).toContainText("Read by the model from an image. No balance check was possible.");
    await expect(card.getByText("Read by the model. Check the date and amount against the original.")).toBeVisible();
    await expect(card.getByText("From the file: TOKO CONTOH 35.000")).toBeVisible();
  });

  test("skip and approve behave as before", async ({ page }) => {
    const { inbox, card } = await open(page, "pdf", "Add 3 transactions to Account A");
    await card.getByRole("button", { name: "Skip row 1: Gaji Contoh, +50,000" }).click();
    const after = page.getByRole("article", { name: "Add 2 transactions to Account A", exact: true }); // the title follows the skip
    await expect(after.getByRole("button", { name: /^Approve/ })).toContainText("Add 2 transactions, 1 skipped");
    await expect(after.getByText("Possible duplicate")).toBeVisible(); // a skipped row keeps its flags
    await after.getByRole("button", { name: /^Approve/ }).click();
    await expect.poll(() => inbox.sent("POST", "/approve").length).toBe(1);
  });

  test("a hostile filename stays text", async ({ page }) => {
    const p = uploadProposal("pdf");
    p.payload.attachment!.filename = '<img src=x onerror="window.__xss=1">.pdf';
    await mockInbox(page, { list: [p] });
    await page.clock.setFixedTime(NOW);
    await page.goto("/inbox");
    await expect(page.getByTestId("inbox-upload-file")).toHaveText('<img src=x onerror="window.__xss=1">.pdf');
    await expect(page.locator("img[src=x]")).toHaveCount(0);
  });
});
