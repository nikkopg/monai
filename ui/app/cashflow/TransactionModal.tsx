"use client";

import { useEffect, useState } from "react";

import { tokens, card, input, btn, label } from "../styles";

// Categories became first-class hierarchy rows in Phase 11: GET /categories
// returns a tree, and a name the backend does not recognise resolves to
// Uncategorized rather than creating anything. Creating categories therefore
// lives in Settings > Categories, not in this modal.
type CategoryNode = {
  id: number;
  name: string;
  is_system: boolean;
  children: CategoryNode[];
};

// Depth-first flatten. A record may be assigned at ANY level, so group nodes
// and their children are both selectable. System nodes (Transfer,
// Uncategorized) are omitted: "(no category)" already resolves to
// Uncategorized server-side, and transfer legs are not hand-picked here.
function flattenCategories(
  nodes: CategoryNode[],
  depth = 0
): { name: string; depth: number }[] {
  return nodes.flatMap((n) =>
    n.is_system
      ? []
      : [
          { name: n.name, depth },
          ...flattenCategories(n.children ?? [], depth + 1),
        ]
  );
}

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

// Expense / Income / Transfer segmented control (REC-04, D-01). Expense
// default on create. An existing transfer leg (edit mode) initializes to
// "transfer" too but with the control locked — see `locked` below.
type Segment = "expense" | "income" | "transfer";
const SEGMENTS: readonly Segment[] = ["expense", "income", "transfer"];

// Unsigned magnitude -> signed amount, sign derived from the segment (D-02),
// retiring the old "negative = expense" manual-sign foot-gun. Income and a
// fresh Transfer create both stay positive; Expense negates. `originalSign`
// is only consulted when editing an existing transfer leg (segment forced to
// "transfer" while isEdit) — that path must preserve the row's stored sign
// untouched (UI-SPEC Interaction States #7) rather than re-derive it, since
// a transfer leg can legitimately be stored negative or positive depending
// on which side of the pair it is.
function signedAmount(
  magnitude: string,
  segment: Segment,
  originalSign: 1 | -1 = 1
): number {
  const n = Math.abs(parseFloat(magnitude));
  if (segment === "expense") return -n;
  if (segment === "income") return n;
  return n * originalSign;
}

export default function TransactionModal({
  editingTx,
  accounts,
  onClose,
  onSaved,
}: Props) {
  const isEdit = editingTx != null;
  // Editing an existing transfer leg locks the segmented control to
  // "transfer" and keeps the row on the legacy single-leg PUT path — see the
  // segmented control and handleSubmit below (D-03 / RESEARCH Pitfall 1 /
  // UI-SPEC Interaction States #7).
  const locked = isEdit && editingTx!.is_transfer;

  const [segment, setSegment] = useState<Segment>(() => {
    if (editingTx?.is_transfer) return "transfer";
    if (editingTx) return editingTx.amount < 0 ? "expense" : "income";
    return "expense"; // D-01 default, create mode
  });

  const [date, setDate] = useState(
    toLocalDatetimeInputValue(editingTx ? new Date(editingTx.date) : new Date())
  );
  // Unsigned magnitude — the sign is derived from `segment` at submit time
  // (D-02), so edit mode reverse-maps the stored signed amount to its
  // absolute value here.
  const [amount, setAmount] = useState(
    editingTx ? String(Math.abs(editingTx.amount)) : ""
  );
  const [currency, setCurrency] = useState("IDR"); // D-05, no FX/enum
  // Category is a select sourced from the GET /categories tree.
  // `categorySelection` holds the chosen <select> value: "" -> (no category),
  // otherwise the exact stored category name.
  const [categorySelection, setCategorySelection] = useState(
    editingTx?.category ?? ""
  );
  const [categories, setCategories] = useState<
    { name: string; depth: number }[]
  >([]);
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

  // Fetch existing category names on mount (the modal is conditionally
  // rendered, so this runs each time it opens). On failure, degrade to an
  // empty list — (no category) and + New category… remain usable.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/categories");
        if (!r.ok) return;
        const tree: CategoryNode[] = await r.json();
        if (!cancelled) setCategories(flattenCategories(tree ?? []));
      } catch {
        // leave categories empty — field still functional
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Options for the category select, in order: stored names from the fetch,
  // plus the edit-mode current category if it is not (yet) in the list so
  // opening the edit modal never blanks or mutates the current category.
  const categoryOptions = (() => {
    const opts = [...categories];
    const current = editingTx?.category;
    if (current && !opts.some((o) => o.name === current)) {
      opts.unshift({ name: current, depth: 0 });
    }
    return opts;
  })();

  // Category cell is hidden on a fresh Transfer create (D-04, server-assigns
  // the category) but stays visible when locked to an existing transfer leg
  // — the row may carry pre-phase category data that hiding would silently
  // drop (UI-SPEC Interaction States #7).
  const categoryVisible = segment !== "transfer" || locked;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const selectedAccount = accounts.find(
        (a) => String(a.id) === accountId
      );
      // Category-or-null contract (unchanged): "" -> null (the backend
      // resolves null to Uncategorized); else the exact stored name,
      // byte-identical, so selection can never introduce a case variant.
      const categoryValue = categorySelection || null;
      // Edit-transfer-lock: preserve the row's original stored sign rather
      // than re-deriving it from `segment` (which is forced to "transfer"
      // for display only in that state) — sign stays untouched per UI-SPEC 7.
      const originalSign = editingTx && editingTx.amount < 0 ? -1 : 1;
      const body: Record<string, unknown> = {
        date: new Date(date).toISOString(),
        amount: signedAmount(amount, segment, originalSign),
        category: categoryValue,
        merchant: merchant || null,
        notes: notes || null,
        currency,
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
          {/* Segmented control (REC-04) — copied verbatim from
              settings/page.tsx L227-264 (UIR-07), swapping the option array
              and click handler. Locked (disabled) when editing an existing
              transfer leg so the user cannot switch away from Transfer. */}
          <div
            style={{
              display: "inline-flex",
              background: tokens.color.sidebar,
              border: `1px solid ${tokens.color.border2}`,
              borderRadius: 12,
              padding: 4,
              marginBottom: 18,
            }}
          >
            {SEGMENTS.map((s) => {
              const active = segment === s;
              return (
                <button
                  key={s}
                  type="button"
                  onClick={locked ? undefined : () => setSegment(s)}
                  style={{
                    border: "none",
                    borderRadius: 9,
                    padding: "8px 18px",
                    fontSize: 14,
                    fontWeight: active ? 600 : 500,
                    cursor: locked ? "default" : "pointer",
                    color: active ? tokens.color.ink : tokens.color.muted,
                    background: active ? "#fff" : "transparent",
                    boxShadow: active
                      ? "0 1px 2px rgba(40,34,24,.12)"
                      : "none",
                    opacity: locked ? 0.5 : 1,
                    transition: "all .2s ease",
                  }}
                >
                  {s[0].toUpperCase() + s.slice(1)}
                </button>
              );
            })}
          </div>
          {locked && (
            <div
              style={{
                fontSize: 13,
                color: tokens.color.muted,
                marginTop: -10,
                marginBottom: 14,
              }}
            >
              This is one leg of a transfer — full pair editing isn&apos;t
              available yet.
            </div>
          )}

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <div>
              <label style={label} htmlFor="tx-date">
                Date
              </label>
              <input
                id="tx-date"
                style={input}
                type="datetime-local"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
            <div>
              <label style={label} htmlFor="tx-amount">
                Amount
              </label>
              <input
                id="tx-amount"
                style={input}
                type="number"
                step="any"
                required
                value={amount}
                placeholder="25000"
                onChange={(e) => setAmount(e.target.value)}
              />
            </div>
            <div>
              <label style={label} htmlFor="tx-currency">
                Currency
              </label>
              <input
                id="tx-currency"
                style={input}
                type="text"
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              />
            </div>
            {categoryVisible && (
              <div>
                <label style={label} htmlFor="tx-category">
                  Category
                </label>
                <select
                  id="tx-category"
                  style={input}
                  value={categorySelection}
                  onChange={(e) => setCategorySelection(e.target.value)}
                >
                  <option value="">(no category)</option>
                  {categoryOptions.map((o) => (
                    <option key={o.name} value={o.name}>
                      {`${"\u00a0\u00a0".repeat(o.depth)}${o.name}`}
                    </option>
                  ))}
                </select>
              </div>
            )}
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
