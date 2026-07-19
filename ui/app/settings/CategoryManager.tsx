"use client";

import { useEffect, useState } from "react";

import { tokens, card, input, btn, btnGhost, categoryPalette } from "../styles";
import ConfirmDialog from "../cashflow/ConfirmDialog";

// ---------------------------------------------------------------------------
// CategoryManager (Settings) — recursive tree manager for the category
// hierarchy (D-16). Replaces the old flat rename/merge table that used to
// live under the Cashflow page.
// Plain useState recursion, no tree library — ~100 rows total is trivial
// (11-UI-SPEC.md's "Don't Hand-Roll" guidance). Implements UI-SPEC Component 1
// verbatim: expand/collapse (collapsed by default), inline add/edit, the
// block-or-reassign delete guard (CAT-02/Pitfall 3), the closed 13-swatch
// palette with parent-color inheritance (D-14), and system-row locks
// (Transfer/Uncategorized, D-04).
//
// Merge (D-11, explicitly retained) still targets the legacy
// POST /api/categories/merge — it combines two DIFFERENT named categories'
// transaction history, which the newer per-node PUT/DELETE cannot express.
// Per-node name/color/icon edits go through PUT /categories/{id} (built in
// plan 11-03 specifically as the one-shot edit endpoint for this UI) rather
// than the legacy single-field POST /categories/rename, since PUT already
// covers rename as a subset and avoids a second network round-trip when both
// name and color/icon change together.
// ---------------------------------------------------------------------------

type CategoryNode = {
  id: number;
  name: string;
  parent_id: number | null;
  kind: string;
  color: string | null;
  effective_color: string | null;
  icon: string | null;
  is_system: boolean;
  tx_count: number;
  children: CategoryNode[];
};

type Props = {
  onChanged: () => void;
};

type EditFlow =
  | { mode: "idle" }
  | {
      mode: "add";
      parentId: number | null;
      name: string;
      color: string | null;
      icon: string;
      kind: string;
    }
  | {
      mode: "edit";
      node: CategoryNode;
      name: string;
      color: string | null;
      icon: string;
    };

type DeleteFlow =
  | { stage: "idle" }
  | { stage: "confirm"; node: CategoryNode }
  | { stage: "reassign"; node: CategoryNode; affectedCount: number; targetId: string };

type MergeFlow =
  | { stage: "idle" }
  | { stage: "picking"; from: CategoryNode; into: string }
  | { stage: "confirming"; from: CategoryNode; into: string; affectedCount: number };

function flattenAll(nodes: CategoryNode[]): CategoryNode[] {
  return nodes.flatMap((n) => [n, ...flattenAll(n.children)]);
}

function descendantIds(node: CategoryNode): Set<number> {
  const ids = new Set<number>([node.id]);
  for (const child of node.children) {
    descendantIds(child).forEach((id) => ids.add(id));
  }
  return ids;
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace("#", "");
  const n = parseInt(clean, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
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

const badgeStyle: React.CSSProperties = {
  fontSize: 12,
  color: tokens.color.muted,
  background: tokens.color.border,
  borderRadius: tokens.radius.pill,
  padding: "2px 8px",
  marginLeft: 8,
};

const actionStyle: React.CSSProperties = {
  color: tokens.color.muted,
  cursor: "pointer",
  fontSize: 12,
  marginLeft: 12,
};

const deleteActionStyle: React.CSSProperties = { ...actionStyle, color: tokens.color.terracotta };
const lockedActionStyle: React.CSSProperties = { ...actionStyle, color: tokens.color.border2, cursor: "not-allowed" };

export default function CategoryManager({ onChanged }: Props) {
  const [tree, setTree] = useState<CategoryNode[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [editFlow, setEditFlow] = useState<EditFlow>({ mode: "idle" });
  const [deleteFlow, setDeleteFlow] = useState<DeleteFlow>({ stage: "idle" });
  const [mergeFlow, setMergeFlow] = useState<MergeFlow>({ stage: "idle" });
  const [error, setError] = useState<string | null>(null);

  async function loadCategories() {
    try {
      const r = await fetch("/api/categories");
      if (!r.ok) return;
      const data: CategoryNode[] = await r.json();
      setTree(data);
    } catch {
      // load failure — leave tree empty; page-level error banners already
      // cover the "backend down" case elsewhere on this page
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    loadCategories();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const flat = flattenAll(tree);

  function toggle(id: number) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function startAdd(parentId: number | null) {
    setEditFlow({ mode: "add", parentId, name: "", color: null, icon: "", kind: "expense" });
    if (parentId !== null) setExpandedIds((prev) => new Set(prev).add(parentId));
  }

  function startEdit(node: CategoryNode) {
    setEditFlow({ mode: "edit", node, name: node.name, color: node.color, icon: node.icon ?? "" });
  }

  function cancelEdit() {
    setEditFlow({ mode: "idle" });
  }

  async function saveAdd() {
    if (editFlow.mode !== "add") return;
    const { parentId, name, color, icon, kind } = editFlow;
    setError(null);
    try {
      const body: Record<string, unknown> = { name, parent_id: parentId, icon: icon || null };
      if (parentId === null) {
        body.kind = kind;
        body.color = color;
      } else if (color) {
        body.color = color;
      }
      const r = await fetch("/api/categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        setEditFlow({ mode: "idle" });
        await loadCategories();
        onChanged();
      } else {
        setError(`Couldn't add category: ${await extractDetail(r)}. Nothing was changed.`);
      }
    } catch (e) {
      setError(`Couldn't add category: ${e instanceof Error ? e.message : "Network error"}. Nothing was changed.`);
    }
  }

  async function saveEdit() {
    if (editFlow.mode !== "edit") return;
    const { node, name, color, icon } = editFlow;
    setError(null);
    try {
      const body: Record<string, unknown> = { color, icon: icon || null };
      if (!node.is_system) body.name = name;
      const r = await fetch(`/api/categories/${node.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        setEditFlow({ mode: "idle" });
        await loadCategories();
        onChanged();
      } else {
        setError(`Couldn't edit category: ${await extractDetail(r)}. Nothing was changed.`);
      }
    } catch (e) {
      setError(`Couldn't edit category: ${e instanceof Error ? e.message : "Network error"}. Nothing was changed.`);
    }
  }

  async function attemptDelete(node: CategoryNode) {
    setError(null);
    try {
      const r = await fetch(`/api/categories/${node.id}`, { method: "DELETE" });
      if (r.ok) {
        setDeleteFlow({ stage: "idle" });
        await loadCategories();
        onChanged();
        return;
      }
      if (r.status === 422) {
        const errBody = await r.json().catch(() => ({}));
        const detail = errBody?.detail ?? {};
        const affectedCount: number = typeof detail === "object" ? detail?.affected_count ?? 0 : 0;
        const childCount: number = typeof detail === "object" ? detail?.child_count ?? 0 : 0;
        if (childCount > 0) {
          // Backend unconditionally blocks delete when subcategories exist —
          // reassign_to only ever moves transactions, never subcategories
          // (Pitfall 3) — so no reassign CTA is offered here, only the
          // corrective instruction.
          setError(
            `Couldn't delete category: ${affectedCount} transactions and ${childCount} subcategories use this category — remove or re-parent the subcategories first. Nothing was changed.`
          );
          setDeleteFlow({ stage: "idle" });
          return;
        }
        if (affectedCount > 0) {
          const excluded = descendantIds(node);
          const target = flat.find((c) => !excluded.has(c.id));
          setDeleteFlow({
            stage: "reassign",
            node,
            affectedCount,
            targetId: target ? String(target.id) : "",
          });
          return;
        }
        const message = typeof detail === "string" ? detail : detail?.message ?? "unknown error";
        setError(`Couldn't delete category: ${message}. Nothing was changed.`);
        setDeleteFlow({ stage: "idle" });
        return;
      }
      setError(`Couldn't delete category: ${await extractDetail(r)}. Nothing was changed.`);
      setDeleteFlow({ stage: "idle" });
    } catch (e) {
      setError(`Couldn't delete category: ${e instanceof Error ? e.message : "Network error"}. Nothing was changed.`);
      setDeleteFlow({ stage: "idle" });
    }
  }

  async function confirmReassignDelete() {
    if (deleteFlow.stage !== "reassign") return;
    const { node, targetId } = deleteFlow;
    setError(null);
    try {
      const r = await fetch(`/api/categories/${node.id}?reassign_to=${targetId}`, { method: "DELETE" });
      if (r.ok) {
        setDeleteFlow({ stage: "idle" });
        await loadCategories();
        onChanged();
      } else {
        setError(`Couldn't delete category: ${await extractDetail(r)}. Nothing was changed.`);
        setDeleteFlow({ stage: "idle" });
      }
    } catch (e) {
      setError(`Couldn't delete category: ${e instanceof Error ? e.message : "Network error"}. Nothing was changed.`);
      setDeleteFlow({ stage: "idle" });
    }
  }

  function openMergePicker(from: CategoryNode) {
    const others = flat.filter((c) => c.id !== from.id);
    setMergeFlow({ stage: "picking", from, into: others[0]?.name ?? "" });
  }

  function proceedToMergeConfirm() {
    if (mergeFlow.stage !== "picking") return;
    const { from, into } = mergeFlow;
    setMergeFlow({ stage: "confirming", from, into, affectedCount: from.tx_count });
  }

  async function submitMerge() {
    if (mergeFlow.stage !== "confirming") return;
    const { from, into } = mergeFlow;
    setError(null);
    try {
      const r = await fetch("/api/categories/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_name: from.name, into_name: into }),
      });
      if (r.ok) {
        setMergeFlow({ stage: "idle" });
        await loadCategories();
        onChanged();
      } else {
        setError(`Couldn't merge category: ${await extractDetail(r)}. Nothing was changed.`);
        setMergeFlow({ stage: "idle" });
      }
    } catch (e) {
      setError(`Couldn't merge category: ${e instanceof Error ? e.message : "Network error"}. Nothing was changed.`);
      setMergeFlow({ stage: "idle" });
    }
  }

  function renderChip(node: CategoryNode) {
    const hex = node.effective_color ?? tokens.color.muted2;
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 22,
          height: 22,
          borderRadius: tokens.radius.pill,
          background: hexToRgba(hex, 0.16),
          fontSize: 13,
          flexShrink: 0,
        }}
      >
        {node.icon || "🗂"}
      </span>
    );
  }

  function renderSwatchPicker(
    selected: string | null,
    allowInherit: boolean,
    onPick: (hex: string | null) => void
  ) {
    return (
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
        {allowInherit && (
          <button
            type="button"
            title="Inherit parent color"
            onClick={() => onPick(null)}
            style={{
              width: 18,
              height: 18,
              borderRadius: tokens.radius.pill,
              border: selected === null ? `2px solid ${tokens.color.green}` : `1px solid ${tokens.color.border2}`,
              background: tokens.color.sidebar,
              cursor: "pointer",
              padding: 0,
            }}
          />
        )}
        {categoryPalette.map((sw) => (
          <button
            key={sw.name}
            type="button"
            title={sw.name}
            onClick={() => onPick(sw.hex)}
            style={{
              width: 18,
              height: 18,
              borderRadius: tokens.radius.pill,
              border: selected === sw.hex ? `2px solid ${tokens.color.green}` : `1px solid ${tokens.color.border2}`,
              background: sw.hex,
              cursor: "pointer",
              padding: 0,
            }}
          />
        ))}
      </div>
    );
  }

  function renderAddRow(depth: number) {
    if (editFlow.mode !== "add") return null;
    const { name, color, icon, kind, parentId } = editFlow;
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          minHeight: 36,
          paddingLeft: depth * 20,
          borderTop: `1px solid ${tokens.color.border}`,
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <input
          style={{ ...input, width: 160 }}
          value={name}
          placeholder="Category name"
          onChange={(e) => setEditFlow({ ...editFlow, name: e.target.value })}
        />
        {parentId === null && (
          <select
            style={{ ...input, width: 100 }}
            value={kind}
            onChange={(e) => setEditFlow({ ...editFlow, kind: e.target.value })}
          >
            <option value="expense">expense</option>
            <option value="income">income</option>
          </select>
        )}
        {renderSwatchPicker(color, parentId !== null, (hex) => setEditFlow({ ...editFlow, color: hex }))}
        <input
          style={{ ...input, width: 60 }}
          value={icon}
          placeholder="emoji"
          onChange={(e) => setEditFlow({ ...editFlow, icon: e.target.value })}
        />
        <button type="button" style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={saveAdd}>
          Save
        </button>
        <button type="button" style={{ ...btnGhost, padding: "4px 10px", fontSize: 12 }} onClick={cancelEdit}>
          Cancel
        </button>
      </div>
    );
  }

  function renderRow(node: CategoryNode, depth: number) {
    const isExpandable = depth === 0 || node.children.length > 0;
    const isExpanded = expandedIds.has(node.id);
    const isHovered = hoveredId === node.id;
    const activeEdit = editFlow.mode === "edit" && editFlow.node.id === node.id ? editFlow : null;
    const isAddingUnder = editFlow.mode === "add" && editFlow.parentId === node.id;

    return (
      <div key={node.id}>
        <div
          onMouseEnter={() => setHoveredId(node.id)}
          onMouseLeave={() => setHoveredId((h) => (h === node.id ? null : h))}
          style={{
            display: "flex",
            alignItems: "center",
            minHeight: 36,
            paddingLeft: depth * 20,
            borderTop: `1px solid ${tokens.color.border}`,
            gap: tokens.space.xs,
          }}
        >
          <span
            role={isExpandable ? "button" : undefined}
            onClick={isExpandable ? () => toggle(node.id) : undefined}
            style={{
              width: 14,
              display: "inline-block",
              textAlign: "center",
              cursor: isExpandable ? "pointer" : "default",
              color: tokens.color.muted2,
              fontSize: 10,
              transform: isExpanded ? "rotate(90deg)" : "none",
              transition: "transform .15s ease",
            }}
          >
            {isExpandable ? "▶" : ""}
          </span>

          {renderChip(node)}

          {activeEdit ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", flex: 1 }}>
              {activeEdit.node.is_system ? (
                <span style={{ fontSize: 13, marginLeft: 4 }}>{activeEdit.node.name}</span>
              ) : (
                <input
                  style={{ ...input, width: 180 }}
                  value={activeEdit.name}
                  onChange={(e) => setEditFlow({ ...activeEdit, name: e.target.value })}
                />
              )}
              {renderSwatchPicker(activeEdit.color, true, (hex) => setEditFlow({ ...activeEdit, color: hex }))}
              <input
                style={{ ...input, width: 60 }}
                value={activeEdit.icon}
                placeholder="emoji"
                onChange={(e) => setEditFlow({ ...activeEdit, icon: e.target.value })}
              />
              <button type="button" style={{ ...btn, padding: "4px 10px", fontSize: 12 }} onClick={saveEdit}>
                Save
              </button>
              <button type="button" style={{ ...btnGhost, padding: "4px 10px", fontSize: 12 }} onClick={cancelEdit}>
                Cancel
              </button>
            </div>
          ) : (
            <>
              <span style={{ fontSize: 13, fontWeight: 400, marginLeft: 4 }}>{node.name}</span>
              <span style={badgeStyle}>{node.tx_count}</span>
              {node.is_system && (
                <span style={{ fontSize: 11, color: tokens.color.muted2, marginLeft: 8 }}>
                  System category — can&apos;t be deleted.
                </span>
              )}
              {isHovered && (
                <div style={{ marginLeft: "auto", whiteSpace: "nowrap", paddingRight: 8 }}>
                  {depth < 2 && (
                    <span role="button" onClick={() => startAdd(node.id)} style={actionStyle}>
                      Add subcategory
                    </span>
                  )}
                  <span role="button" onClick={() => startEdit(node)} style={actionStyle}>
                    Edit
                  </span>
                  <span role="button" onClick={() => openMergePicker(node)} style={actionStyle}>
                    Merge into…
                  </span>
                  {node.is_system ? (
                    <span style={lockedActionStyle} title="System category — can't be deleted.">
                      Delete
                    </span>
                  ) : (
                    <span
                      role="button"
                      onClick={() => setDeleteFlow({ stage: "confirm", node })}
                      style={deleteActionStyle}
                    >
                      Delete
                    </span>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {isExpanded && node.children.map((child) => renderRow(child, depth + 1))}
        {isAddingUnder && renderAddRow(depth + 1)}
      </div>
    );
  }

  return (
    <>
      {loaded && tree.length === 0 ? (
        <div>
          <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>No categories yet.</div>
          <div style={{ color: tokens.color.muted, fontSize: 14 }}>
            Categories are created automatically during setup, or add your first one below.
          </div>
        </div>
      ) : (
        <div>{tree.map((node) => renderRow(node, 0))}</div>
      )}

      {editFlow.mode === "add" && editFlow.parentId === null ? (
        renderAddRow(0)
      ) : (
        <div style={{ marginTop: 12 }}>
          <button type="button" style={btn} onClick={() => startAdd(null)}>
            Add category
          </button>
        </div>
      )}

      {error && <div style={{ color: tokens.color.terracotta, fontSize: 12, marginTop: 8 }}>{error}</div>}

      {deleteFlow.stage === "confirm" && (
        <ConfirmDialog
          message="Delete this category? This can't be undone."
          confirmLabel="Delete"
          onCancel={() => setDeleteFlow({ stage: "idle" })}
          onConfirm={() => attemptDelete(deleteFlow.node)}
        />
      )}

      {deleteFlow.stage === "reassign" && (
        <ConfirmDialog
          message={`${deleteFlow.affectedCount} transactions use this category — choose a destination category to reassign them, or cancel.`}
          confirmLabel="Reassign & delete"
          onCancel={() => setDeleteFlow({ stage: "idle" })}
          onConfirm={confirmReassignDelete}
        >
          <select
            style={input}
            value={deleteFlow.targetId}
            onChange={(e) => setDeleteFlow({ ...deleteFlow, targetId: e.target.value })}
          >
            {flat
              .filter((c) => !descendantIds(deleteFlow.node).has(c.id))
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </ConfirmDialog>
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
            <p style={{ fontSize: 14, margin: "0 0 16px", color: tokens.color.text }}>
              Merge &quot;{mergeFlow.from.name}&quot; into which category?
            </p>
            <select
              style={{ ...input, marginBottom: 16 }}
              value={mergeFlow.into}
              onChange={(e) => setMergeFlow({ ...mergeFlow, into: e.target.value })}
            >
              {flat
                .filter((c) => c.id !== mergeFlow.from.id)
                .map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
            </select>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <button
                type="button"
                onClick={() => setMergeFlow({ stage: "idle" })}
                style={{
                  background: "transparent",
                  color: tokens.color.muted,
                  border: "none",
                  padding: "8px 16px",
                  fontSize: 14,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button type="button" style={btn} onClick={proceedToMergeConfirm}>
                Merge categories
              </button>
            </div>
          </div>
        </div>
      )}

      {mergeFlow.stage === "confirming" && (
        <ConfirmDialog
          message={`Merge "${mergeFlow.from.name}" into "${mergeFlow.into}"? ${mergeFlow.affectedCount} transactions will be updated. This can't be undone.`}
          confirmLabel="Merge"
          onCancel={() => setMergeFlow({ stage: "idle" })}
          onConfirm={submitMerge}
        />
      )}
    </>
  );
}
