# Deferred Items — Phase 11

## Pre-existing test failure (out of scope for 11-01)

- `backend/tests/test_settings.py::test_put_settings_requires_key` fails on the
  clean tree (verified at base commit 5bf88fa with all 11-01 changes stashed:
  `1 failed, 8 passed`). Not caused by this phase's changes — likely stale
  MONAI_API_KEY state in the dev environment or a fixture-order issue.
  Discovered during 11-01 full-suite regression run (2026-07-19).
