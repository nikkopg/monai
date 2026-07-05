"use client";

import { useState } from "react";

import { card, input, btn, label } from "../styles";

// ---------------------------------------------------------------------------
// TransactionModal — single shared component for BOTH create and edit (D-10).
// `editingTx == null` -> create mode ("Add transaction"); populated -> edit
// mode ("Edit transaction" / "Save changes"). Submits POST /api/transactions
// (create) or PUT /api/transactions/{id} (edit) through the Next.js proxy,
// which injects the API key server-side. On success calls onSaved() (parent
// refetches list + summary, Pattern 5) then onClose().
// ---------------------------------------------------------------------------

export type Tx = {
  id: number;
  date: string;
  amount: number;
  category: string | null;
  merchant: string | null;
  account_id: number | null;
  notes: string | null;
  is_transfer: boolean;
};

export type AccountOption = { id: number; name: string };

type Props = {
  editingTx: Tx | null;
  accounts: AccountOption[];
  onClose: () => void;
  onSaved: () => void;
};

// Format a Date (or ISO string) as a `datetime-local`-compatible string using
// LOCAL wall-clock components — reused verbatim from page.tsx (WR-06: avoids
// the UTC/local offset shift toISOString() would introduce).
function toLocalDatetimeInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

export default function TransactionModal({
  editingTx,
  accounts,
  onClose,
  onSaved,
}: Props) {
  const isEdit = editingTx != null;

  const [date, setDate] = useState(
    toLocalDatetimeInputValue(editingTx ? new Date(editingTx.date) : new Date())
  );
  const [amount, setAmount] = useState(
    editingTx ? String(editingTx.amount) : ""
  );
  const [category, setCategory] = useState(editingTx?.category ?? "");
  const [merchant, setMerchant] = useState(editingTx?.merchant ?? "");
  const [accountId, setAccountId] = useState<string>(
    editingTx?.account_id != null
      ? String(editingTx.account_id)
      : accounts[0]
      ? String(accounts[0].id)
      : ""
  );
  const [notes, setNotes] = useState(editingTx?.notes ?? "");
  const [isTransfer, setIsTransfer] = useState(editingTx?.is_transfer ?? false);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const selectedAccount = accounts.find(
        (a) => String(a.id) === accountId
      );
      const body: Record<string, unknown> = {
        date: new Date(date).toISOString(),
        amount: parseFloat(amount),
        category: category || null,
        merchant: merchant || null,
        notes: notes || null,
        is_transfer: isTransfer,
      };
      if (!isEdit) {
        // Create requires an `account` name (backend resolves/creates it).
        body.account = selectedAccount?.name ?? "Cash";
      } else if (selectedAccount) {
        body.account = selectedAccount.name;
      }

      const url = isEdit
        ? `/api/transactions/${editingTx!.id}`
        : "/api/transactions";
      const method = isEdit ? "PUT" : "POST";

      const r = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (r.ok) {
        onSaved();
        onClose();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setError(`Couldn't save transaction: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save transaction: ${
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
          {isEdit ? "Edit transaction" : "Add transaction"}
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
              <label style={label}>Date</label>
              <input
                style={input}
                type="datetime-local"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Amount (negative = expense)</label>
              <input
                style={input}
                type="number"
                step="any"
                required
                value={amount}
                placeholder="-25000"
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Category</label>
              <input
                style={input}
                value={category}
                placeholder="Food & Drinks"
                onChange={(e) => setCategory(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Merchant / note</label>
              <input
                style={input}
                value={merchant}
                placeholder="warung sate"
                onChange={(e) => setMerchant(e.target.value)}
              />
            </div>
            <div>
              <label style={label}>Account</label>
              <select
                style={input}
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={label}>Notes</label>
              <input
                style={input}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
              <label style={{ ...label, marginBottom: 10 }}>
                <input
                  type="checkbox"
                  checked={isTransfer}
                  onChange={(e) => setIsTransfer(e.target.checked)}
                  style={{ marginRight: 6 }}
                />
                Transfer
              </label>
            </div>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginTop: 16,
            }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                background: "transparent",
                color: "#9aa0a6",
                border: "none",
                padding: "8px 16px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button style={btn} type="submit" disabled={saving}>
              {saving
                ? "Saving…"
                : isEdit
                ? "Save changes"
                : "Add transaction"}
            </button>
            {error && (
              <span style={{ color: "#f87171", fontSize: 12 }}>{error}</span>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
