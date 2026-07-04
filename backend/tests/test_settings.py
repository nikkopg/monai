"""
Settings endpoint tests — GET/PUT /settings (UI-03, UI-04).

Defines the contract before the implementation exists (RED). Covers:
  - GET returns effective settings with masked keys only, no raw key fields
  - PUT requires MONAI_API_KEY auth (401 without it)
  - PUT updates provider/model and a subsequent GET reflects the change
  - Keys are always masked (bullet-last4), never returned raw
  - Blank/absent key on PUT keeps the previously stored key (no clobber)
  - base_currency / price_data_source persist across a fresh GET
  - reset_engine() is invoked exactly once when an LLM field changes, and
    NOT invoked when only preference fields change

All tests use the live Postgres via the shared `client`/`api_key` fixtures
(conftest.py) — no mocking of the DB, only of backend.query.reset_engine
where the call-count invariant is asserted.
"""

import pytest


# ---------------------------------------------------------------------------
# GET /settings — defaults, masked-only shape
# ---------------------------------------------------------------------------


def test_get_settings_returns_defaults(client):
    """GET /settings returns 200 with the effective settings shape."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()

    assert "llm_provider" in body
    assert "llm_model" in body
    assert body.get("base_currency") == "IDR"
    assert "price_data_source" in body

    # Masked key fields present; raw key fields must never appear.
    assert "anthropic_api_key_masked" in body
    assert "openai_api_key_masked" in body
    assert "anthropic_api_key" not in body
    assert "openai_api_key" not in body


# ---------------------------------------------------------------------------
# PUT /settings — auth gate
# ---------------------------------------------------------------------------


def test_put_settings_requires_key(client):
    """PUT /settings with no MONAI_API_KEY header returns 401."""
    resp = client.put("/settings", json={"base_currency": "IDR"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /settings — provider/model update round-trip
# ---------------------------------------------------------------------------


def test_put_updates_provider_and_get_reflects(client, api_key):
    """Authenticated PUT changing provider/model is reflected on a fresh GET."""
    resp = client.put(
        "/settings",
        json={"llm_provider": "claude", "llm_model": "claude-haiku-4-5-20251001"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] == "claude"

    get_resp = client.get("/settings")
    assert get_resp.status_code == 200
    assert get_resp.json()["llm_provider"] == "claude"


# ---------------------------------------------------------------------------
# Key masking — never raw
# ---------------------------------------------------------------------------


def test_key_is_masked_never_raw(client, api_key):
    """PUT a raw API key; GET must return only the masked bullet-last4 form."""
    raw_key = "sk-ant-super-secret-1234"
    resp = client.put(
        "/settings",
        json={"anthropic_api_key": raw_key},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200

    get_resp = client.get("/settings")
    assert get_resp.status_code == 200
    body = get_resp.json()

    masked = body["anthropic_api_key_masked"]
    assert masked is not None
    assert masked.endswith(raw_key[-4:])
    assert masked != raw_key

    # Raw key string must not appear anywhere in the response body.
    assert raw_key not in get_resp.text


# ---------------------------------------------------------------------------
# Blank key on PUT keeps existing stored key
# ---------------------------------------------------------------------------


def test_blank_key_keeps_existing(client, api_key):
    """A blank/absent key field on PUT must not clobber a previously stored key."""
    raw_key = "sk-ant-keepme-5678"
    first = client.put(
        "/settings",
        json={"anthropic_api_key": raw_key},
        headers={"MONAI_API_KEY": api_key},
    )
    assert first.status_code == 200

    # Blank string means "keep existing" per plan semantics.
    second = client.put(
        "/settings",
        json={"anthropic_api_key": ""},
        headers={"MONAI_API_KEY": api_key},
    )
    assert second.status_code == 200

    get_resp = client.get("/settings")
    masked = get_resp.json()["anthropic_api_key_masked"]
    assert masked is not None
    assert masked.endswith(raw_key[-4:])


# ---------------------------------------------------------------------------
# Preferences persist (base_currency, price_data_source)
# ---------------------------------------------------------------------------


def test_preferences_persist(client, api_key):
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
# reset_engine invoked exactly once on LLM-field change, not on prefs-only
# ---------------------------------------------------------------------------


def test_llm_change_resets_engine(client, api_key, monkeypatch):
    """reset_engine() is called exactly once on an LLM-field PUT, never on
    a preferences-only PUT."""
    import backend.query as query_mod

    calls = {"count": 0}

    def _fake_reset_engine():
        calls["count"] += 1

    monkeypatch.setattr(query_mod, "reset_engine", _fake_reset_engine)

    resp = client.put(
        "/settings",
        json={"llm_provider": "ollama", "llm_model": "gemma4:31b-cloud"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp.status_code == 200
    assert calls["count"] == 1

    # Preferences-only change must NOT trigger another reset.
    resp2 = client.put(
        "/settings",
        json={"base_currency": "IDR"},
        headers={"MONAI_API_KEY": api_key},
    )
    assert resp2.status_code == 200
    assert calls["count"] == 1
