"use client";
// 261122-omp: the Model field for Ollama — a select of the models Ollama has
// installed, fetched from GET /api/settings/ollama-models. If Ollama can't be
// reached, or lists nothing, the plain text field comes back so a name can
// still be typed.
import { useEffect, useState } from "react";

import { tokens, input } from "../styles";

export type OllamaModel = { name: string; size: number; parameter_size: string | null };

function optionLabel(m: OllamaModel): string {
  const parts = [m.name];
  if (m.parameter_size) parts.push(m.parameter_size);
  if (m.size > 0) parts.push(`${(m.size / 1e9).toFixed(1)} GB`);
  return parts.join(" · ");
}

export default function OllamaModelField({
  value,
  onChange,
  onModels,
}: {
  value: string;
  onChange: (name: string) => void;
  onModels?: (models: OllamaModel[]) => void;
}) {
  const [models, setModels] = useState<OllamaModel[] | null>(null); // null: loading
  const [failed, setFailed] = useState(false);

  async function load() {
    setModels(null);
    setFailed(false);
    try {
      const r = await fetch("/api/settings/ollama-models");
      if (!r.ok) throw new Error(String(r.status));
      const list: OllamaModel[] = await r.json();
      setModels(list);
      onModels?.(list);
    } catch {
      setModels([]);
      setFailed(true);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const note = { fontSize: "var(--fs-xs, 12px)", color: tokens.color.muted3, marginTop: 6 } as const;
  const refresh = (
    <button
      type="button"
      className="tap44"
      onClick={load}
      style={{
        background: "none",
        border: `1px solid ${tokens.color.border2}`,
        borderRadius: tokens.radius.sm,
        padding: "0 14px",
        fontSize: 13,
        color: tokens.color.ink,
        cursor: "pointer",
      }}
    >
      Refresh
    </button>
  );

  if (models !== null && models.length === 0) {
    return (
      <>
        <div style={{ display: "flex", gap: 8 }}>
          <input id="set-model" style={input} type="text" value={value} onChange={(e) => onChange(e.target.value)} />
          {refresh}
        </div>
        <div style={note} data-testid="model-note">
          {failed
            ? "Couldn't reach Ollama, so type the model name."
            : "Ollama has no models installed. Pull one with ollama pull, then refresh."}
        </div>
      </>
    );
  }

  const installed = models?.some((m) => m.name === value) ?? true;
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <select
        id="set-model"
        style={input}
        value={value}
        disabled={models === null}
        onChange={(e) => onChange(e.target.value)}
      >
        {models === null && <option value={value}>Loading models…</option>}
        {models !== null && !installed && value && <option value={value}>{value} (not installed)</option>}
        {models?.map((m) => (
          <option key={m.name} value={m.name}>
            {optionLabel(m)}
          </option>
        ))}
      </select>
      {refresh}
    </div>
  );
}
