"use client";

import { useState } from "react";

import { card, input, btn, label } from "../styles";
import ConfirmDialog from "./ConfirmDialog";

// ---------------------------------------------------------------------------
// AccountManager — list accounts with inline edit + delete (D-05/D-06).
// Delete flow:
//   1. ConfirmDialog "Delete this account? This can't be undone."
//   2. DELETE /api/accounts/{id}
//   3. If 422 -> read detail.affected_count, swap the dialog content (via the
//      children slot) for a destination-account <select> + reassign copy.
//   4. On confirming the destination, re-issue DELETE with ?reassign_to=.
// ---------------------------------------------------------------------------

// Only id/name are needed here — accepts either the plain /api/accounts
// shape or the richer per-account balance rows from GET /cashflow/summary
// (current_balance/period_net are simply ignored by this component).
export type Account = { id: number; name: string };

type Props = {
  accounts: Account[];
  onChanged: () => void;
};

type DeleteFlowState =
  | { stage: "idle" }
  | { stage: "confirm"; account: Account }
  | { stage: "reassign"; account: Account; affectedCount: number; targetId: string };

export default function AccountManager({ accounts, onChanged }: Props) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleteFlow, setDeleteFlow] = useState<DeleteFlowState>({ stage: "idle" });

  async function saveAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await fetch("/api/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName }),
      });
      if (r.ok) {
        setNewName("");
        setAdding(false);
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save account: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save account: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  async function saveEdit(id: number) {
    setError(null);
    try {
      const r = await fetch(`/api/accounts/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName }),
      });
      if (r.ok) {
        setEditingId(null);
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save account: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save account: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  async function confirmDelete(account: Account) {
    setError(null);
    try {
      const r = await fetch(`/api/accounts/${account.id}`, { method: "DELETE" });
      if (r.ok) {
        setDeleteFlow({ stage: "idle" });
        onChanged();
        return;
      }
      if (r.status === 422) {
        const errBody = await r.json().catch(() => ({}));
        const affectedCount = errBody?.detail?.affected_count ?? 0;
        const otherAccounts = accounts.filter((a) => a.id !== account.id);
        setDeleteFlow({
          stage: "reassign",
          account,
          affectedCount,
          targetId: otherAccounts[0] ? String(otherAccounts[0].id) : "",
        });
        return;
      }
      const detail = await extractDetail(r);
      setError(`Couldn't save account: ${detail}. Nothing was changed.`);
      setDeleteFlow({ stage: "idle" });
    } catch (e) {
      setError(
        `Couldn't save account: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
      setDeleteFlow({ stage: "idle" });
    }
  }

  async function confirmReassignDelete() {
    if (deleteFlow.stage !== "reassign") return;
    const { account, targetId } = deleteFlow;
    setError(null);
    try {
      const r = await fetch(
        `/api/accounts/${account.id}?reassign_to=${targetId}`,
        { method: "DELETE" }
      );
      if (r.ok) {
        setDeleteFlow({ stage: "idle" });
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save account: ${detail}. Nothing was changed.`);
        setDeleteFlow({ stage: "idle" });
      }
    } catch (e) {
      setError(
        `Couldn't save account: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
      setDeleteFlow({ stage: "idle" });
    }
  }

  return (
    <section style={card}>
      <label style={label}>Accounts</label>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <tbody>
          {accounts.map((a) => (
            <tr key={a.id} style={{ borderTop: "1px solid #e7e1d5" }}>
              <td style={{ padding: "8px 4px" }}>
                {editingId === a.id ? (
                  <input
                    style={input}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                  />
                ) : (
                  a.name
                )}
              </td>
              <td style={{ padding: "8px 4px", textAlign: "right", whiteSpace: "nowrap" }}>
                {editingId === a.id ? (
                  <>
                    <button
                      type="button"
                      onClick={() => saveEdit(a.id)}
                      style={{ ...btn, padding: "4px 10px", fontSize: 12, marginRight: 6 }}
                    >
                      Save account
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      style={{
                        background: "transparent",
                        color: "#8b8474",
                        border: "none",
                        fontSize: 12,
                        cursor: "pointer",
                      }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <span
                      role="button"
                      onClick={() => {
                        setEditingId(a.id);
                        setEditName(a.name);
                      }}
                      style={{ color: "#8b8474", cursor: "pointer", marginRight: 12, fontSize: 12 }}
                    >
                      Edit
                    </span>
                    <span
                      role="button"
                      onClick={() => setDeleteFlow({ stage: "confirm", account: a })}
                      style={{ color: "#b5503f", cursor: "pointer", fontSize: 12 }}
                    >
                      Delete
                    </span>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 12 }}>
        {adding ? (
          <form onSubmit={saveAdd} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              style={{ ...input, width: 200 }}
              value={newName}
              placeholder="Account name"
              onChange={(e) => setNewName(e.target.value)}
              required
            />
            <button style={btn} type="submit">
              Add account
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              style={{
                background: "transparent",
                color: "#8b8474",
                border: "none",
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
          </form>
        ) : (
          <button type="button" style={btn} onClick={() => setAdding(true)}>
            Add account
          </button>
        )}
      </div>

      {error && (
        <div style={{ color: "#b5503f", fontSize: 12, marginTop: 8 }}>{error}</div>
      )}

      {deleteFlow.stage === "confirm" && (
        <ConfirmDialog
          message="Delete this account? This can't be undone."
          confirmLabel="Delete"
          onCancel={() => setDeleteFlow({ stage: "idle" })}
          onConfirm={() => confirmDelete(deleteFlow.account)}
        />
      )}

      {deleteFlow.stage === "reassign" && (
        <ConfirmDialog
          message={`${deleteFlow.affectedCount} transactions use this account — choose a destination account to reassign them, or cancel.`}
          confirmLabel="Reassign & delete"
          onCancel={() => setDeleteFlow({ stage: "idle" })}
          onConfirm={confirmReassignDelete}
        >
          <select
            style={input}
            value={deleteFlow.targetId}
            onChange={(e) =>
              setDeleteFlow({ ...deleteFlow, targetId: e.target.value })
            }
          >
            {accounts
              .filter((a) => a.id !== deleteFlow.account.id)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </ConfirmDialog>
      )}
    </section>
  );
}

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
