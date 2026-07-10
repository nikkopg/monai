"""
Price-adapter tests (Wave 0 RED targets) — filled in by Plan 04.

  - test_fetch_crypto_price      — raw httpx call to CoinGecko /simple/price
  - test_fetch_idx_price_fallback — yfinance IDX fetch with graceful fallback

Each body calls pytest.fail(...) so the downstream RED->GREEN transition is visible
(real failing targets, NOT skips). No production price module is imported here —
those names are referenced lazily inside the real assertions Plan 04 will add.
"""

import pytest


def test_fetch_crypto_price():
    pytest.fail("not yet implemented — Plan 04 fills this")


def test_fetch_idx_price_fallback():
    pytest.fail("not yet implemented — Plan 04 fills this")
