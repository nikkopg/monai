"use client";

import { useEffect, useRef, useState } from "react";

import { tokens, card, input, btn, btnDark, dangerBtn } from "../styles";
import TransactionModal, {
  type Tx as ModalTx,
  type AccountOption,
} from "../cashflow/TransactionModal";
import ConfirmDialog from "../cashflow/ConfirmDialog";

// ---------------------------------------------------------------------------
// Records ledger (REC-01/02/03/05) — date-grouped transaction history with a
// full server-side filter bar, transfer-pair collapse, multi-select bulk
// delete/recategorize, and load-more paging. Pure composition: reuses
// TransactionModal (row edit + Phase-16 transfer-leg-locked mode),
// ConfirmDialog (bulk/pair delete), and the 17-03 extended GET /transactions
// + bulk endpoints. Turns ui/e2e/records.spec.ts (17-02) GREEN.
// ---------------------------------------------------------------------------

type Tx = ModalTx & { transfer_pair_id: number | null };

// Categories are a 3-level hierarchy (GET /categories). Mirrors
// TransactionModal.tsx's local flattenCategories helper verbatim — not
// exported anywhere in the codebase today, so duplicated here rather than
// introducing a new shared module for a single small pure function.
type CategoryNode = {
  id: number;
  name: string;
  is_system: boolean;
  children: CategoryNode[];
};

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

type LedgerRow =
  | { kind: "single"; tx: Tx }
  | { kind: "transfer-pair"; legA: Tx; legB: Tx | null };

// Copied verbatim from 17-RESEARCH.md "Code Examples > Transfer-pair
// collapse — client-side grouping (D-07)". Degrades gracefully (legB: null)
// when a filtered view only surfaces one leg of a pair — must never throw.
function collapseTransferPairs(rows: Tx[]): LedgerRow[] {
  const seen = new Set<number>();
  const result: LedgerRow[] = [];
  for (const tx of rows) {
    if (tx.transfer_pair_id == null) {
      result.push({ kind: "single", tx });
      continue;
    }
    if (seen.has(tx.transfer_pair_id)) continue; // already emitted this pair
    seen.add(tx.transfer_pair_id);
    const sibling = rows.find(
      (r) => r.transfer_pair_id === tx.transfer_pair_id && r.id !== tx.id
    );
    result.push({ kind: "transfer-pair", legA: tx, legB: sibling ?? null });
  }
  return result;
}

// Local calendar date grouping (day-group headers, D-01 presentation-only
// rule) — never UTC-slice a date string, always resolve through Date's
// local getters so "Today"/"Yesterday" match the viewer's clock.
function localDateKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(
    2,
    "0"
  )}-${String(d.getDate()).padStart(2, "0")}`;
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const startOfDay = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

// Same money/signed convention as cashflow/page.tsx — plain grouped digits
// (single-currency IDR, no symbol invented), `signed` adds an explicit +/-.
const money = (n: number) => new Intl.NumberFormat("en-US").format(Math.round(n));
const signed = (n: number) =>
  new Intl.NumberFormat("en-US", { signDisplay: "always" }).format(
    Math.round(n)
  );

// ---------------------------------------------------------------------------
// Ledger row shell (Component 4/5) — copied verbatim from cashflow/page.tsx's
// recent-transactions row (L742-828) with one addition: a leading 28px
// checkbox gutter (Component 6). Shared by normal rows, degraded transfer
// legs, and collapsed transfer-pair rows via props (glyph/primary/meta/
// amount vary; the shell + interaction wiring is identical).
// ---------------------------------------------------------------------------
function LedgerRowShell({
  tint,
  glyph,
  primary,
  meta,
  amountText,
  amountColor,
  checked,
  onToggle,
  onEdit,
  onDelete,
}: {
  tint: string;
  glyph: React.ReactNode;
  primary: React.ReactNode;
  meta: React.ReactNode;
  amountText: string;
  amountColor: string;
  checked: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "12px 0",
        borderTop: `1px solid ${tokens.color.borderInner}`,
      }}
    >
      <span style={{ width: 28, flexShrink: 0 }}>
        <input type="checkbox" checked={checked} onChange={onToggle} />
      </span>
      <span
        style={{
          width: 38,
          height: 38,
          borderRadius: 11,
          background: tint,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 13,
          fontWeight: 600,
          color: tokens.color.muted3,
          flexShrink: 0,
        }}
      >
        {glyph}
      </span>
      {/* Spans, not divs, below — Playwright's `div:has-text()` idiom (used
          by records.spec.ts to locate a specific row via .first()/.last())
          matches every ANCESTOR div wrapping the text too; keeping the outer
          row above as the ONLY div in this subtree makes it the sole match. */}
      <span style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
        <span
          style={{
            display: "block",
            fontSize: 14,
            fontWeight: 500,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {primary}
        </span>
        <span style={{ display: "block", fontSize: 12, color: tokens.color.muted2 }}>
          {meta}
        </span>
      </span>
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
          color: amountColor,
          whiteSpace: "nowrap",
        }}
      >
        {amountText}
      </div>
      <div style={{ display: "flex", gap: 12, flexShrink: 0 }}>
        <span
          role="button"
          onClick={onEdit}
          style={{ color: tokens.color.muted2, cursor: "pointer", fontSize: 12 }}
        >
          Edit
        </span>
        <span
          role="button"
          onClick={onDelete}
          style={{ color: tokens.color.terracotta, cursor: "pointer", fontSize: 12 }}
        >
          Delete
        </span>
      </div>
    </div>
  );
}

type DeleteTarget = { kind: "single"; tx: Tx } | { kind: "pair"; id: number };

export default function RecordsPage() {
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [categoryTree, setCategoryTree] = useState<CategoryNode[]>([]);
  const categoryOptions = flattenCategories(categoryTree);

  // Filter bar (Component 2) — locked field order: Search, Account, Category,
  // Type, Min, Max, Show-transfers. Any change debounces a refetch (300ms)
  // and ALWAYS resets offset to 0.
  const [q, setQ] = useState("");
  const [accountId, setAccountId] = useState("");
  const [category, setCategory] = useState("");
  const [type, setType] = useState("");
  const [amountMin, setAmountMin] = useState("");
  const [amountMax, setAmountMax] = useState("");
  const [showTransfers, setShowTransfers] = useState(true);

  const [txs, setTxs] = useState<Tx[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingTx, setEditingTx] = useState<ModalTx | null>(null);

  const [deletingTarget, setDeletingTarget] = useState<DeleteTarget | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [recatCategory, setRecatCategory] = useState("");
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [skipNote, setSkipNote] = useState<string | null>(null);

  const didMountRef = useRef(false);

  async function loadSupport() {
    try {
      const [accR, catR] = await Promise.all([
        fetch("/api/accounts"),
        fetch("/api/categories"),
      ]);
      if (accR.ok) setAccounts(await accR.json());
      if (catR.ok) setCategoryTree(await catR.json());
    } catch {
      // filter/category selects degrade to empty lists — the ledger fetch
      // below is independent and still works.
    }
  }

  function buildParams(atOffset: number): URLSearchParams {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (accountId) p.set("account_id", accountId);
    if (category) p.set("category", category);
    if (type) p.set("type", type);
    if (amountMin) p.set("amount_min", amountMin);
    if (amountMax) p.set("amount_max", amountMax);
    p.set("include_transfers", String(showTransfers));
    p.set("limit", "100");
    p.set("offset", String(atOffset));
    return p;
  }

  async function load(reset: boolean) {
    const atOffset = reset ? 0 : offset;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/transactions?${buildParams(atOffset).toString()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const rows: Tx[] = await r.json();
      setTxs((prev) => (reset ? rows : [...prev, ...rows]));
      setOffset(atOffset + rows.length);
      setHasMore(rows.length === 100);
    } catch {
      setError(
        "Couldn't load your records — check the backend is running and reload the page."
      );
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    await load(true);
  }

  useEffect(() => {
    loadSupport();
    load(true);
  }, []);

  // Debounced refetch on any filter change (REC-02) — offset always resets.
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    const timer = setTimeout(() => load(true), 300);
    return () => clearTimeout(timer);
  }, [q, accountId, category, type, amountMin, amountMax, showTransfers]);

  // Bulk-recategorize target defaults to the first non-system category once
  // the tree loads (Copywriting Contract).
  useEffect(() => {
    if (categoryOptions.length && !recatCategory) {
      setRecatCategory(categoryOptions[0].name);
    }
  }, [categoryTree]);

  function accountName(id: number | null): string {
    return accounts.find((a) => a.id === id)?.name ?? "Unknown";
  }

  function toggleSelection(ids: number[]) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allSelected = ids.every((id) => next.has(id));
      if (allSelected) ids.forEach((id) => next.delete(id));
      else ids.forEach((id) => next.add(id));
      return next;
    });
  }

  async function confirmDelete() {
    if (!deletingTarget) return;
    setDeleteError(null);
    const id = deletingTarget.kind === "single" ? deletingTarget.tx.id : deletingTarget.id;
    try {
      const r = await fetch(`/api/transactions/${id}`, { method: "DELETE" });
      if (r.ok) {
        setDeletingTarget(null);
        await refresh();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setDeleteError(`Couldn't save transaction: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setDeleteError(
        `Couldn't save transaction: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  async function doBulkRecategorize() {
    setBulkError(null);
    setSkipNote(null);
    try {
      const r = await fetch("/api/transactions/bulk-recategorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: Array.from(selectedIds), category: recatCategory }),
      });
      if (r.ok) {
        const body = await r.json();
        setSelectedIds(new Set());
        if (body.skipped?.length) {
          setSkipNote(
            `${body.recategorized?.length ?? 0} recategorized. ${
              body.skipped.length
            } transfer legs skipped — transfers are categorized automatically.`
          );
        }
        await refresh();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setBulkError(`Couldn't recategorize these records: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setBulkError(
        `Couldn't recategorize these records: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  async function doBulkDelete() {
    setBulkError(null);
    try {
      const r = await fetch("/api/transactions/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      });
      if (r.ok) {
        setSelectedIds(new Set());
        setBulkDeleteOpen(false);
        await refresh();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setBulkError(`Couldn't delete these records: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setBulkError(
        `Couldn't delete these records: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  function ledgerRowFor(row: LedgerRow) {
    if (row.kind === "single") {
      const tx = row.tx;
      const isIncome = tx.amount >= 0 && !tx.is_transfer;
      const tint = tx.is_transfer
        ? tokens.color.tintNeutral
        : isIncome
        ? tokens.color.tintGreen
        : tokens.color.tintWarm;
      return (
        <LedgerRowShell
          key={tx.id}
          tint={tint}
          glyph={(tx.category || tx.merchant || "?").slice(0, 1).toUpperCase()}
          primary={tx.merchant || tx.category || "Transaction"}
          meta={`${(tx.category || "Uncategorized") + (tx.is_transfer ? " · transfer" : "")} · ${tx.date.slice(0, 10)}`}
          amountText={signed(tx.amount)}
          amountColor={tx.amount < 0 ? tokens.color.terracotta : tokens.color.green}
          checked={selectedIds.has(tx.id)}
          onToggle={() => toggleSelection([tx.id])}
          onEdit={() => {
            setEditingTx(tx);
            setModalOpen(true);
          }}
          onDelete={() => setDeletingTarget({ kind: "single", tx })}
        />
      );
    }

    const { legA, legB } = row;
    if (legB) {
      // Collapsed transfer pair (Component 5) — From = the outgoing
      // (negative) leg, To = the incoming (positive) leg.
      const outgoing = legA.amount < 0 ? legA : legB;
      const incoming = legA.amount < 0 ? legB : legA;
      return (
        <LedgerRowShell
          key={legA.id}
          tint={tokens.color.tintNeutral}
          glyph="⇄"
          primary={`Transfer: ${accountName(outgoing.account_id)} → ${accountName(
            incoming.account_id
          )}`}
          meta={legA.date.slice(0, 10)}
          amountText={money(Math.abs(legA.amount))}
          amountColor={tokens.color.ink}
          checked={selectedIds.has(legA.id) && selectedIds.has(legB.id)}
          onToggle={() => toggleSelection([legA.id, legB.id])}
          onEdit={() => {
            setEditingTx(legA);
            setModalOpen(true);
          }}
          onDelete={() => setDeletingTarget({ kind: "pair", id: legA.id })}
        />
      );
    }

    // Degraded case — sibling not present in the filtered result set
    // (RESEARCH A3). Render as a normal row with a muted "(transfer)" tag;
    // Edit/Delete still route through the pair-aware locked-modal/confirm
    // path since this is still one leg of a transfer.
    const isIncome = legA.amount >= 0 && !legA.is_transfer;
    const tint = legA.is_transfer
      ? tokens.color.tintNeutral
      : isIncome
      ? tokens.color.tintGreen
      : tokens.color.tintWarm;
    return (
      <LedgerRowShell
        key={legA.id}
        tint={tint}
        glyph={(legA.category || legA.merchant || "?").slice(0, 1).toUpperCase()}
        primary={
          <>
            {legA.merchant || legA.category || "Transaction"}
            <span style={{ fontSize: 12, color: tokens.color.muted, fontWeight: 400 }}>
              {" "}(transfer)
            </span>
          </>
        }
        meta={`${legA.category || "Uncategorized"} · ${legA.date.slice(0, 10)}`}
        amountText={signed(legA.amount)}
        amountColor={legA.amount < 0 ? tokens.color.terracotta : tokens.color.green}
        checked={selectedIds.has(legA.id)}
        onToggle={() => toggleSelection([legA.id])}
        onEdit={() => {
          setEditingTx(legA);
          setModalOpen(true);
        }}
        onDelete={() => setDeletingTarget({ kind: "pair", id: legA.id })}
      />
    );
  }

  // ---- derived: day-group + daily net (Component 3, locked rule) ----------
  const groups = (() => {
    const map = new Map<string, Tx[]>();
    for (const t of txs) {
      const key = localDateKey(t.date);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(t);
    }
    return Array.from(map.entries()).map(([key, rows]) => ({
      key,
      label: dayLabel(rows[0].date),
      rows,
    }));
  })();

  const filtersActive =
    q !== "" ||
    accountId !== "" ||
    category !== "" ||
    type !== "" ||
    amountMin !== "" ||
    amountMax !== "" ||
    !showTransfers;

  return (
    // section, not div — records.spec.ts locates specific rows via
    // `div:has-text()` (.first()/.last()); a div:page-root would also match
    // any row's text as an ancestor, so every wrapper above row-level uses a
    // non-div tag, leaving each ledger row as the sole matching div.
    <section className="tab-in" style={{ padding: "40px 44px 60px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 30,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: tokens.color.muted2,
              marginBottom: 6,
            }}
          >
            Ledger
          </div>
          <h1
            style={{
              fontFamily: tokens.font.serif,
              fontWeight: 400,
              fontSize: 40,
              margin: 0,
              letterSpacing: "-.5px",
            }}
          >
            Records
          </h1>
        </div>
        <button
          type="button"
          style={btnDark}
          onClick={() => {
            setEditingTx(null);
            setModalOpen(true);
          }}
        >
          + Add record
        </button>
      </div>

      {error && (
        <div style={{ ...card, color: tokens.color.terracotta }}>{error}</div>
      )}

      {!error && (
        <section style={{ ...card, marginBottom: 18 }}>
          {selectedIds.size === 0 ? (
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: tokens.space.sm,
                background: tokens.color.sidebar,
                borderRadius: tokens.radius.md,
                padding: "8px 12px",
                marginBottom: tokens.space.md,
              }}
            >
              <input
                style={{ ...input, flex: 2, minWidth: 180 }}
                placeholder="Search merchant or notes…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <select
                style={{ ...input, flex: 1 }}
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
              >
                <option value="">All accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <select
                style={{ ...input, flex: 1 }}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">All categories</option>
                {categoryOptions.map((o) => (
                  <option key={o.name} value={o.name}>
                    {`${"  ".repeat(o.depth)}${o.name}`}
                  </option>
                ))}
              </select>
              <select
                style={{ ...input, flex: 1 }}
                value={type}
                onChange={(e) => setType(e.target.value)}
              >
                <option value="">All types</option>
                <option value="expense">Expense</option>
                <option value="income">Income</option>
                <option value="transfer">Transfer</option>
              </select>
              <input
                style={{ ...input, width: 110 }}
                type="number"
                placeholder="Min amount"
                value={amountMin}
                onChange={(e) => setAmountMin(e.target.value)}
              />
              <input
                style={{ ...input, width: 110 }}
                type="number"
                placeholder="Max amount"
                value={amountMax}
                onChange={(e) => setAmountMax(e.target.value)}
              />
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  flexShrink: 0,
                  fontSize: 13,
                  color: tokens.color.muted3,
                }}
              >
                <input
                  type="checkbox"
                  checked={showTransfers}
                  onChange={(e) => setShowTransfers(e.target.checked)}
                />
                Show transfers
              </label>
            </div>
          ) : (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: tokens.space.sm,
                background: tokens.color.sidebar,
                borderRadius: tokens.radius.md,
                padding: "8px 12px",
                marginBottom: tokens.space.md,
              }}
            >
              <span style={{ fontSize: 12, fontWeight: 600 }}>
                {selectedIds.size} selected
              </span>
              <div
                style={{
                  marginLeft: "auto",
                  display: "flex",
                  alignItems: "center",
                  gap: tokens.space.sm,
                }}
              >
                <select
                  style={{ ...input, width: 160 }}
                  value={recatCategory}
                  onChange={(e) => setRecatCategory(e.target.value)}
                >
                  {categoryOptions.map((o) => (
                    <option key={o.name} value={o.name}>
                      {`${"  ".repeat(o.depth)}${o.name}`}
                    </option>
                  ))}
                </select>
                <button type="button" style={btn} onClick={doBulkRecategorize}>
                  Recategorize
                </button>
                <button
                  type="button"
                  style={dangerBtn}
                  onClick={() => setBulkDeleteOpen(true)}
                >
                  Delete
                </button>
                <span
                  role="button"
                  onClick={() => setSelectedIds(new Set())}
                  style={{ color: tokens.color.muted, cursor: "pointer", fontSize: 12 }}
                >
                  Cancel selection
                </span>
              </div>
            </div>
          )}

          {bulkError && (
            <div style={{ color: tokens.color.terracotta, fontSize: 12, marginBottom: tokens.space.sm }}>
              {bulkError}
            </div>
          )}
          {skipNote && (
            <div style={{ color: tokens.color.muted, fontSize: 12, marginBottom: tokens.space.sm }}>
              {skipNote}
            </div>
          )}

          {loading && txs.length === 0 ? (
            <div style={{ fontSize: 14, color: tokens.color.muted, paddingTop: 10 }}>
              Loading your records…
            </div>
          ) : txs.length === 0 ? (
            <div style={{ paddingTop: 10 }}>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
                {filtersActive ? "No records match these filters." : "No records yet."}
              </div>
              <div style={{ color: tokens.color.muted, fontSize: 14 }}>
                {filtersActive
                  ? "Try widening your search or clearing a filter."
                  : "Add your first record to start building your history."}
              </div>
            </div>
          ) : (
            <>
              {groups.map((g, idx) => {
                const net = g.rows
                  .filter((r) => r.transfer_pair_id == null)
                  .reduce((s, r) => s + r.amount, 0);
                return (
                  <section key={g.key}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        padding: "10px 0 6px",
                        borderTop: idx === 0 ? "none" : `1px solid ${tokens.color.border}`,
                      }}
                    >
                      <span style={{ fontSize: 12, fontWeight: 600 }}>{g.label}</span>
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 600,
                          fontVariantNumeric: "tabular-nums",
                          color: net >= 0 ? tokens.color.green : tokens.color.terracotta,
                        }}
                      >
                        Net {signed(net)}
                      </span>
                    </div>
                    {collapseTransferPairs(g.rows).map((row) => ledgerRowFor(row))}
                  </section>
                );
              })}
              {hasMore && (
                <div style={{ textAlign: "center", marginTop: 14 }}>
                  <button type="button" style={btn} onClick={() => load(false)}>
                    Load 100 more
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {modalOpen && (
        <TransactionModal
          editingTx={editingTx}
          accounts={accounts}
          onClose={() => {
            setModalOpen(false);
            setEditingTx(null);
          }}
          onSaved={refresh}
        />
      )}

      {deletingTarget && (
        <ConfirmDialog
          message={
            deletingTarget.kind === "single"
              ? "Delete this transaction? This can't be undone."
              : "Delete this transfer? Both linked records will be removed. This can't be undone."
          }
          confirmLabel="Delete"
          onCancel={() => setDeletingTarget(null)}
          onConfirm={confirmDelete}
        />
      )}
      {deleteError && (
        <div style={{ color: tokens.color.terracotta, fontSize: 12, marginTop: 8 }}>
          {deleteError}
        </div>
      )}

      {bulkDeleteOpen && (
        <ConfirmDialog
          message={`Delete ${selectedIds.size} records? Transfer pairs are deleted together. This can't be undone.`}
          confirmLabel="Delete"
          onCancel={() => setBulkDeleteOpen(false)}
          onConfirm={doBulkDelete}
        />
      )}
    </section>
  );
}
