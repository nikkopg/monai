"""
Settings service — DB-backed key/value overrides for the Ollama model and app
preferences (base currency, price data source), falling back to env defaults
when no row exists (UI-03, UI-04). Ollama is the only provider (261122-rmp);
old llm_provider / *_api_key rows in app_settings are ignored.

Setting keys used from app_settings:
  llm_model, base_currency, price_data_source

Public API:
  mask_key(raw)                       -> masked bullet-last4 string or None (MCP secrets)
  get_effective_settings(db)          -> dict (SettingsOut shape)
  upsert_settings(db, patch)          -> bool (True if the model changed)
"""

import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models import AppSetting

# ---------------------------------------------------------------------------
# Setting-key constants
# ---------------------------------------------------------------------------

KEY_LLM_MODEL = "llm_model"
KEY_BASE_CURRENCY = "base_currency"
KEY_PRICE_DATA_SOURCE = "price_data_source"

ALL_KEYS = (KEY_LLM_MODEL, KEY_BASE_CURRENCY, KEY_PRICE_DATA_SOURCE)


def mask_key(raw: str | None) -> str | None:
    """Return a bullet-last4 masked form of a secret, or None for falsy
    input. Never returns the raw value."""
    if not raw:
        return None
    if len(raw) >= 4:
        return f"••••{raw[-4:]}"
    return "••••"


def get_effective_settings(db: Session) -> dict:
    """The effective settings: stored rows over env defaults."""
    rows = {row.key: row.value for row in db.query(AppSetting).all()}
    return {
        KEY_LLM_MODEL: rows.get(KEY_LLM_MODEL) or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud"),
        KEY_BASE_CURRENCY: rows.get(KEY_BASE_CURRENCY) or "IDR",
        KEY_PRICE_DATA_SOURCE: rows.get(KEY_PRICE_DATA_SOURCE) or "coingecko",
    }


def upsert_settings(db: Session, patch: dict, commit: bool = True) -> bool:
    """Upsert the given key/value patch into app_settings.

    Skips any value that is None or an empty string — "keep existing"
    semantics, so callers (e.g. PUT /settings) never accidentally clobber a
    stored value with a blank field. Returns True iff the model was written,
    signalling the caller should re-run configure_llm() + reset_engine().

    Pass commit=False to defer the commit to the caller so the settings write
    can be transactionally grouped with, e.g., an audit-log row.
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
        if key == KEY_LLM_MODEL:
            changed_llm = True

    if commit:
        db.commit()
    return changed_llm
