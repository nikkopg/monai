"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label } from "../styles";
import ConfirmDialog from "./ConfirmDialog";

// ---------------------------------------------------------------------------
// CategoryManager — rename + merge with live affected-count (D-09).
// Enumerates category names from GET /api/categories (the deterministic
// enumeration source — Plan 03 dependency, guaranteed present, no
// "if only the tool exists" branch). For each name, fetches its
// affected-count badge from GET /api/categories/{name}/affected-count.
// Rename is non-destructive (no ConfirmDialog); merge is destructive and
// shows the affected_count in a ConfirmDialog before POST /categories/merge.
// ---------------------------------------------------------------------------

type Props = {
  onChanged: () => void;
};

type MergeFlow =
  | { stage: "idle" }
  | { stage: "picking"; from: string; into: string }
  | { stage: "confirming"; from: string; into: string; affectedCount: number };

export default function CategoryManager({ onChanged }: Props) {
  const [categories, setCategories] = useState<string[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [renamingName, setRenamingName] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [mergeFlow, setMergeFlow] = useState<MergeFlow>({ stage: "idle" });
  const [error, setError] = useState<string | null>(null);

  async function loadCategories() {
    try {
      const r = await fetch("/api/categories");
      if (!r.ok) return;
      const data: { categories: string[] } = await r.json();
      setCategories(data.categories);
      // Fetch each row's affected-count badge.
      const entries = await Promise.all(
        data.categories.map(async (name) => {
          try {
            const cr = await fetch(
              `/api/categories/${encodeURIComponent(name)}/affected-count`
            );
            if (cr.ok) {
              const cd = await cr.json();
              return [name, cd.affected_count as number] as const;
            }
          } catch {
            // ignore per-row count failure
          }
          return [name, 0] as const;
        })
      );
      setCounts(Object.fromEntries(entries));
    } catch {
      // load failure — leave categories empty; page-level error banners
      // already cover the "backend down" case elsewhere on this page
    }
  }

  useEffect(() => {
    loadCategories();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitRename(oldName: string) {
    setError(null);
    try {
      const r = await fetch("/api/categories/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_name: oldName, new_name: renameValue }),
      });
      if (r.ok) {
        setRenamingName(null);
        await loadCategories();
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't rename category: ${detail}. Nothing was changed.`);
      }
    } catch (e) {
      setError(
        `Couldn't rename category: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
    }
  }

  function openMergePicker(from: string) {
    const others = categories.filter((c) => c !== from);
    setMergeFlow({ stage: "picking", from, into: others[0] ?? "" });
  }

  function proceedToConfirm() {
    if (mergeFlow.stage !== "picking") return;
    const { from, into } = mergeFlow;
    setMergeFlow({
      stage: "confirming",
      from,
      into,
      affectedCount: counts[from] ?? 0,
    });
  }

  async function submitMerge() {
    if (mergeFlow.stage !== "confirming") return;
    const { from, into } = mergeFlow;
    setError(null);
    try {
      const r = await fetch("/api/categories/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_name: from, into_name: into }),
      });
      if (r.ok) {
        setMergeFlow({ stage: "idle" });
        await loadCategories();
        onChanged();
      } else {
        const detail = await extractDetail(r);
        setError(`Couldn't merge category: ${detail}. Nothing was changed.`);
        setMergeFlow({ stage: "idle" });
      }
    } catch (e) {
      setError(
        `Couldn't merge category: ${
          e instanceof Error ? e.message : "Network error"
        }. Nothing was changed.`
      );
      setMergeFlow({ stage: "idle" });
    }
  }

  const badgeStyle: React.CSSProperties = {
    fontSize: 12,
    color: "#8b8474",
    background: "#e7e1d5",
    borderRadius: 999,
    padding: "2px 8px",
    marginLeft: 8,
  };

  return (
    <section style={card}>
      <label style={label}>Categories</label>

      {categories.length === 0 ? (
        <div>
          <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
            No categories yet.
          </div>
          <div style={{ color: "#8b8474", fontSize: 14 }}>
            Categories appear automatically once transactions are
            categorized — add a transaction with a category to get started.
          </div>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <tbody>
            {categories.map((name) => (
              <tr key={name} style={{ borderTop: "1px solid #e7e1d5" }}>
                <td style={{ padding: "8px 4px" }}>
                  {renamingName === name ? (
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <input
                        style={{ ...input, width: 200 }}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                      />
                      <button
                        type="button"
                        style={{ ...btn, padding: "4px 10px", fontSize: 12 }}
                        onClick={() => submitRename(name)}
                      >
                        Rename category
                      </button>
                      <button
                        type="button"
                        onClick={() => setRenamingName(null)}
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
                    </div>
                  ) : (
                    <>
                      {name}
                      <span style={badgeStyle}>{counts[name] ?? 0}</span>
                    </>
                  )}
                </td>
                <td style={{ padding: "8px 4px", textAlign: "right", whiteSpace: "nowrap" }}>
                  {renamingName !== name && (
                    <>
                      <span
                        role="button"
                        onClick={() => {
                          setRenamingName(name);
                          setRenameValue(name);
                        }}
                        style={{ color: "#8b8474", cursor: "pointer", marginRight: 12, fontSize: 12 }}
                      >
                        Rename
                      </span>
                      <span
                        role="button"
                        onClick={() => openMergePicker(name)}
                        style={{ color: "#8b8474", cursor: "pointer", fontSize: 12 }}
                      >
                        Merge into…
                      </span>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && (
        <div style={{ color: "#b5503f", fontSize: 12, marginTop: 8 }}>{error}</div>
      )}

      {mergeFlow.stage === "picking" && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15,17,21,0.72)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 200,
          }}
          onClick={() => setMergeFlow({ stage: "idle" })}
        >
          <div
            style={{ ...card, maxWidth: 360, width: "100%", padding: 24, margin: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <p style={{ fontSize: 14, margin: "0 0 16px", color: "#23201b" }}>
              Merge &quot;{mergeFlow.from}&quot; into which category?
            </p>
            <select
              style={{ ...input, marginBottom: 16 }}
              value={mergeFlow.into}
              onChange={(e) =>
                setMergeFlow({ ...mergeFlow, into: e.target.value })
              }
            >
              {categories
                .filter((c) => c !== mergeFlow.from)
                .map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
            </select>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                type="button"
                onClick={() => setMergeFlow({ stage: "idle" })}
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
              <button type="button" style={btn} onClick={proceedToConfirm}>
                Merge categories
              </button>
            </div>
          </div>
        </div>
      )}

      {mergeFlow.stage === "confirming" && (
        <ConfirmDialog
          message={`Merge "${mergeFlow.from}" into "${mergeFlow.into}"? ${mergeFlow.affectedCount} transactions will be updated. This can't be undone.`}
          confirmLabel="Merge"
          onCancel={() => setMergeFlow({ stage: "idle" })}
          onConfirm={submitMerge}
        />
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
