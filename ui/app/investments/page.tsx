"use client";

import { useCallback, useEffect, useState } from "react";

import { card } from "../styles";
import PlatformManager, { type Platform } from "./PlatformManager";

// ---------------------------------------------------------------------------
// Investments page — grown from the Phase 3 skeleton into a "use client"
// tracker (RESEARCH Pitfall 5). This slice (Plan 05-02) renders only the
// Platforms card hosting <PlatformManager>; the portfolio-total banner and
// per-platform holding cards arrive in Plans 03/04.
// ---------------------------------------------------------------------------

export default function InvestmentsPage() {
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await fetch("/api/platforms");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setPlatforms(await r.json());
    } catch {
      setError(
        "Couldn't load your portfolio — check the backend is running and reload the page."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 0, marginBottom: 32 }}>
        Investments
      </h1>

      {loading ? (
        <section style={card}>
          <p style={{ color: "#9aa0a6", fontSize: 14, margin: 0 }}>
            Loading your portfolio…
          </p>
        </section>
      ) : error ? (
        <section style={card}>
          <p style={{ color: "#f87171", fontSize: 14, margin: 0 }}>{error}</p>
        </section>
      ) : (
        <PlatformManager platforms={platforms} onChanged={load} />
      )}
    </main>
  );
}
