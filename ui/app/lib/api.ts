// ---------------------------------------------------------------------------
// Shared API helpers (WR-12). Previously copy-pasted across AccountManager,
// AdjustBalanceModal, DepositCashModal, and HoldingModal — the copies drifted
// (HoldingModal's inline variant rendered Pydantic 422 arrays as
// "[object Object]", WR-02). This is the single canonical version.
// ---------------------------------------------------------------------------

const CURRENCY_RE = /^[A-Z]{3,4}$/;
export { CURRENCY_RE };

// Pull a human-readable message out of a failed fetch Response. Handles the
// three shapes the backend actually returns:
//   - FastAPI HTTPException: { detail: "string" }
//   - structured domain error: { detail: { message: "..." } }
//   - Pydantic validation 422: { detail: [{ loc, msg }, ...] }  (WR-02)
// Falls back to "HTTP <status>" if the body isn't JSON or has no detail.
export async function extractDetail(r: Response): Promise<string> {
  let detail = `HTTP ${r.status}`;
  try {
    const errBody = await r.json();
    const d = errBody?.detail;
    if (typeof d === "string") {
      detail = d;
    } else if (Array.isArray(d)) {
      // Pydantic 422: degrade [{loc, msg}] to "field: msg; field: msg".
      const msgs = d
        .map((e) => {
          const loc = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : undefined;
          const msg = e?.msg ?? "invalid";
          return loc ? `${loc}: ${msg}` : msg;
        })
        .filter(Boolean);
      if (msgs.length > 0) detail = msgs.join("; ");
    } else if (d?.message) {
      detail = d.message;
    }
  } catch {
    // keep the status-based detail
  }
  return detail;
}

// IDR-style whole-number formatting (no decimals) — the app is single-currency
// IDR, which has no sub-unit.
export const fmtPlain = (n: number) =>
  new Intl.NumberFormat("en-US").format(Math.round(n));
