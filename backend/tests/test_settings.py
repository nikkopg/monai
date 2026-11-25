"""
Settings endpoint tests — GET/PUT /settings (UI-03, UI-04; Ollama-only since 261122-rmp).

Covers:
  - GET returns the model and preferences only (no provider, no API keys)
  - PUT requires MONAI_API_KEY auth (401 without it)
  - PUT updates the model and a subsequent GET reflects the change
  - an old client's llm_provider / API key fields are ignored
  - base_currency / price_data_source persist across a fresh GET
  - reset_engine() is invoked exactly once when the model changes, and
    NOT invoked when only preference fields change
  - GET /settings/ollama-models lists installed models (261122-omp)

All tests use the test Postgres via the shared `client`/`api_key` fixtures
(conftest.py) — no mocking of the DB, only of backend.query.reset_engine
where the call-count invariant is asserted.
"""

import pytest


# ---------------------------------------------------------------------------
# GET /settings — defaults, masked-only shape
# ---------------------------------------------------------------------------


def test_get_settings_returns_defaults(client, authed):
    """GET /settings returns the Ollama model and the preferences, nothing else
    (Ollama is the only provider since 261122-rmp)."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"llm_model", "base_currency", "price_data_source"}
    assert body["base_currency"] == "IDR"


# ---------------------------------------------------------------------------
# PUT /settings — auth gate
# ---------------------------------------------------------------------------


def test_put_settings_requires_key(client, monkeypatch):
    """PUT /settings with no MONAI_API_KEY header returns 401.

    require_api_key fails closed with 503 when no key is configured
    server-side at all (backend/auth.py); on an isolated test run with no
    MONAI_API_KEY env var this test's own process has none, so configure
    one (without sending it) to exercise the missing-header 401 path
    specifically, mirroring conftest.py's `api_key` fixture."""
    import backend.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_CONFIGURED_KEY", "zz-test-settings-key")
    resp = client.put("/settings", json={"base_currency": "IDR"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /settings — model update round-trip
# ---------------------------------------------------------------------------


def test_put_updates_model_and_get_reflects(client, api_key, authed):
    """Authenticated PUT changing the model is reflected on a fresh GET."""
    resp = client.put("/settings", json={"llm_model": "zz-local:1b"}, headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200
    assert resp.json()["llm_model"] == "zz-local:1b"
    assert client.get("/settings").json()["llm_model"] == "zz-local:1b"


def test_removed_provider_fields_are_ignored(client, api_key, authed):
    """An old client's llm_provider or API key is ignored, never stored or echoed."""
    before = client.get("/settings").json()
    resp = client.put(
        "/settings",
        json={"llm_provider": "claude", "anthropic_api_key": "sk-zz-ignored-1234"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200
    assert resp.json() == before
    assert "sk-zz-ignored-1234" not in resp.text


# ---------------------------------------------------------------------------
# Preferences persist (base_currency, price_data_source)
# ---------------------------------------------------------------------------


def test_preferences_persist(client, api_key, authed):
    """PUT preferences; a fresh GET returns those exact values."""
    resp = client.put(
        "/settings",
        json={"base_currency": "IDR", "price_data_source": "coingecko"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200

    get_resp = client.get("/settings")
    body = get_resp.json()
    assert body["base_currency"] == "IDR"
    assert body["price_data_source"] == "coingecko"
    assert body["price_data_source"] in {"coingecko", "yfinance", "manual"}


# ---------------------------------------------------------------------------
# reset_engine invoked exactly once on a model change, not on prefs-only
# ---------------------------------------------------------------------------


def test_llm_change_resets_engine(client, api_key, monkeypatch):
    """reset_engine() is called exactly once on a model PUT, never on
    a preferences-only PUT."""
    import backend.query as query_mod

    calls = {"count": 0}

    def _fake_reset_engine():
        calls["count"] += 1

    monkeypatch.setattr(query_mod, "reset_engine", _fake_reset_engine)

    resp = client.put("/settings", json={"llm_model": "gemma4:31b-cloud"}, headers={"MONAI_API_KEY": api_key})
    assert resp.status_code == 200
    assert calls["count"] == 1

    # Preferences-only change must NOT trigger another reset.
    resp2 = client.put("/settings", json={"base_currency": "IDR"}, headers={"MONAI_API_KEY": api_key})
    assert resp2.status_code == 200
    assert calls["count"] == 1


def test_get_llm_rebuilds_from_effective_settings_after_reset(monkeypatch):
    """reset_engine() must not drop a Settings-page override: _get_llm rebuilds with it."""
    from backend import query, settings

    seen = []
    monkeypatch.setattr(settings, "get_effective_settings", lambda db: {"llm_model": "zz-local:1b"})
    monkeypatch.setattr(query, "configure_llm", lambda overrides=None: seen.append(overrides))
    query.reset_engine()
    try:
        query._get_llm()
    finally:
        query.reset_engine()
    assert seen == [{"llm_model": "zz-local:1b"}]


# ---------------------------------------------------------------------------
# GET /settings/ollama-models — the Settings model picker (261122-omp)
# ---------------------------------------------------------------------------


def _fake_ollama(monkeypatch, models=None, error=None):
    from types import SimpleNamespace

    import ollama

    class Fake:
        def __init__(self, host=None, timeout=None):
            pass

        def list(self):
            if error:
                raise error
            return SimpleNamespace(models=[
                SimpleNamespace(model=n, size=s, details=SimpleNamespace(parameter_size=p))
                for n, s, p in models
            ])

    monkeypatch.setattr(ollama, "Client", Fake)


def test_ollama_models_lists_installed_sorted(client, authed, monkeypatch):
    _fake_ollama(monkeypatch, [("zeta:1b", 900, "1B"), ("alpha:2b", 1800, "2B")])
    r = client.get("/settings/ollama-models")
    assert r.status_code == 200
    assert r.json() == [
        {"name": "alpha:2b", "size": 1800, "parameter_size": "2B"},
        {"name": "zeta:1b", "size": 900, "parameter_size": "1B"},
    ]


def test_ollama_models_unreachable_is_502(client, authed, monkeypatch):
    _fake_ollama(monkeypatch, error=ConnectionError("refused"))
    r = client.get("/settings/ollama-models")
    assert r.status_code == 502
    assert r.json()["detail"] == "Couldn't reach Ollama."


def test_ollama_models_requires_key(client, api_key, monkeypatch):
    _fake_ollama(monkeypatch, [])
    assert client.get("/settings/ollama-models").status_code == 401
