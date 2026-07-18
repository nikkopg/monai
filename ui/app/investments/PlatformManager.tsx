"use client";

import { useState } from "react";

import { card, input, btn, label } from "../styles";
import ConfirmDialog from "../cashflow/ConfirmDialog";

// ---------------------------------------------------------------------------
// PlatformManager — list platforms with inline edit + delete (D-12).
// Direct structural mirror of ../cashflow/AccountManager.tsx; the only
// entity-shape difference is the optional `kind` label alongside `name`.
// Delete flow:
//   1. ConfirmDialog "Delete this platform? This can't be undone."
//   2. DELETE /api/platforms/{id}
//   3. If 422 -> read detail.affected_count, swap the dialog content for a
//      destination-platform <select> + reassign copy.
//   4. On confirming the destination, re-issue DELETE with ?reassign_to=.
// ---------------------------------------------------------------------------

export type Platform = { id: number; name: string; kind: string | null };

type Props = {
  platforms: Platform[];
  onChanged: () => void;
};

type DeleteFlowState =
  | { stage: "idle" }
  | { stage: "confirm"; platform: Platform }
  | { stage: "reassign"; platform: Platform; affectedCount: number; targetId: string };

export default function PlatformManager({ platforms, onChanged }: Props) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleteFlow, setDeleteFlow] = useState<DeleteFlowState>({ stage: "idle" });

  async function saveAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await fetch("/api/platforms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName, kind: newKind || null }),
      });
      if (r.ok) {
        setNewName("");
        setNewKind("");
        setAdding(false);
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save platform: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save platform: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  async function saveEdit(id: number) {
    setError(null);
    try {
      const r = await fetch(`/api/platforms/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName }),
      });
      if (r.ok) {
        setEditingId(null);
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save platform: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't save platform: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  async function confirmDelete(platform: Platform) {
    setError(null);
    try {
      const r = await fetch(`/api/platforms/${platform.id}`, { method: "DELETE" });
      if (r.ok) {
        setDeleteFlow({ stage: "idle" });
        onChanged();
        return;
      }
      if (r.status === 422) {
        const errBody = await r.json().catch(() => ({}));
        const affectedCount = errBody?.detail?.affected_count ?? 0;
        const otherPlatforms = platforms.filter((p) => p.id !== platform.id);
        setDeleteFlow({
          stage: "reassign",
          platform,
          affectedCount,
          targetId: otherPlatforms[0] ? String(otherPlatforms[0].id) : "",
        });
        return;
      }
      const detail = await extractDetail(r);
      setError(`Couldn't save platform: ${detail}. Nothing was changed.`);
      setDeleteFlow({ stage: "idle" });
    } catch (e) {
      setError(
        `Couldn't save platform: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
      setDeleteFlow({ stage: "idle" });
    }
  }

  async function confirmReassignDelete() {
    if (deleteFlow.stage !== "reassign") return;
    const { platform, targetId } = deleteFlow;
    setError(null);
    try {
      const r = await fetch(
        `/api/platforms/${platform.id}?reassign_to=${targetId}`,
        { method: "DELETE" }
      );
      if (r.ok) {
        setDeleteFlow({ stage: "idle" });
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't save platform: ${detail}. Nothing was changed.`);
        setDeleteFlow({ stage: "idle" });
      }
    } catch (e) {
      setError(
        `Couldn't save platform: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
      setDeleteFlow({ stage: "idle" });
    }
  }

  const reassignTargetName =
    deleteFlow.stage === "reassign"
      ? platforms.find((p) => String(p.id) === deleteFlow.targetId)?.name ?? ""
      : "";

  return (
    <section style={card}>
      <label style={label}>Platforms</label>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <tbody>
          {platforms.map((p) => (
            <tr key={p.id} style={{ borderTop: "1px solid #e7e1d5" }}>
              <td style={{ padding: "8px 4px" }}>
                {editingId === p.id ? (
                  <input
                    style={input}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                  />
                ) : (
                  <>
                    {p.name}
                    {p.kind && (
                      <span style={{ color: "#8b8474", fontSize: 12, marginLeft: 8 }}>
                        {p.kind}
                      </span>
                    )}
                  </>
                )}
              </td>
              <td style={{ padding: "8px 4px", textAlign: "right", whiteSpace: "nowrap" }}>
                {editingId === p.id ? (
                  <>
                    <button
                      type="button"
                      onClick={() => saveEdit(p.id)}
                      style={{ ...btn, padding: "4px 10px", fontSize: 12, marginRight: 6 }}
                    >
                      Save platform
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
                        setEditingId(p.id);
                        setEditName(p.name);
                      }}
                      style={{ color: "#8b8474", cursor: "pointer", marginRight: 12, fontSize: 12 }}
                    >
                      Edit
                    </span>
                    <span
                      role="button"
                      onClick={() => setDeleteFlow({ stage: "confirm", platform: p })}
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

      {platforms.length === 0 && !adding && (
        <div style={{ color: "#8b8474", fontSize: 13, marginTop: 8 }}>
          No platforms yet. Add a platform (e.g. your brokerage or crypto app) to
          start grouping holdings — or log a holding first and assign a platform
          later.
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        {adding ? (
          <form onSubmit={saveAdd} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              style={{ ...input, width: 200 }}
              value={newName}
              placeholder="Platform name"
              onChange={(e) => setNewName(e.target.value)}
              required
            />
            <input
              style={{ ...input, width: 160 }}
              value={newKind}
              placeholder="e.g. brokerage, crypto app"
              onChange={(e) => setNewKind(e.target.value)}
            />
            <button style={btn} type="submit">
              Add platform
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
            Add platform
          </button>
        )}
      </div>

      {error && (
        <div style={{ color: "#b5503f", fontSize: 12, marginTop: 8 }}>{error}</div>
      )}

      {deleteFlow.stage === "confirm" && (
        <ConfirmDialog
          message="Delete this platform? This can't be undone."
          confirmLabel="Delete"
          onCancel={() => setDeleteFlow({ stage: "idle" })}
          onConfirm={() => confirmDelete(deleteFlow.platform)}
        />
      )}

      {deleteFlow.stage === "reassign" && (
        <ConfirmDialog
          message={`${deleteFlow.affectedCount} holdings use this platform — choose a destination platform to reassign them, or cancel.`}
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
            {platforms
              .filter((p) => p.id !== deleteFlow.platform.id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
          {reassignTargetName && (
            <p style={{ color: "#8b8474", fontSize: 12, margin: "8px 0 0" }}>
              Reassign {deleteFlow.affectedCount} holdings to &quot;{reassignTargetName}&quot;
              and delete &quot;{deleteFlow.platform.name}&quot;?
            </p>
          )}
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
