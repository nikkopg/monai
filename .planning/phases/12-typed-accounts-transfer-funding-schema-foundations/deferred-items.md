# Deferred Items — Phase 12

Out-of-scope discoveries logged during execution, not fixed (scope boundary).

## Plan 02

- **`backend/tests/test_settings.py::test_put_settings_requires_key`** fails
  with `503` instead of the expected `401` (no MONAI_API_KEY header should
  short-circuit to 401 before touching settings logic). Reproduced
  identically with Plan 02's `backend/models.py` changes reverted (`git
  stash`), confirming this is a pre-existing failure unrelated to migration
  010 or the `accounts.type` schema change. Not fixed — out of scope for
  this plan's file list (`alembic/versions/010_typed_accounts.py`,
  `backend/models.py`).
