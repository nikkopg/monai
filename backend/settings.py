"""
Settings service — DB-backed key/value overrides for LLM provider/model/keys
and app preferences (base currency, price data source), falling back to
backend.config env-var defaults when no row exists (UI-03, UI-04).

Setting keys stored in app_settings:
  llm_provider, llm_model, anthropic_api_key, openai_api_key,
  base_currency, price_data_source

Public API:
  mask_key(raw)                       -> masked bullet-last4 string or None
  get_effective_settings(db, raw_keys=False) -> dict (SettingsOut shape by default)
  upsert_settings(db, patch)          -> bool (True if any LLM-relevant field changed)
"""

import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models import AppSetting

# ---------------------------------------------------------------------------
# Setting-key constants
# ---------------------------------------------------------------------------

KEY_LLM_PROVIDER = "llm_provider"
KEY_LLM_MODEL = "llm_model"
KEY_ANTHROPIC_API_KEY = "anthropic_api_key"
KEY_OPENAI_API_KEY = "openai_api_key"
KEY_BASE_CURRENCY = "base_currency"
KEY_PRICE_DATA_SOURCE = "price_data_source"

ALL_KEYS = (
    KEY_LLM_PROVIDER,
    KEY_LLM_MODEL,
    KEY_ANTHROPIC_API_KEY,
    KEY_OPENAI_API_KEY,
    KEY_BASE_CURRENCY,
    KEY_PRICE_DATA_SOURCE,
)

# Fields that, when changed, require reconfigure_llm() + reset_engine().
_LLM_RELEVANT_KEYS = {
    KEY_LLM_PROVIDER,
    KEY_LLM_MODEL,
    KEY_ANTHROPIC_API_KEY,
    KEY_OPENAI_API_KEY,
}


def mask_key(raw: str | None) -> str | None:
    """Return a bullet-last4 masked form of a raw API key, or None for
    falsy input. Never returns the raw value."""
    if not raw:
        return None
    if len(raw) >= 4:
        return f"••••{raw[-4:]}"
    return "••••"


def _model_env_default(provider: str) -> str:
    """The per-provider model env-var default, matching backend.config."""
    if provider == "claude":
        return os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    # ollama (and unknown providers fall back to the ollama default model)
    return os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")


def _load_raw(db: Session) -> dict[str, str | None]:
    """Read all app_settings rows into a dict, falling back to env defaults
    for any key with no stored row."""
    rows = {row.key: row.value for row in db.query(AppSetting).all()}

    provider = rows.get(KEY_LLM_PROVIDER) or os.getenv("LLM_PROVIDER", "ollama")
    model = rows.get(KEY_LLM_MODEL) or _model_env_default(provider)

    return {
        KEY_LLM_PROVIDER: provider,
        KEY_LLM_MODEL: model,
        KEY_ANTHROPIC_API_KEY: rows.get(KEY_ANTHROPIC_API_KEY)
        or os.getenv("ANTHROPIC_API_KEY"),
        KEY_OPENAI_API_KEY: rows.get(KEY_OPENAI_API_KEY) or os.getenv("OPENAI_API_KEY"),
        KEY_BASE_CURRENCY: rows.get(KEY_BASE_CURRENCY) or "IDR",
        KEY_PRICE_DATA_SOURCE: rows.get(KEY_PRICE_DATA_SOURCE) or "coingecko",
    }


def get_effective_settings(db: Session, raw_keys: bool = False) -> dict:
    """Return the effective settings dict.

    raw_keys=False (default): SettingsOut shape — anthropic_api_key/
        openai_api_key are replaced by their masked *_masked forms; raw key
        fields are omitted entirely.
    raw_keys=True: internal use only (configure_llm) — includes the raw
        anthropic_api_key/openai_api_key values, never sent to the client.
    """
    raw = _load_raw(db)

    if raw_keys:
        return raw

    return {
        KEY_LLM_PROVIDER: raw[KEY_LLM_PROVIDER],
        KEY_LLM_MODEL: raw[KEY_LLM_MODEL],
        "anthropic_api_key_masked": mask_key(raw[KEY_ANTHROPIC_API_KEY]),
        "openai_api_key_masked": mask_key(raw[KEY_OPENAI_API_KEY]),
        KEY_BASE_CURRENCY: raw[KEY_BASE_CURRENCY],
        KEY_PRICE_DATA_SOURCE: raw[KEY_PRICE_DATA_SOURCE],
    }


def upsert_settings(db: Session, patch: dict) -> bool:
    """Upsert the given key/value patch into app_settings.

    Skips any value that is None or an empty string — "keep existing"
    semantics, so callers (e.g. PUT /settings) never accidentally clobber a
    stored key with a blank field. Returns True iff any LLM-relevant key
    (provider/model/either API key) was written, signalling the caller
    should re-run configure_llm() + reset_engine().
    """
    changed_llm = False
    for key, value in patch.items():
        if key not in ALL_KEYS:
            continue
        if value is None or value == "":
            continue
        row = db.get(AppSetting, key) or AppSetting(key=key)
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        db.merge(row)
        if key in _LLM_RELEVANT_KEYS:
            changed_llm = True

    db.commit()
    return changed_llm
