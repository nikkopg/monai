"use client";

import { useEffect, useState } from "react";

import { card, input, btn, label } from "../styles";

// ---------------------------------------------------------------------------
// Settings page — three independently-saveable cards: LLM Provider & Model,
// API Keys, Preferences. Loads current settings via GET /api/settings on
// mount, and PUTs partial per-card updates through the existing catch-all
// proxy (which injects MONAI_API_KEY server-side — the browser never adds an
// auth header). Phase 3 Plan 03 (UI-03/UI-04).
// ---------------------------------------------------------------------------

type SettingsOut = {
  llm_provider: string;
  llm_model: string;
  anthropic_api_key_masked: string | null;
  openai_api_key_masked: string | null;
  base_currency: string;
  price_data_source: string;
};

const DEFAULT_MODEL_BY_PROVIDER: Record<string, string> = {
  ollama: "gemma4:31b-cloud",
  claude: "claude-haiku-4-5-20251001",
  openai: "gpt-4o-mini",
};

const disabledBtn: React.CSSProperties = {
  ...btn,
  background: "#374151",
  cursor: "not-allowed",
};

type SaveState = { status: "idle" | "saving" | "success" | "error"; message?: string };

export default function SettingsPage() {
  const [loadError, setLoadError] = useState(false);

  // Card 1: LLM Provider & Model
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState(DEFAULT_MODEL_BY_PROVIDER.ollama);
  const [providerState, setProviderState] = useState<SaveState>({ status: "idle" });

  // Card 2: API Keys
  const [anthropicMasked, setAnthropicMasked] = useState<string | null>(null);
  const [openaiMasked, setOpenaiMasked] = useState<string | null>(null);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [keysState, setKeysState] = useState<SaveState>({ status: "idle" });

  // Card 3: Preferences
  const [baseCurrency, setBaseCurrency] = useState("IDR");
  const [priceDataSource, setPriceDataSource] = useState("coingecko");
  const [preferencesState, setPreferencesState] = useState<SaveState>({ status: "idle" });

  useEffect(() => {
    async function loadSettings() {
      try {
        const r = await fetch("/api/settings");
        if (!r.ok) {
          setLoadError(true);
          return;
        }
        const data: SettingsOut = await r.json();
        setProvider(data.llm_provider);
        setModel(data.llm_model);
        setAnthropicMasked(data.anthropic_api_key_masked);
        setOpenaiMasked(data.openai_api_key_masked);
        setBaseCurrency(data.base_currency);
        setPriceDataSource(data.price_data_source);
      } catch {
        setLoadError(true);
      }
    }
    loadSettings();
  }, []);

  function handleProviderChange(next: string) {
    setProvider(next);
    setModel(DEFAULT_MODEL_BY_PROVIDER[next] ?? "");
  }

  async function putSettings(
    body: Record<string, string>,
    setState: (s: SaveState) => void
  ) {
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
          // ignore body-parse failure, keep the status-based detail
        }
        setState({ status: "error", message: detail });
        return;
      }
      setState({ status: "success" });
    } catch (e) {
      setState({
        status: "error",
        message: e instanceof Error ? e.message : "network error",
      });
    }
  }

  async function saveProvider(e: React.FormEvent) {
    e.preventDefault();
    setProviderState({ status: "idle" });
    await putSettings(
      { llm_provider: provider, llm_model: model },
      setProviderState
    );
  }

  async function saveKeys(e: React.FormEvent) {
    e.preventDefault();
    setKeysState({ status: "idle" });
    const body: Record<string, string> = {};
    if (anthropicKey) body.anthropic_api_key = anthropicKey;
    if (openaiKey) body.openai_api_key = openaiKey;
    await putSettings(body, setKeysState);
    setAnthropicKey("");
    setOpenaiKey("");
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
      return <span style={{ color: "#4ade80", fontSize: 12 }}>Saved.</span>;
    }
    if (state.status === "error") {
      return (
        <span style={{ color: "#f87171", fontSize: 12 }}>
          Save failed: {state.message}. Your previous settings are unchanged — try again.
        </span>
      );
    }
    return null;
  }

  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "48px 24px" }}>
      <h1 style={{ fontSize: 28, fontWeight: 600, marginTop: 0, marginBottom: 16 }}>
        Settings
      </h1>

      {loadError && (
        <section style={card}>
          <p style={{ color: "#f87171", fontSize: 14, margin: 0 }}>
            Couldn&apos;t load settings — check the backend is running and reload the page.
          </p>
        </section>
      )}

      {/* Card 1: LLM Provider & Model */}
      <section style={card}>
        <label style={label}>LLM Provider &amp; Model</label>
        <form onSubmit={saveProvider}>
          <div style={{ marginBottom: 16 }}>
            <label style={label}>Provider</label>
            <select
              style={input}
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
            >
              <option value="ollama">ollama</option>
              <option value="claude">claude</option>
              <option value="openai">openai</option>
            </select>
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={label}>Model</label>
            <input
              style={input}
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              style={providerState.status === "saving" ? disabledBtn : btn}
              type="submit"
              disabled={providerState.status === "saving"}
            >
              {providerState.status === "saving" ? "Saving…" : "Save Provider"}
            </button>
            {statusMessage(providerState)}
          </div>
        </form>
      </section>

      {/* Card 2: API Keys */}
      <section style={card}>
        <label style={label}>API Keys</label>
        <form onSubmit={saveKeys}>
          <div style={{ marginBottom: 16 }}>
            <label style={label}>Anthropic API key</label>
            <input
              style={input}
              type="password"
              value={anthropicKey}
              placeholder={
                anthropicMasked ? anthropicMasked : "sk-ant-..."
              }
              onChange={(e) => setAnthropicKey(e.target.value)}
            />
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={label}>OpenAI API key</label>
            <input
              style={input}
              type="password"
              value={openaiKey}
              placeholder={openaiMasked ? openaiMasked : "sk-..."}
              onChange={(e) => setOpenaiKey(e.target.value)}
            />
          </div>
          <p style={{ ...label, marginBottom: 16 }}>
            Leave blank to keep the current key.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              style={keysState.status === "saving" ? disabledBtn : btn}
              type="submit"
              disabled={keysState.status === "saving"}
            >
              {keysState.status === "saving" ? "Saving…" : "Save Keys"}
            </button>
            {statusMessage(keysState)}
          </div>
        </form>
      </section>

      {/* Card 3: Preferences */}
      <section style={card}>
        <label style={label}>Preferences</label>
        <form onSubmit={savePreferences}>
          <div style={{ marginBottom: 16 }}>
            <label style={label}>Base currency</label>
            <input
              style={input}
              type="text"
              value={baseCurrency}
              onChange={(e) => setBaseCurrency(e.target.value)}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={label}>Price data source</label>
            <select
              style={input}
              value={priceDataSource}
              onChange={(e) => setPriceDataSource(e.target.value)}
            >
              <option value="coingecko">coingecko</option>
              <option value="yfinance">yfinance</option>
              <option value="manual">manual</option>
            </select>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              style={preferencesState.status === "saving" ? disabledBtn : btn}
              type="submit"
              disabled={preferencesState.status === "saving"}
            >
              {preferencesState.status === "saving" ? "Saving…" : "Save Preferences"}
            </button>
            {statusMessage(preferencesState)}
          </div>
        </form>
      </section>
    </main>
  );
}
