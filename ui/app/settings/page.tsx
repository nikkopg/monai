"use client";

import { useEffect, useState } from "react";

import { tokens, card, input, btn } from "../styles";

// ---------------------------------------------------------------------------
// Settings page — v1.1 "paper" redesign. Same three independently-saveable
// cards (LLM Provider & Model, API Keys, Preferences), same GET/PUT
// /api/settings wiring (the catch-all proxy injects MONAI_API_KEY server-side).
// Provider is now a segmented control (UIR-07); the live-refresh toggle from
// the mockup is intentionally omitted — there is no backend field for it and
// this milestone is presentation-only (a non-persisting toggle would be fake).
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

const PROVIDERS = ["ollama", "claude", "openai"] as const;

type SaveState = {
  status: "idle" | "saving" | "success" | "error";
  message?: string;
};

const cardTitle: React.CSSProperties = {
  fontSize: 15,
  fontWeight: 600,
  marginBottom: 4,
};
const cardSub: React.CSSProperties = {
  fontSize: 13,
  color: tokens.color.muted,
  marginBottom: 16,
};
const fieldLabel: React.CSSProperties = {
  fontSize: 12,
  color: tokens.color.muted2,
  marginBottom: 7,
  display: "block",
};

export default function SettingsPage() {
  const [loadError, setLoadError] = useState(false);

  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState(DEFAULT_MODEL_BY_PROVIDER.ollama);
  const [providerState, setProviderState] = useState<SaveState>({
    status: "idle",
  });

  const [anthropicMasked, setAnthropicMasked] = useState<string | null>(null);
  const [openaiMasked, setOpenaiMasked] = useState<string | null>(null);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [keysState, setKeysState] = useState<SaveState>({ status: "idle" });

  const [baseCurrency, setBaseCurrency] = useState("IDR");
  const [priceDataSource, setPriceDataSource] = useState("coingecko");
  const [preferencesState, setPreferencesState] = useState<SaveState>({
    status: "idle",
  });

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
    const ok = await putSettings(body, setKeysState);
    if (ok) {
      setAnthropicKey("");
      setOpenaiKey("");
    }
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
        <span style={{ color: tokens.color.green, fontSize: 12 }}>Saved.</span>
      );
    }
    if (state.status === "error") {
      return (
        <span style={{ color: tokens.color.terracotta, fontSize: 12 }}>
          Save failed: {state.message}. Your previous settings are unchanged — try
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
        <div
          style={{
            fontSize: 12,
            letterSpacing: ".12em",
            textTransform: "uppercase",
            color: tokens.color.muted2,
            marginBottom: 6,
          }}
        >
          Configuration
        </div>
        <h1
          style={{
            fontFamily: tokens.font.serif,
            fontWeight: 400,
            fontSize: 40,
            margin: 0,
            letterSpacing: "-.5px",
          }}
        >
          Settings
        </h1>
      </div>

      {loadError && (
        <div style={{ ...card, color: tokens.color.terracotta }}>
          Couldn&apos;t load settings — check the backend is running and reload
          the page.
        </div>
      )}

      {/* Card 1: LLM Provider & Model */}
      <div style={card}>
        <div style={cardTitle}>LLM Provider &amp; Model</div>
        <div style={cardSub}>Which engine answers your questions.</div>
        <form onSubmit={saveProvider}>
          <label style={fieldLabel}>Provider</label>
          <div
            style={{
              display: "inline-flex",
              background: tokens.color.sidebar,
              border: `1px solid ${tokens.color.border2}`,
              borderRadius: 12,
              padding: 4,
              marginBottom: 18,
            }}
          >
            {PROVIDERS.map((p) => {
              const active = provider === p;
              return (
                <button
                  key={p}
                  type="button"
                  onClick={() => handleProviderChange(p)}
                  style={{
                    border: "none",
                    borderRadius: 9,
                    padding: "8px 18px",
                    fontSize: 14,
                    fontWeight: active ? 600 : 500,
                    cursor: "pointer",
                    color: active ? tokens.color.ink : tokens.color.muted,
                    background: active ? "#fff" : "transparent",
                    boxShadow: active
                      ? "0 1px 2px rgba(40,34,24,.12)"
                      : "none",
                    transition: "all .2s ease",
                  }}
                >
                  {p}
                </button>
              );
            })}
          </div>
          <label style={fieldLabel}>Model</label>
          <input
            style={input}
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: 18,
            }}
          >
            <button
              style={saveBtn(providerState)}
              type="submit"
              disabled={providerState.status === "saving"}
            >
              {providerState.status === "saving" ? "Saving…" : "Save Provider"}
            </button>
            {statusMessage(providerState)}
          </div>
        </form>
      </div>

      {/* Card 2: API Keys */}
      <div style={card}>
        <div style={cardTitle}>API Keys</div>
        <div style={cardSub}>
          Stored encrypted. Leave blank to keep the current key.
        </div>
        <form onSubmit={saveKeys}>
          <label style={fieldLabel}>Anthropic API key</label>
          <input
            style={{ ...input, marginBottom: 14 }}
            type="password"
            value={anthropicKey}
            placeholder={anthropicMasked ? anthropicMasked : "sk-ant-..."}
            onChange={(e) => setAnthropicKey(e.target.value)}
          />
          <label style={fieldLabel}>OpenAI API key</label>
          <input
            style={input}
            type="password"
            value={openaiKey}
            placeholder={openaiMasked ? openaiMasked : "sk-..."}
            onChange={(e) => setOpenaiKey(e.target.value)}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: 18,
            }}
          >
            <button
              style={saveBtn(keysState)}
              type="submit"
              disabled={keysState.status === "saving"}
            >
              {keysState.status === "saving" ? "Saving…" : "Save Keys"}
            </button>
            {statusMessage(keysState)}
          </div>
        </form>
      </div>

      {/* Card 3: Preferences */}
      <div style={{ ...card, marginBottom: 0 }}>
        <div style={cardTitle}>Preferences</div>
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
              <label style={fieldLabel}>Base currency</label>
              <input
                style={input}
                type="text"
                value={baseCurrency}
                onChange={(e) => setBaseCurrency(e.target.value)}
              />
            </div>
            <div>
              <label style={fieldLabel}>Price data source</label>
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
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
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
