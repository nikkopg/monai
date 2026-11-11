import { test, expect } from "@playwright/test";
import { changeBadge, periodWindow, spendBar, topCategories } from "../app/cashflow/periodCard";

// Browserless: pure period maths for the Cashflow "Income & spending" card (no
// page, no server). All values synthetic; dates built from local Date constructors.

const NOV11 = new Date(2026, 10, 11); // a Wednesday

function win(kind: "week" | "month" | "year", offset: number, today = NOV11) {
  const w = periodWindow(kind, offset, today);
  return { range: `${w.start}..${w.end}`, prev: `${w.prevStart}..${w.prevEnd}`, w };
}

test.describe("periodWindow", () => {
  test("month, in progress and past", () => {
    const cur = win("month", 0);
    expect(cur.range).toBe("2026-11-01..2026-11-11");
    expect(cur.prev).toBe("2026-10-01..2026-10-11");
    expect(cur.w).toMatchObject({ title: "Nov 2026", span: "1–11 Nov", prevSpan: "1–11 Oct", inProgress: true });

    const past = win("month", -1);
    expect(past.range).toBe("2026-10-01..2026-10-31");
    expect(past.prev).toBe("2026-09-01..2026-09-30");
    expect(past.w).toMatchObject({ title: "Oct 2026", span: "1–31 Oct", prevSpan: "1–30 Sep", inProgress: false });
    expect(win("month", -12).range).toBe("2025-11-01..2025-11-30");
  });

  test("month clamps the day and crosses a year", () => {
    expect(win("month", 0, new Date(2026, 2, 31)).prev).toBe("2026-02-01..2026-02-28");
    const jan = win("month", 0, new Date(2026, 0, 15));
    expect(jan.prev).toBe("2025-12-01..2025-12-15");
    expect(jan.w.prevSpan).toBe("1–15 Dec 2025");
    const first = win("month", 0, new Date(2026, 10, 1));
    expect(first.w).toMatchObject({ span: "1 Nov", prevSpan: "1 Oct" });
  });

  test("week starts Monday", () => {
    const cur = win("week", 0);
    expect(cur.range).toBe("2026-11-09..2026-11-11");
    expect(cur.prev).toBe("2026-11-02..2026-11-04");
    expect(cur.w).toMatchObject({ title: "9–15 Nov 2026", span: "9–11 Nov", prevSpan: "2–4 Nov" });

    const past = win("week", -1);
    expect(past.range).toBe("2026-11-02..2026-11-08");
    expect(past.prev).toBe("2026-10-26..2026-11-01");
    expect(past.w.prevSpan).toBe("26 Oct–1 Nov");
  });

  test("week across a year boundary names both years", () => {
    const w = win("week", 0, new Date(2027, 0, 1)); // a Friday
    expect(w.range).toBe("2026-12-28..2027-01-01");
    expect(w.w).toMatchObject({
      span: "28 Dec 2026–1 Jan 2027",
      title: "28 Dec 2026–3 Jan 2027",
      prevSpan: "21–25 Dec",
    });
    expect(w.prev).toBe("2026-12-21..2026-12-25");
  });

  test("year compares the same calendar dates", () => {
    const cur = win("year", 0);
    expect(cur.range).toBe("2026-01-01..2026-11-11");
    expect(cur.prev).toBe("2025-01-01..2025-11-11");
    expect(cur.w).toMatchObject({ title: "2026", span: "1 Jan–11 Nov", prevSpan: "1 Jan–11 Nov 2025" });
    expect(win("year", 0, new Date(2028, 1, 29)).prev).toBe("2027-01-01..2027-02-28");

    const past = win("year", -1);
    expect(past.range).toBe("2025-01-01..2025-12-31");
    expect(past.prev).toBe("2024-01-01..2024-12-31");
    expect(past.w).toMatchObject({ title: "2025", prevSpan: "1 Jan–31 Dec 2024" });
  });
});

test.describe("changeBadge", () => {
  const vs = "1–11 Oct";

  test("good and bad follow the metric, not the arrow", () => {
    expect(changeBadge(9_500_000, 8_500_000, true, vs)).toEqual({
      text: "+12%",
      dir: "up",
      tone: "good",
      title: "Up 12% vs 1–11 Oct (8,500,000)",
    });
    expect(changeBadge(4_210_000, 4_600_000, false, vs)).toEqual({
      text: "−8%",
      dir: "down",
      tone: "good",
      title: "Down 8% vs 1–11 Oct (4,600,000)",
    });
    expect(changeBadge(5_200_000, 4_000_000, false, vs)).toMatchObject({ text: "+30%", dir: "up", tone: "bad" });
  });

  test("tiny moves and a zero base are flat", () => {
    expect(changeBadge(1004, 1000, true, vs)).toEqual({
      text: "0%",
      dir: null,
      tone: "flat",
      title: "No change vs 1–11 Oct (1,000)",
    });
    expect(changeBadge(500, 0, true, vs)).toEqual({
      text: "new",
      dir: null,
      tone: "flat",
      title: "New vs 1–11 Oct (0)",
    });
    expect(changeBadge(0, 0, true, vs)).toMatchObject({ text: "0%", tone: "flat" });
  });

  test("a negative base uses its absolute value", () => {
    expect(changeBadge(500_000, -1_000_000, true, vs)).toMatchObject({ text: "+150%", dir: "up", tone: "good" });
    expect(changeBadge(-500_000, 1_000_000, true, vs)).toMatchObject({ text: "−150%", dir: "down", tone: "bad" });
  });
});

test.describe("spendBar", () => {
  test("share of income spent, capped at a full bar", () => {
    expect(spendBar(9_500_000, 4_210_000)).toEqual({ spent: 44, width: 44, kept: "56% kept" });
    expect(spendBar(1_000_000, 1_300_000)).toEqual({ spent: 130, width: 100, kept: "30% over" });
    expect(spendBar(1_000_000, 0)).toEqual({ spent: 0, width: 0, kept: "100% kept" });
  });

  test("no income, no bar", () => {
    expect(spendBar(0, 1_000_000)).toBeNull();
    expect(spendBar(-5, 1)).toBeNull();
  });
});

test.describe("topCategories", () => {
  const rows = (totals: number[]) =>
    totals.map((total, i) => ({ id: i + 1, name: `Cat ${i + 1}`, color: "#abc", icon: null, total, children: [] }));

  test("folds the tail past five into Others", () => {
    const out = topCategories(rows([10, 70, 50, 40, 30, 20, 30])); // sum 250
    expect(out.map((r) => r.name)).toEqual(["Cat 2", "Cat 3", "Cat 4", "Cat 5", "Cat 7", "Others"]);
    expect(out[5]).toEqual({ id: -1, name: "Others", color: "#c8c1b5", icon: null, children: [], total: 30, share: 12 });
    expect(out.map((r) => r.share)).toEqual([28, 20, 16, 12, 12, 12]);
  });

  test("six rows all stay named", () => {
    const out = topCategories(rows([6, 5, 4, 3, 2, 1]));
    expect(out.map((r) => r.name)).toEqual(["Cat 1", "Cat 2", "Cat 3", "Cat 4", "Cat 5", "Cat 6"]);
  });

  test("short, empty and zero-sum input", () => {
    expect(topCategories(rows([1, 3, 2])).map((r) => [r.name, r.share])).toEqual([
      ["Cat 2", 50],
      ["Cat 3", 33],
      ["Cat 1", 17],
    ]);
    expect(topCategories([])).toEqual([]);
    expect(topCategories(rows([0, 0])).map((r) => r.share)).toEqual([0, 0]);
  });
});
