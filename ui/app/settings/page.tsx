"use client";

import { useEffect, useState } from "react";

import { tokens, card, input, btn } from "../styles";
import CategoryManager from "./CategoryManager";
import SkillsCard from "./SkillsCard";
import OllamaModelField from "./OllamaModelField";
import ExternalMcpCard from "./ExternalMcpCard";
import AccountManager, { type Account } from "../overview/AccountManager";
import CsvUpload from "../overview/CsvUpload";
import PlatformManager, { type Platform } from "../investments/PlatformManager";

// ---------------------------------------------------------------------------
// Settings page — v1.1 "paper" redesign. Same three independently-saveable
// cards (Model, Preferences; API Keys and the provider switch went with
// Claude/OpenAI in 261122-rmp), same GET/PUT
// /api/settings wiring (the catch-all proxy injects MONAI_API_KEY server-side).
// The live-refresh toggle from
// the mockup is intentionally omitted — there is no backend field for it and
// this milestone is presentation-only (a non-persisting toggle would be fake).
// ---------------------------------------------------------------------------

type SettingsOut = {
  llm_model: string;
  base_currency: string;
  price_data_source: string;
};

type SaveState = {
  status: "idle" | "saving" | "success" | "error";
  message?: string;
};

// h2: each card is a section of the page (F008); margin reset from the h2 default.
const cardTitle: React.CSSProperties = {
  fontSize: "var(--fs-h3, 15px)",
  fontWeight: 600,
  margin: "0 0 4px",
};
const cardSub: React.CSSProperties = {
  fontSize: "var(--fs-body, 13px)",
  color: tokens.color.muted,
  marginBottom: 16,
};
const fieldLabel: React.CSSProperties = {
  fontSize: "var(--fs-xs, 12px)",
  color: tokens.color.muted2,
  marginBottom: 7,
  display: "block",
};

export default function SettingsPage() {
  const [loadError, setLoadError] = useState(false);

  const [model, setModel] = useState("");
  const [modelState, setModelState] = useState<SaveState>({
    status: "idle",
  });



  const [baseCurrency, setBaseCurrency] = useState("IDR");
  const [priceDataSource, setPriceDataSource] = useState("coingecko");
  const [preferencesState, setPreferencesState] = useState<SaveState>({
    status: "idle",
  });

  // Accounts manager (moved here from the Overview page). AccountManager needs
  // each account's current_balance, which only GET /cashflow/summary returns
  // (the plain /accounts endpoint omits it); period is irrelevant to balances.
  const [accounts, setAccounts] = useState<Account[]>([]);

  async function loadAccounts() {
    try {
      const r = await fetch("/api/cashflow/summary?period=this_month");
      if (r.ok) setAccounts((await r.json()).accounts ?? []);
    } catch {
      // non-fatal — the Accounts card just renders empty if this fails
    }
  }

  // Platforms manager (moved here from the Investments page).
  const [platforms, setPlatforms] = useState<Platform[]>([]);

  async function loadPlatforms() {
    try {
      const r = await fetch("/api/platforms");
      if (r.ok) setPlatforms(await r.json());
    } catch {
      // non-fatal — the Platforms card just renders empty if this fails
    }
  }

  async function loadSettings() {
    try {
      const r = await fetch("/api/settings");
      if (!r.ok) {
        setLoadError(true);
        return;
      }
      const data: SettingsOut = await r.json();
      setModel(data.llm_model);
      setBaseCurrency(data.base_currency);
      setPriceDataSource(data.price_data_source);
    } catch {
      setLoadError(true);
    }
  }

  // The loaders catch their own errors, so Promise.all always resolves.
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    Promise.all([loadAccounts(), loadPlatforms(), loadSettings()]).then(() =>
      setLoaded(true)
    );
  }, []);

  // The cards above a hash target fill in after their fetches, so the
  // browser's own hash jump lands too early; scroll once the data is in.
  // CategoryManager's later growth above is absorbed by scroll anchoring.
  useEffect(() => {
    if (loaded && window.location.hash.length > 1) {
      document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
    }
  }, [loaded]);

  async function putSettings(
    body: Record<string, string>,
    setState: (s: SaveState) => void
  ): Promise<boolean> {
    setState({ status: "saving" });
    try {
      const r = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const errBody = await r.json();
          detail = errBody?.detail ?? detail;
        } catch {
          // keep the status-based detail
        }
        setState({ status: "error", message: detail });
        return false;
      }
      setState({ status: "success" });
      return true;
    } catch (e) {
      setState({
        status: "error",
        message: e instanceof Error ? e.message : "network error",
      });
      return false;
    }
  }

  async function saveModel(e: React.FormEvent) {
    e.preventDefault();
    setModelState({ status: "idle" });
    await putSettings({ llm_model: model }, setModelState);
  }

  async function savePreferences(e: React.FormEvent) {
    e.preventDefault();
    setPreferencesState({ status: "idle" });
    await putSettings(
      { base_currency: baseCurrency, price_data_source: priceDataSource },
      setPreferencesState
    );
  }

  function statusMessage(state: SaveState) {
    if (state.status === "success") {
      return (
        <span style={{ color: tokens.color.green, fontSize: "var(--fs-xs, 12px)" }}>Saved.</span>
      );
    }
    if (state.status === "error") {
      return (
        <span style={{ color: tokens.color.terracotta, fontSize: "var(--fs-xs, 12px)" }}>
          Save failed: {state.message}. Your previous settings are unchanged. Try
          again.
        </span>
      );
    }
    return null;
  }

  const saveBtn = (state: SaveState): React.CSSProperties =>
    state.status === "saving" ? { ...btn, opacity: 0.6, cursor: "not-allowed" } : btn;

  return (
    <div className="tab-in" style={{ maxWidth: 720, margin: "0 auto", padding: "40px 44px 60px" }}>
      <div style={{ marginBottom: 28 }}>
        <h1
          style={{
            fontFamily: tokens.font.serif,
            fontWeight: 400,
            fontSize: "var(--fs-title, 40px)",
            margin: 0,
            letterSpacing: "-.5px",
          }}
        >
          Settings
        </h1>
      </div>

      {loadError && (
        <div style={{ ...card, color: tokens.color.terracotta }}>
          Couldn&apos;t load settings. Check the backend is running and reload
          the page.
        </div>
      )}

      {/* Card 1: Model (Ollama is the only provider since 261122-rmp) */}
      <div style={card}>
        <h2 style={cardTitle}>Model</h2>
        <div style={cardSub}>The Ollama model that answers your questions.</div>
        <form onSubmit={saveModel}>
          <label htmlFor="set-model" style={fieldLabel}>Model</label>
          <OllamaModelField value={model} onChange={setModel} />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: 18,
            }}
          >
            <button
              className="tap44"
              style={saveBtn(modelState)}
              type="submit"
              disabled={modelState.status === "saving"}
            >
              {modelState.status === "saving" ? "Saving…" : "Save Model"}
            </button>
            {statusMessage(modelState)}
          </div>
        </form>
      </div>

      {/* Card 3: Categories — expandable tree manager (D-16) */}
      <div style={card}>
        <h2 style={cardTitle}>Categories</h2>
        <div style={cardSub}>Manage the category hierarchy used across cashflow and chat.</div>
        <CategoryManager onChanged={() => {}} />
      </div>

      {/* Card: Accounts — balances, rename/delete, adjust balance (moved from
          the Overview page). AccountManager renders its own card section. */}
      <AccountManager accounts={accounts} onChanged={loadAccounts} />

      {/* Card: Import CSV (moved from the Overview page); an import changes
          balances, so the accounts above reload. */}
      <CsvUpload onImported={loadAccounts} />

      {/* Card: Platforms (moved from the Investments page); add/edit/delete
          reload the list. PlatformManager renders its own card section. */}
      <PlatformManager platforms={platforms} onChanged={loadPlatforms} />

      {/* Card: Skills (Phase 40) */}
      <SkillsCard />

      {/* Card: External MCP servers (Phase 41) */}
      <ExternalMcpCard />

      {/* Card 4: Preferences */}
      <div style={{ ...card, marginBottom: 0 }}>
        <h2 style={cardTitle}>Preferences</h2>
        <form onSubmit={savePreferences}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
              gap: 16,
              marginTop: 8,
              marginBottom: 18,
            }}
          >
            <div>
              <label htmlFor="set-base-currency" style={fieldLabel}>Base currency</label>
              <input
                id="set-base-currency"
                style={input}
                type="text"
                value={baseCurrency}
                onChange={(e) => setBaseCurrency(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="set-price-source" style={fieldLabel}>Price data source</label>
              <select
                id="set-price-source"
                style={input}
                value={priceDataSource}
                onChange={(e) => setPriceDataSource(e.target.value)}
              >
                <option value="coingecko">coingecko</option>
                <option value="yfinance">yfinance</option>
                <option value="manual">manual</option>
              </select>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              className="tap44"
              style={saveBtn(preferencesState)}
              type="submit"
              disabled={preferencesState.status === "saving"}
            >
              {preferencesState.status === "saving"
                ? "Saving…"
                : "Save Preferences"}
            </button>
            {statusMessage(preferencesState)}
          </div>
        </form>
      </div>
    </div>
  );
}
