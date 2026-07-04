import { card } from "../styles";

// ---------------------------------------------------------------------------
// Settings page — minimal Phase 3 placeholder. Server component (no client
// state yet). Exists so the Nav has four real routes; plan 03-03 replaces
// this file with the full three-card settings form (LLM Provider & Model,
// API Keys, Preferences).
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 0, marginBottom: 16 }}>
        Settings
      </h1>
      <section style={card}>
        <p style={{ color: "#e6e8eb", fontSize: 14, margin: 0 }}>
          Settings controls load here.
        </p>
      </section>
    </main>
  );
}
