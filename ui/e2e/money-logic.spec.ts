import { test, expect } from "@playwright/test";
import { fmtAmount, fmtAmountSigned, fmtRateCompare, impliedRate, rateHover, sumIdr } from "../app/lib/money";

// Browserless: pure formatter checks (no page, no server). All values synthetic.

// Copies of the page formatters this module replaced; the IDR branch must match them.
const money = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));
const signed = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(Math.round(n));

const edge = [-1234567.5, -2.5, -0.4, 0, 0.5, 2.5, 1234567.5, 999999999.49]; // pii-ok synthetic edge values

test.describe("money formatter", () => {
  test("IDR is byte-identical", () => {
    for (const v of edge) {
      expect(fmtAmount(v, "IDR"), `fmtAmount(${v}, IDR)`).toBe(money(v));
      expect(fmtAmount(v), `fmtAmount(${v})`).toBe(money(v));
      expect(fmtAmount(v, null), `fmtAmount(${v}, null)`).toBe(money(v));
      expect(fmtAmountSigned(v, "IDR"), `fmtAmountSigned(${v}, IDR)`).toBe(signed(v));
      expect(fmtAmountSigned(v), `fmtAmountSigned(${v})`).toBe(signed(v));
    }
    expect(fmtAmountSigned(-0.4, "IDR")).toBe("-0");
    expect(fmtAmountSigned(0, "IDR")).toBe("+0");
    expect(fmtAmount(0, "IDR")).toBe("0");
    expect(fmtAmount(1234567.5, "IDR")).toBe("1,234,568");
  });

  test("USD has two decimals and a code", () => {
    expect(fmtAmount(-12.34, "USD")).toBe("-12.34 USD");
    expect(fmtAmount(5, "USD")).toBe("5.00 USD");
    expect(fmtAmount(1234567.891, "USD")).toBe("1,234,567.89 USD");
    expect(fmtAmountSigned(12.3, "USD")).toBe("+12.30 USD");
    expect(fmtAmountSigned(-12.34, "USD")).toBe("-12.34 USD");
  });

  test("missing is a dash", () => {
    for (const v of [null, undefined, NaN, Infinity]) {
      for (const ccy of ["IDR", "USD"]) {
        expect(fmtAmount(v, ccy), `fmtAmount(${v}, ${ccy})`).toBe("—");
        expect(fmtAmountSigned(v, ccy), `fmtAmountSigned(${v}, ${ccy})`).toBe("—");
      }
    }
  });

  test("rate hover", () => {
    expect(rateHover(16250, "2026-10-30")).toBe("1 USD = 16,250 IDR · rate of 30 Oct 2026");
    expect(rateHover(16250.456, "2026-10-30")).toBe("1 USD = 16,250.46 IDR · rate of 30 Oct 2026");
    expect(rateHover(null, "2026-10-30")).toBeUndefined();
    expect(rateHover(16250, null)).toBeUndefined();
  });
});

test.describe("sumIdr", () => {
  test("sumIdr adds IDR values only", () => {
    const idr = { amount: -25000 };
    const usd = { amount: -12.34, currency: "USD", amount_idr: -200525 };
    const noRate = { amount: -5, currency: "USD", amount_idr: null };
    expect(sumIdr([idr, usd])).toEqual({ total: -225525, unconverted: 0 });
    expect(sumIdr([idr, usd, noRate])).toEqual({ total: -225525, unconverted: 1 });
    expect(sumIdr([{ amount: -5, currency: "USD" }])).toEqual({ total: 0, unconverted: 1 });
    expect(sumIdr([{ amount: -100, currency: "IDR", amount_idr: -90 }])).toEqual({ total: -90, unconverted: 0 });
    expect(sumIdr([])).toEqual({ total: 0, unconverted: 0 });
    expect(sumIdr([noRate, usd, idr].reverse())).toEqual(sumIdr([noRate, usd, idr]));
  });
});

test.describe("implied rate (display only)", () => {
  test("impliedRate is IDR over USD or null", () => {
    expect(impliedRate(1631000, 100)).toBe(16310);
    expect(impliedRate(-1631000, -100)).toBe(16310);
    for (const [i, u] of [[0, 100], [1631000, 0], [NaN, 100], [1631000, Infinity], [null, 100]] as const) {
      expect(impliedRate(i as number, u as number), `impliedRate(${i}, ${u})`).toBeNull();
    }
  });

  test("fmtRateCompare writes the three UI-SPEC strings", () => {
    expect(fmtRateCompare(16310, 16250, "2026-10-30", "ok")).toBe(
      "Implied 1 USD = 16,310 IDR · ECB 16,250 (rate of 30 Oct 2026)"
    );
    expect(fmtRateCompare(16310, null, null, "none")).toBe("Implied 1 USD = 16,310 IDR · ECB rate unavailable");
    expect(fmtRateCompare(16310, null, null, "loading")).toBe("Implied 1 USD = 16,310 IDR · checking ECB rate…");
    expect(fmtRateCompare(16310, 16250.6, "2026-10-30", "ok")).toContain("ECB 16,251 ");
    expect(fmtRateCompare(16310, null, null, "ok")).toBe("Implied 1 USD = 16,310 IDR · ECB rate unavailable");
  });
});
