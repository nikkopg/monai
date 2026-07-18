"use client";

import { useState } from "react";

import { card, btn, label } from "../styles";

// ---------------------------------------------------------------------------
// CsvUpload — thin wrapper over the existing POST /import (CASH-08). No
// backend change: the proxy forwards the multipart body untouched. Renders
// "Parsed {n} · Inserted {n} · Skipped {n}", with the Skipped segment in
// Destructive color when skipped > 0.
// ---------------------------------------------------------------------------

type ImportResult = {
  parsed: number;
  inserted: number;
  skipped: number;
  currency: string;
};

type Props = {
  onImported: () => void;
};

export default function CsvUpload({ onImported }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const r = await fetch("/api/import", {
        method: "POST",
        body: formData,
      });
      if (r.ok) {
        const data: ImportResult = await r.json();
        setResult(data);
        onImported();
      } else {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setError(`Couldn't import the file: ${detail}. No rows were inserted.`);
      }
    } catch (e) {
      setError(
        `Couldn't import the file: ${
          e instanceof Error ? e.message : "Network error"
        }. No rows were inserted.`
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <section style={card}>
      <label style={label}>Import CSV</label>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
        <input
          type="file"
          accept=".csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          style={btn}
          disabled={!file || uploading}
          onClick={handleUpload}
        >
          {uploading ? "Uploading…" : "Upload CSV"}
        </button>
      </div>
      {!file && !result && (
        <div style={{ ...label, marginTop: 8, marginBottom: 0 }}>
          Choose a Wallet CSV export to upload.
        </div>
      )}
      {result && (
        <div style={{ fontSize: 14, marginTop: 12 }}>
          Parsed {result.parsed} · Inserted {result.inserted} ·{" "}
          <span style={{ color: result.skipped > 0 ? "#b5503f" : "#8b8474" }}>
            Skipped {result.skipped}
          </span>
        </div>
      )}
      {error && (
        <div style={{ color: "#b5503f", fontSize: 12, marginTop: 8 }}>{error}</div>
      )}
    </section>
  );
}
