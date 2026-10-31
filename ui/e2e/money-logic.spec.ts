import { test, expect } from "@playwright/test";
import { fmtAmount, fmtAmountSigned, rateHover } from "../app/lib/money";

// Browserless: pure formatter checks (no page, no server). All values synthetic.

// Copies of the page formatters this module replaced; the IDR branch must match them.
const money = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));
const signed = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(Math.round(n));

const edge = [-1234567.5, -2.5, -0.4, 0, 0.5, 2.5, 1234567.5, 999999999.49];

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
