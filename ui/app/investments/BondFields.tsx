"use client";

import { input, label, tokens } from "../styles";
import { fmtPlain } from "../lib/api";
import { couponPreview, type BondTermsInput } from "../lib/bond";
import Pills from "../components/Pills";

// ---------------------------------------------------------------------------
// BondFields — the SBN coupon terms, shared by HoldingModal (Log event -> Buy)
// and HoldingOverrideModal (quick 261117-rw1). Renders grid items, so it must sit
// inside the parent's .form-grid (two columns on desktop, one on phones). The
// preview is display only; the stored coupon comes from the backend.
// ---------------------------------------------------------------------------

const full: React.CSSProperties = { gridColumn: "1 / -1" };
const note: React.CSSProperties = {
  ...label,
  fontSize: "var(--fs-xs, 11px)",
  margin: 0,
  color: tokens.color.muted3,
};
const line: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
  fontVariantNumeric: "tabular-nums",
};

export default function BondFields({
  value,
  onChange,
  nominal,
  accounts,
}: {
  value: BondTermsInput;
  onChange: (next: BondTermsInput) => void;
  nominal: number;
  accounts: { id: number; name: string }[];
}) {
  const set = (patch: Partial<BondTermsInput>) => onChange({ ...value, ...patch });
  const preview = couponPreview(nominal, parseFloat(value.rate), parseFloat(value.taxPct));
  const money = (n: number | undefined, sign = "") => (n === undefined ? "—" : `${sign}${fmtPlain(n)}`);

  return (
    <>
      <div style={full}>
        <div style={label}>Coupon</div>
        <Pills
          label="Coupon"
          tap
          value={value.floating ? "floating" : "fixed"}
          options={[
            { value: "fixed", label: "Fixed" },
            { value: "floating", label: "Floating" },
          ]}
          onChange={(v) => set({ floating: v === "floating" })}
        />
        {value.floating && (
          <p style={{ ...note, marginTop: 6 }}>
            Edit the rate when it resets; coupons after that use the new rate.
          </p>
        )}
      </div>
      <div>
        <label style={label} htmlFor="bond-rate">
          Rate % p.a.
        </label>
        <input
          id="bond-rate"
          style={input}
          inputMode="decimal"
          placeholder="6.25"
          value={value.rate}
          onChange={(e) => set({ rate: e.target.value })}
        />
      </div>
      <div>
        <label style={label} htmlFor="bond-pay-day">
          Pay day
        </label>
        <input
          id="bond-pay-day"
          style={input}
          type="number"
          inputMode="numeric"
          min="1"
          max="28"
          step="1"
          placeholder="15"
          value={value.payDay}
          onChange={(e) => set({ payDay: e.target.value })}
        />
      </div>
      <div>
        <label style={label} htmlFor="bond-maturity">
          Maturity
        </label>
        <input
          id="bond-maturity"
          style={input}
          type="date"
          value={value.maturity}
          onChange={(e) => set({ maturity: e.target.value })}
        />
      </div>
      <div>
        <label style={label} htmlFor="bond-tax">
          Tax %
        </label>
        <input
          id="bond-tax"
          style={input}
          inputMode="decimal"
          value={value.taxPct}
          onChange={(e) => set({ taxPct: e.target.value })}
        />
      </div>
      <div style={full}>
        <label style={label} htmlFor="bond-coupon-account">
          Coupons go to
        </label>
        <select
          id="bond-coupon-account"
          style={input}
          value={value.couponAccountId}
          onChange={(e) => set({ couponAccountId: e.target.value })}
        >
          <option value="" disabled>
            Choose an account
          </option>
          {accounts.map((a) => (
            <option key={a.id} value={String(a.id)}>
              {a.name}
            </option>
          ))}
        </select>
      </div>
      <div
        data-testid="bond-preview"
        style={{
          ...full,
          background: tokens.color.tintGreen,
          borderRadius: 12,
          padding: "12px 14px",
          fontSize: "var(--fs-body, 14px)",
          lineHeight: 1.6,
        }}
      >
        <div style={line}>
          <span>Gross / month</span>
          <span>{money(preview?.gross)}</span>
        </div>
        <div style={line}>
          <span>{`Tax ${value.taxPct || "0"}%`}</span>
          <span>{money(preview?.tax, "−")}</span>
        </div>
        <div
          style={{
            ...line,
            fontWeight: 600,
            borderTop: "1px solid rgba(47,111,79,.2)",
            marginTop: 4,
            paddingTop: 4,
          }}
        >
          <span>You receive / month</span>
          <span>{money(preview?.net)}</span>
        </div>
      </div>
    </>
  );
}
