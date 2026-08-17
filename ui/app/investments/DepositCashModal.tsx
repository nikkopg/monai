"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label, tokens } from "../styles";

// ---------------------------------------------------------------------------
// DepositCashModal — liquid->investment cash deposit (XFER-02, D-03/D-04/D-07).
// Mirrors HoldingModal's overlay+card shell. Owns its own GET /api/accounts
// fetch on mount (the platform detail page fetches no account data) and
// client-filters to type === "liquid" — the "From account" field is always a
// <select> sourced from a fresh fetch, never free text (RESEARCH Pitfall 2:
// a mismatching name would silently fork a duplicate account via
// _get_or_create_account). POSTs /api/transactions/investment-transfer
// through the Next.js proxy (injects the API key server-side); on success
// calls onSaved() (parent refetches platform detail) then onClose(). No
// ConfirmDialog step — the neutral-ink preview line is the write-safety
// mechanism (D-07).
// ---------------------------------------------------------------------------

type Account = {
  id: number;
  name: string;
  type: string | null;
  currency: string | null;
};

type Props = {
  platformId: number;
  platformName: string;
  onClose: () => void;
  onSaved: () => void;
};

const fmtPlain = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));

async function extractDetail(r: Response): Promise<string> {
  let detail = `HTTP ${r.status}`;
  try {
    const errBody = await r.json();
    detail =
      typeof errBody?.detail === "string"
        ? errBody.detail
        : errBody?.detail?.message ?? detail;
  } catch {
    // keep the status-based detail
  }
  return detail;
}

export default function DepositCashModal({
  platformId,
  platformName,
  onClose,
  onSaved,
}: Props) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [fromAccount, setFromAccount] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("IDR");
  const [date, setDate] = useState("");
  const [notes, setNotes] = useState("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const liquidAccounts = accounts.filter((a) => a.type === "liquid");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/accounts");
        if (!r.ok) throw new Error("fetch failed");
        const data: Account[] = await r.json();
        if (!cancelled) {
          setAccounts(data);
          const liquid = data.filter((a) => a.type === "liquid");
          if (liquid.length > 0) setFromAccount(liquid[0].name);
        }
      } catch {
        // leave accounts empty; empty-state copy + disabled submit covers it
      } finally {
        if (!cancelled) setAccountsLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const parsedAmount = parseFloat(amount || "0");
  const canSubmit =
    !saving && liquidAccounts.length > 0 && !!fromAccount && parsedAmount > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      const body = {
        from_account: fromAccount,
        platform_id: platformId,
        amount: parseFloat(amount),
        currency: currency || "IDR",
        date: date || undefined,
        notes: notes || undefined,
      };
      const r = await fetch("/api/transactions/investment-transfer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        onSaved();
        onClose();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't deposit cash: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't deposit cash: ${
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
      onClick={onClose}
    >
      <div
        style={{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>
          Deposit cash — {platformName}
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
              <label style={label} htmlFor="deposit-cash-from-account">
                From account
              </label>
              <select
                id="deposit-cash-from-account"
                style={input}
                value={fromAccount}
                onChange={(e) => setFromAccount(e.target.value)}
                disabled={liquidAccounts.length === 0}
              >
                {liquidAccounts.map((a) => (
                  <option key={a.id} value={a.name}>
                    {a.name}
                  </option>
                ))}
              </select>
              {accountsLoaded && liquidAccounts.length === 0 && (
                <p style={{ ...label, fontSize: 11, marginTop: 4, color: tokens.color.terracotta }}>
                  No liquid accounts yet — add one in Cashflow before depositing cash.
                </p>
              )}
            </div>
            <div>
              <label style={label} htmlFor="deposit-cash-amount">
                Amount
              </label>
              <input
                id="deposit-cash-amount"
                style={input}
                type="number"
                step="any"
                required
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div>
              <label style={label} htmlFor="deposit-cash-currency">
                Currency
              </label>
              <input
                id="deposit-cash-currency"
                style={input}
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              />
            </div>
            <div>
              <label style={label} htmlFor="deposit-cash-date">
                Date
              </label>
              <input
                id="deposit-cash-date"
                style={input}
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
            <div style={{ gridColumn: "1 / -1" }}>
              <label style={label} htmlFor="deposit-cash-notes">
                Notes
              </label>
              <input
                id="deposit-cash-notes"
                style={input}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
          </div>

          {fromAccount && parsedAmount > 0 && (
            <p style={{ fontSize: 13, color: tokens.color.text, margin: "0 0 10px" }}>
              Moves Rp {fmtPlain(parsedAmount)} from {fromAccount} into {platformName}.
            </p>
          )}

          <div
            style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                color: "#8b8474",
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button style={btn} type="submit" disabled={!canSubmit}>
              {saving ? "Saving…" : "Deposit cash"}
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
