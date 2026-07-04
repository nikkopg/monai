import { card } from "../styles";

// ---------------------------------------------------------------------------
// Investments page — Phase 3 skeleton. Server component (no client state, no
// "use client" — RESEARCH.md Pitfall 5). Full holdings/live-price/P&L UI
// ships in Phase 5.
// ---------------------------------------------------------------------------

export default function InvestmentsPage() {
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
      <section style={card}>
        <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 0, marginBottom: 16 }}>
          Investments are coming in Phase 5
        </h1>
        <p style={{ color: "#e6e8eb", fontSize: 14, margin: 0 }}>
          Holdings, live prices, and profit/loss tracking will appear here
          once the investment subsystem ships. Check back after Phase 5.
        </p>
      </section>
    </main>
  );
}
