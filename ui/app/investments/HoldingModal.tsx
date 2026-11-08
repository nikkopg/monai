"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label, tokens } from "../styles";
import { extractDetail, fmtPlain } from "../lib/api";
import { fmtAmount } from "../lib/money";
import type { PlatformOption } from "./page";

// ---------------------------------------------------------------------------
// HoldingModal — buy/sell/dividend event entry (D-01, primary INV-01 path).
// Mirrors TransactionModal's overlay+card shell. POSTs /api/portfolio-events
// through the Next.js proxy (which injects the API key server-side); the
// position recompute happens server-side (05-RESEARCH Pattern 2). On success
// calls onSaved() (parent refetches the summary) then onClose().
//
// XFER-03 extension: a required "Investment liquid account" <select>
// (modal-owned GET /api/accounts fetch, client-filtered to type === "liquid" —
// never free text, RESEARCH Pitfall 2) routes every Buy/Sell submit to
// /api/portfolio-events/funded-buy|sell, carrying a cash_amount that defaults
// to quantity x price until manually edited (D-06). Submit stays disabled until
// an account is chosen (quick 261107-nq6). Dividend has no funded schema: it
// drops the account and is the only thing POSTed to /api/portfolio-events.
//
// Edit mode (editEvent prop): prefilled from an existing event; submit PUTs
// /api/portfolio-events/{id}. A linked (funded) event shows its Cash amount
// field; the funding link, platform and asset type are not editable here.
//
// Phase 45: the cash currency is never an input — it is the funding account's
// own (read-only chip, omitted from the body; the backend derives it). The
// position's currency is the holding's when the ticker is already held on the
// platform (chip, not sent), else a IDR/USD select defaulting to the account's
// currency and sent as event_currency. The cash amount auto-fills from
// quantity x price only when both currencies match; no FX is ever applied.
//
// Quick 261108-gdf: a funded Buy/Sell can carry a fee (coin or cash). Quantity
// is always the FILLED amount; the backend stores the net, and an edit shows and
// sends the filled quantity back so a fee is never applied twice. A cash fee
// moves the auto-filled cash amount (+ on a buy, - on a sell).
// ---------------------------------------------------------------------------

export type EditableEvent = {
  id: number;
  date: string; // YYYY-MM-DD
  ticker: string;
  event_type: "buy" | "sell" | "dividend";
  quantity: number;
  price: number;
  transaction_id: number | null;
  cash_amount: number | null;
  fee?: number | null;
  fee_kind?: string | null;
};

type Props = {
  platforms: PlatformOption[];
  onClose: () => void;
  onSaved: () => void;
  defaultPlatformId?: number;
  editEvent?: EditableEvent;
  // Existing positions, to tell a held ticker (currency fixed) from a new one.
  positions?: {
    ticker: string;
    platformId: number;
    currency: string;
    quantity: number;
  }[];
};

const chipStyle: React.CSSProperties = {
  border: input.border,
  borderRadius: tokens.radius.sm,
  padding: "0 16px",
  display: "flex",
  alignItems: "center",
  background: tokens.color.sidebar,
  fontSize: 14,
  fontWeight: 600,
  color: tokens.color.muted3,
  flexShrink: 0,
};

// IDR keeps this modal's historical "Rp n"; USD uses the shared formatter.
const fmtSide = (n: number, ccy: string) =>
  ccy === "USD" ? fmtAmount(n, "USD") : `Rp ${fmtPlain(n)}`;

type Account = {
  id: number;
  name: string;
  type: string | null;
  currency: string | null;
};

const ASSET_TYPES = ["crypto", "idx_stock", "mutual_fund", "other"] as const;

// datetime-local value from a Date using LOCAL wall-clock components (verbatim
// from TransactionModal — avoids the toISOString() UTC shift).
function toLocalDatetimeInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

// CR-02: the event column is a plain DATE — take the LOCAL calendar date of the
// datetime-local value directly. NEVER new Date(v).toISOString() here: that
// reinterprets the wall-clock string as UTC and books early-morning WIB trades
// (00:00–06:59) a day early. The datetime-local value is already local
// "YYYY-MM-DDTHH:mm", so its first 10 chars are the local calendar date.
const toLocalDateOnly = (v: string) => v.slice(0, 10);

export default function HoldingModal({
  platforms,
  onClose,
  onSaved,
  defaultPlatformId,
  editEvent,
  positions,
}: Props) {
  const isEdit = editEvent !== undefined;
  const linked = editEvent?.transaction_id != null;
  const [ticker, setTicker] = useState(editEvent?.ticker ?? "");
  const [assetType, setAssetType] = useState<string>("crypto");
  // Platform is required (no more "(unassigned)") — pre-select
  // defaultPlatformId when given (still editable), else the first platform.
  const [platformId, setPlatformId] = useState<string>(
    defaultPlatformId
      ? String(defaultPlatformId)
      : platforms.length > 0
      ? String(platforms[0].id)
      : ""
  );
  const [eventType, setEventType] = useState<"buy" | "sell" | "dividend">(
    editEvent?.event_type ?? "buy"
  );
  const [quantity, setQuantity] = useState(
    editEvent ? String(editEvent.quantity) : ""
  );
  const [price, setPrice] = useState(editEvent ? String(editEvent.price) : "");
  const [fee, setFee] = useState(editEvent?.fee ? String(editEvent.fee) : "");
  // null = follow the default (coin for a new crypto buy, else cash) until picked.
  const [feeKindPick, setFeeKindPick] = useState<"coin" | "cash" | null>(
    editEvent?.fee_kind === "coin" || editEvent?.fee_kind === "cash" ? editEvent.fee_kind : null
  );
  const [date, setDate] = useState(
    editEvent ? `${editEvent.date}T00:00` : toLocalDatetimeInputValue(new Date())
  );

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDividend = eventType === "dividend";

  // Funding selector (XFER-03) — modal-owned GET /api/accounts fetch,
  // client-filtered to liquid. Required for Buy/Sell; Dividend has no funded
  // schema, so the account is dropped there.
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [fundingAccount, setFundingAccount] = useState("");
  const [cashAmount, setCashAmount] = useState(
    editEvent?.cash_amount != null ? String(editEvent.cash_amount) : ""
  );
  // Edit mode starts "touched" so the quantity x price re-sync (which also
  // fires on mount) can't overwrite the stored cash amount.
  const [cashAmountTouched, setCashAmountTouched] = useState(isEdit);
  const liquidAccounts = accounts.filter((a) => a.type === "liquid");
  const isFunded = isEdit
    ? linked && !isDividend
    : fundingAccount !== "" && !isDividend;

  // Currencies (Phase 45). Absent account currency means IDR.
  const fundingCcy =
    liquidAccounts.find((a) => a.name === fundingAccount)?.currency ?? "IDR";
  const held = positions?.find(
    (p) =>
      p.ticker.toUpperCase() === ticker.trim().toUpperCase() &&
      p.platformId === parseInt(platformId, 10)
  );
  // null = follow the funding account until the owner picks one.
  const [positionCurrency, setPositionCurrency] = useState<string | null>(null);
  // A NEW ticker starts in the platform's currency (the funding account's when the
  // platform carries none); the owner's pick wins. One value feeds the select, the
  // labels and the POST. Edit mode keeps the stored event's own currency rules.
  const platformCcy = isEdit
    ? undefined
    : platforms.find((p) => String(p.id) === platformId)?.currency;
  const newCcy = positionCurrency ?? platformCcy ?? fundingCcy;
  const eventCcy = held?.currency ?? newCcy;
  // shortcut: edit mode has no stored cash currency in the events payload, so it
  // labels the cash side by the position currency only when that is IDR.
  const cashCcy = isEdit ? (eventCcy === "IDR" ? "IDR" : null) : fundingCcy;
  const feeKind: "coin" | "cash" =
    feeKindPick ?? (!isEdit && eventType === "buy" && assetType === "crypto" ? "coin" : "cash");
  const feeNum = parseFloat(fee);
  const hasFee = feeNum > 0;
  // The stored movement: a coin fee comes off a buy and goes on top of a sell.
  const qtyNum = parseFloat(quantity);
  const moved =
    hasFee && feeKind === "coin" && !Number.isNaN(qtyNum)
      ? String(Number((eventType === "sell" ? qtyNum + feeNum : qtyNum - feeNum).toFixed(8)))
      : quantity;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/accounts");
        if (!r.ok) throw new Error("fetch failed");
        const data: Account[] = await r.json();
        if (!cancelled) {
          setAccounts(data);
          setAccountsLoaded(true);
        }
      } catch {
        // leave accounts empty; the select offers only "Choose an account"
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-sync cash_amount to quantity x price only while the user hasn't
  // manually edited it (D-06) — never silently overwrite a manual edit — and
  // only when cash and position share a currency (D-08). Across currencies an
  // untouched value is one we filled ourselves, so it is cleared, never converted.
  useEffect(() => {
    if (cashAmountTouched) return;
    if (cashCcy !== eventCcy) {
      setCashAmount("");
    } else if (quantity && price) {
      const q = parseFloat(quantity);
      const p = parseFloat(price);
      if (!Number.isNaN(q) && !Number.isNaN(p)) {
        // A cash fee is paid on top of a buy and comes off a sell's proceeds.
        const cashFee = hasFee && feeKind === "cash" ? (eventType === "sell" ? -feeNum : feeNum) : 0;
        setCashAmount(String(cashFee ? Number((q * p + cashFee).toFixed(8)) : q * p));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quantity, price, cashCcy, eventCcy, fee, feeKind, eventType]);

  // When switching to Dividend, default quantity to 1 (still editable) so the
  // form keeps the same field set (quantity=1, price=amount convention).
  function onEventTypeChange(next: "buy" | "sell" | "dividend") {
    setEventType(next);
    if (next === "dividend") {
      if (!quantity) setQuantity("1");
      // WR-01: Dividend has no funded schema. Drop any selected funding
      // account explicitly so the user's choice can't be silently discarded
      // into an unfunded write.
      setFundingAccount("");
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (isEdit) {
        const body: Record<string, unknown> = {
          ticker: ticker.trim(),
          event_type: eventType,
          quantity: parseFloat(quantity),
          price: parseFloat(price),
          date: toLocalDateOnly(date),
        };
        if (isFunded) {
          body.cash_amount = parseFloat(cashAmount);
          body.fee = hasFee ? feeNum : 0; // 0 clears a stored fee
          if (hasFee) body.fee_kind = feeKind;
        }
        const r = await fetch(`/api/portfolio-events/${editEvent.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (r.ok) {
          onSaved();
          onClose();
        } else {
          const detail = await extractDetail(r);
          setError(`Couldn't save changes: ${detail}. Nothing was changed.`);
        }
        return;
      }

      if (isFunded) {
        const endpoint =
          eventType === "sell"
            ? "/api/portfolio-events/funded-sell"
            : "/api/portfolio-events/funded-buy";
        const body: Record<string, unknown> = {
          // WR-09: name-keyed — the backend resolves this via
          // _get_or_create_account, so a rename/delete between this modal's
          // account fetch and submit would fork a phantom account. The select
          // is sourced from a fresh fetch which narrows the window; fully
          // closing it needs an id-based backend resolver (out of Phase 18's
          // UI-only scope).
          source_account_name: fundingAccount,
          platform_id: parseInt(platformId, 10),
          ticker: ticker.trim(),
          quantity: parseFloat(quantity),
          price: parseFloat(price),
          cash_amount: parseFloat(cashAmount),
          // cash_currency is omitted: the backend takes it from the account.
          // event_currency only for a new position; a held one keeps its own.
          ...(held ? {} : { event_currency: newCcy }),
          date: toLocalDateOnly(date),
          asset_type: assetType,
          ...(hasFee ? { fee: feeNum, fee_kind: feeKind } : {}),
        };
        const r = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (r.ok) {
          onSaved();
          onClose();
        } else {
          const detail = await extractDetail(r);
          setError(`Couldn't log funded ${eventType}: ${detail}. Nothing was changed.`);
        }
        return;
      }

      // Event date is a plain date (backend column is DATE) — send YYYY-MM-DD.
      const body: Record<string, unknown> = {
        ticker: ticker.trim(),
        event_type: eventType,
        quantity: parseFloat(quantity),
        price: parseFloat(price),
        date: toLocalDateOnly(date),
        asset_type: assetType,
        platform_id: parseInt(platformId, 10),
      };
      const r = await fetch("/api/portfolio-events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        onSaved();
        onClose();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't log event: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't ${isFunded ? `log funded ${eventType}` : "log event"}: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,17,21,0.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={saving ? undefined : onClose}
    >
      <div
        style={{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>
          {isEdit ? "Edit event" : "Log event"}
        </h2>
        <form onSubmit={handleSubmit}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <div>
              <label style={label}>Ticker</label>
              <input
                style={input}
                required
                value={ticker}
                placeholder="BBCA"
                onChange={(e) => setTicker(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Asset type</label>
              <select
                style={input}
                value={assetType}
                disabled={isEdit}
                onChange={(e) => setAssetType(e.target.value)}
              >
                {ASSET_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={label}>Platform</label>
              <select
                style={input}
                required
                disabled={isEdit}
                value={platformId}
                onChange={(e) => setPlatformId(e.target.value)}
              >
                {platforms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              {platforms.length === 0 && (
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: "#b5503f" }}>
                  Add a platform first
                </p>
              )}
            </div>
            <div>
              <label style={label}>Event type</label>
              <select
                style={input}
                value={eventType}
                onChange={(e) =>
                  onEventTypeChange(e.target.value as "buy" | "sell" | "dividend")
                }
              >
                {/* An unfunded event cannot change type (backend 422). */}
                <option value="buy" disabled={isEdit && !linked && editEvent.event_type !== "buy"}>
                  Buy
                </option>
                <option value="sell" disabled={isEdit && !linked && editEvent.event_type !== "sell"}>
                  Sell
                </option>
                <option
                  value="dividend"
                  disabled={linked || (isEdit && editEvent.event_type !== "dividend")}
                >
                  Dividend
                </option>
              </select>
            </div>
            <div>
              <label style={label}>Quantity</label>
              <input
                style={input}
                type="number"
                step="any"
                min="0"
                required
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
              {!isEdit && eventType === "sell" && held && (
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: tokens.color.muted3 }}>
                  Held: {held.quantity}
                </p>
              )}
            </div>
            <div>
              <label style={label} htmlFor="holding-price">
                {isDividend
                  ? "Dividend amount (IDR)"
                  : isFunded || isEdit
                  ? `Price per unit (${eventCcy})`
                  : "Price per unit"}
              </label>
              <div style={{ display: "flex", alignItems: "stretch", gap: 8 }}>
                <input
                  id="holding-price"
                  style={{ ...input, flex: 1, minWidth: 0 }}
                  type="number"
                  step="any"
                  min="0"
                  required
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                />
                {isFunded &&
                  !isDividend &&
                  (held || isEdit ? (
                    <span aria-label="Position currency" style={chipStyle}>
                      {eventCcy}
                    </span>
                  ) : (
                    <select
                      aria-label="Position currency"
                      style={{ ...input, width: 96, flexShrink: 0 }}
                      value={newCcy}
                      onChange={(e) => setPositionCurrency(e.target.value)}
                    >
                      <option value="IDR">IDR</option>
                      <option value="USD">USD</option>
                    </select>
                  ))}
              </div>
            </div>
            <div>
              <label style={label}>Date</label>
              <input
                style={input}
                type="datetime-local"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
            {!isEdit && (
            <div>
              <label style={label}>Investment liquid account</label>
              <select
                style={input}
                value={fundingAccount}
                required={!isDividend}
                disabled={isDividend}
                onChange={(e) => setFundingAccount(e.target.value)}
              >
                <option value="" disabled>
                  Choose an account
                </option>
                {liquidAccounts.map((a) => (
                  <option key={a.id} value={a.name}>
                    {a.name}
                  </option>
                ))}
              </select>
              {isDividend && (
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: tokens.color.muted3 }}>
                  Dividends aren&apos;t funded from an account.
                </p>
              )}
              {!isDividend && accountsLoaded && liquidAccounts.length === 0 && (
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: tokens.color.muted3 }}>
                  Add a liquid account in Settings, or use Add holding directly for a
                  position you already hold.
                </p>
              )}
            </div>
            )}
            {isFunded && (
              <div>
                <label style={label} htmlFor="holding-cash-amount">
                  {cashCcy ? `Cash amount (${cashCcy})` : "Cash amount"}
                </label>
                <div style={{ display: "flex", alignItems: "stretch", gap: 8 }}>
                  <input
                    id="holding-cash-amount"
                    style={{ ...input, flex: 1, minWidth: 0 }}
                    type="number"
                    step="any"
                    required
                    value={cashAmount}
                    onChange={(e) => {
                      setCashAmount(e.target.value);
                      setCashAmountTouched(true);
                    }}
                  />
                  {cashCcy && (
                    <span aria-label="Cash currency" style={chipStyle}>
                      {cashCcy}
                    </span>
                  )}
                </div>
              </div>
            )}
            {isFunded && (
              <div>
                <label style={label} htmlFor="holding-fee">
                  {`Fee (${feeKind === "coin" ? ticker.trim() || "coin" : eventCcy})`}
                </label>
                <div style={{ display: "flex", alignItems: "stretch", gap: 8 }}>
                  <input
                    id="holding-fee"
                    style={{ ...input, flex: 1, minWidth: 0 }}
                    type="number"
                    step="any"
                    min="0"
                    value={fee}
                    onChange={(e) => setFee(e.target.value)}
                  />
                  <select
                    aria-label="Fee kind"
                    style={{ ...input, width: 140, flexShrink: 0 }}
                    value={feeKind}
                    onChange={(e) => setFeeKindPick(e.target.value as "coin" | "cash")}
                  >
                    <option value="coin">From the coin</option>
                    <option value="cash">{`Cash (${eventCcy})`}</option>
                  </select>
                </div>
                {isEdit && linked && (
                  <p style={{ ...label, fontSize: 11, marginTop: 4, color: tokens.color.muted3 }}>
                    The cash amount is not recalculated; change it too if the fee changed what was paid.
                  </p>
                )}
              </div>
            )}
          </div>

          {!isEdit && isFunded && quantity && ticker && (
            <p
              style={{
                fontSize: 13,
                margin: "0 0 10px",
                color:
                  eventType === "sell" ? tokens.color.terracotta : tokens.color.green,
              }}
            >
              {eventType === "sell"
                ? `Credits ${fundingAccount} ${fmtSide(parseFloat(cashAmount || "0"), fundingCcy)}, −${moved} ${ticker}`
                : `Debits ${fundingAccount} ${fmtSide(parseFloat(cashAmount || "0"), fundingCcy)}, +${moved} ${ticker}`}
            </p>
          )}

          <div
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}
          >
            <button
              type="button"
              onClick={saving ? undefined : onClose}
              style={{
                background: "transparent",
                color: "#8b8474",
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: saving ? "default" : "pointer",
              }}
            >
              Cancel
            </button>
            <button
              style={btn}
              type="submit"
              disabled={
                saving ||
                platforms.length === 0 ||
                !(parseFloat(quantity) > 0) ||
                !(parseFloat(price) > 0) ||
                (!isEdit && !isDividend && fundingAccount === "") ||
                (isFunded && !(parseFloat(cashAmount) > 0))
              }
            >
              {saving
                ? "Saving…"
                : isEdit
                ? "Save changes"
                : isFunded
                ? `Log funded ${eventType.charAt(0).toUpperCase()}${eventType.slice(1)}`
                : "Log event"}
            </button>
            {error && (
              <span style={{ color: "#b5503f", fontSize: 12 }}>{error}</span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
