"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label, tokens } from "../styles";
import { extractDetail, fmtPlain } from "../lib/api";
import type { PlatformOption } from "./page";

// ---------------------------------------------------------------------------
// HoldingModal — buy/sell/dividend event entry (D-01, primary INV-01 path).
// Mirrors TransactionModal's overlay+card shell. POSTs /api/portfolio-events
// through the Next.js proxy (which injects the API key server-side); the
// position recompute happens server-side (05-RESEARCH Pattern 2). On success
// calls onSaved() (parent refetches the summary) then onClose().
//
// XFER-03 extension: an optional "Funding account" <select> (modal-owned
// GET /api/accounts fetch, client-filtered to type === "liquid" — never free
// text, RESEARCH Pitfall 2) routes Buy/Sell submits to
// /api/portfolio-events/funded-buy|sell instead, carrying a cash_amount that
// defaults to quantity x price until manually edited (D-06). Dividend has no
// funded schema — a funding selection is ignored for it (unfunded path).
// ---------------------------------------------------------------------------

type Props = {
  platforms: PlatformOption[];
  onClose: () => void;
  onSaved: () => void;
  defaultPlatformId?: number;
};

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
}: Props) {
  const [ticker, setTicker] = useState("");
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
  const [eventType, setEventType] = useState<"buy" | "sell" | "dividend">("buy");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [date, setDate] = useState(toLocalDatetimeInputValue(new Date()));

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDividend = eventType === "dividend";

  // Funding selector (XFER-03) — modal-owned GET /api/accounts fetch,
  // client-filtered to liquid. A funding account is only meaningful for
  // Buy/Sell; Dividend has no funded schema, so it's ignored there.
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [fundingAccount, setFundingAccount] = useState("");
  const [cashAmount, setCashAmount] = useState("");
  const [cashAmountTouched, setCashAmountTouched] = useState(false);
  const liquidAccounts = accounts.filter((a) => a.type === "liquid");
  const isFunded = fundingAccount !== "" && !isDividend;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/accounts");
        if (!r.ok) throw new Error("fetch failed");
        const data: Account[] = await r.json();
        if (!cancelled) setAccounts(data);
      } catch {
        // leave accounts empty; the funding select just shows "none"
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Re-sync cash_amount to quantity x price only while the user hasn't
  // manually edited it (D-06) — never silently overwrite a manual edit.
  useEffect(() => {
    if (!cashAmountTouched && quantity && price) {
      const q = parseFloat(quantity);
      const p = parseFloat(price);
      if (!Number.isNaN(q) && !Number.isNaN(p)) setCashAmount(String(q * p));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quantity, price]);

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
          // WR-10: the cash leg debits the selected liquid account, so label it
          // with that account's own currency (D-09 supports per-leg currency).
          cash_currency:
            liquidAccounts.find((a) => a.name === fundingAccount)?.currency ??
            "IDR",
          // event_currency is the instrument's currency; no UI field for it, so
          // the single-currency IDR assumption holds (ponytail: add a field if
          // non-IDR instruments are ever entered).
          event_currency: "IDR",
          date: toLocalDateOnly(date),
          asset_type: assetType,
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
          Log event
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
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
                <option value="dividend">Dividend</option>
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
            </div>
            <div>
              <label style={label}>
                {isDividend ? "Dividend amount (IDR)" : "Price per unit (IDR)"}
              </label>
              <input
                style={input}
                type="number"
                step="any"
                min="0"
                required
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
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
            <div>
              <label style={label}>Funding account</label>
              <select
                style={input}
                value={fundingAccount}
                disabled={isDividend}
                onChange={(e) => setFundingAccount(e.target.value)}
              >
                <option value="">— none (unfunded) —</option>
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
            </div>
            {isFunded && (
              <div>
                <label style={label}>Cash amount (IDR)</label>
                <input
                  style={input}
                  type="number"
                  step="any"
                  required
                  value={cashAmount}
                  onChange={(e) => {
                    setCashAmount(e.target.value);
                    setCashAmountTouched(true);
                  }}
                />
              </div>
            )}
          </div>

          {isFunded && quantity && ticker && (
            <p
              style={{
                fontSize: 13,
                margin: "0 0 10px",
                color:
                  eventType === "sell" ? tokens.color.terracotta : tokens.color.green,
              }}
            >
              {eventType === "sell"
                ? `Credits ${fundingAccount} Rp ${fmtPlain(parseFloat(cashAmount || "0"))}, −${quantity} ${ticker}`
                : `Debits ${fundingAccount} Rp ${fmtPlain(parseFloat(cashAmount || "0"))}, +${quantity} ${ticker}`}
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
                (isFunded && !(parseFloat(cashAmount) > 0))
              }
            >
              {saving
                ? "Saving…"
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
