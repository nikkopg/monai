# Coding Conventions

**Analysis Date:** 2026-06-20

## Language & Style

**Python (backend, poc):**
- Python 3.12+ syntax. Modern type hints used liberally:
  `str | None`, `tuple[datetime.date | None, ...]`, `list[dict]`,
  `Mapped[int]` (SQLAlchemy 2.0 typed ORM).
- `snake_case` for functions, variables, modules; `PascalCase` for classes.
- Leading underscore marks module-private helpers: `_extract_json`,
  `_get_or_create_account`, `_date_clause`, `_currency`, `_fmt`,
  `_first_of_next_month` (`backend/query.py`, `backend/tools.py`,
  `backend/importer.py`).
- Every module opens with a triple-quoted docstring explaining *what it does and
  why* — often including the design rationale (see `backend/tools.py`,
  `backend/query.py` headers). This is a strong, consistent convention.

**TypeScript (ui):**
- Strict TS (`ui/tsconfig.json`), `camelCase` functions/state, `PascalCase`
  types (`type Tx = {...}` in `ui/app/page.tsx`).
- React function components, hooks (`useState`, `useEffect`), `async` handlers.
- Inline `React.CSSProperties` style objects (`card`, `input`, `btn`, `label`)
  rather than CSS modules or a framework — small surface, dark theme.

## Type Hints & Schemas

- Backend uses **full type annotations** on signatures and SQLAlchemy
  `Mapped[...]` columns (`backend/models.py`).
- Pydantic v2 for API boundaries (`backend/schemas.py`): `BaseModel` with
  `model_config = ConfigDict(from_attributes=True)` on read models to serialize
  ORM objects; `Field(..., description=...)` for documented/required fields.
- Schema naming by role: `*Create` (input), `*Out` (output/ORM read),
  `*Request` / `*Response` (RPC-style endpoints like `/query`).

## Error Handling

**Layered, deliberate:**
- **Domain layer raises `ValueError`** with a descriptive message
  (`importer.parse_csv` on missing columns/bad dates; `tools.resolve_period` on
  unknown period).
- **API layer translates** exceptions to HTTP: `ValueError → HTTPException(422)`,
  bad upload encoding → `400`, generic query failure → `500`
  (`backend/main.py`).
- **AI/query layer never raises to the user** — `ask()` wraps routing and tool
  execution in `try/except` and returns an honest natural-language refusal
  ("I couldn't interpret that question reliably…"). Money-app rule: *refuse
  rather than fabricate.* `TypeError` from bad tool args is caught separately
  ("parameters were off").
- `_extract_json` raises `ValueError` for malformed model output (tested).

## Patterns

- **Registry pattern:** `TOOLS = {name: callable}` dict in `backend/tools.py`;
  the router looks up by string. Adding a tool = function + registry entry +
  `_TOOL_SPEC` doc line in `query.py`.
- **Structured-dict returns:** every tool returns a `dict` with a `"tool"`
  identity key plus typed result fields; `format_answer()` dispatches on that
  key. Keeps SQL execution and presentation separate.
- **Lazy imports inside route handlers** (`backend/main.py`) — e.g.
  `from backend.query import ask` is inside the handler, to avoid circular
  imports and defer heavy LLM module loading until first use.
- **Parameterized SQL only:** all queries use SQLAlchemy `text()` with bound
  params (`:start`, `:cat`, `:lim`) — never string-interpolated user input.
  Limits are clamped (`max(1, min(int(limit), 50))`).
- **`_get_or_create_account` helper** shared between `/transactions` and the
  importer for idempotent account creation.
- **Centralized relative dates:** `resolve_period()` + the `PERIODS` tuple are
  the single source of truth for date boundaries; nothing else computes them.

## Logging

- Standard library `logging`. Module-level loggers via
  `logging.getLogger(__name__)` (`backend/importer.py`, `poc/parser.py`).
- App configures root level once: `logging.basicConfig(level=logging.INFO)` in
  `backend/main.py`.
- Skips/anomalies logged at `WARNING` (currency mismatch, unparseable amount);
  informational counts at `INFO`. No structured logging or correlation IDs.

## Configuration

- 12-factor: all config via environment variables with sensible defaults read in
  `backend/config.py` (`os.getenv(KEY, default)`). No config files or `.env`
  loader committed; Docker sets vars in `docker-compose.yml`.
- Provider switch (`LLM_PROVIDER`) drives lazy, provider-specific imports inside
  `configure_llm()` so only the chosen LLM SDK is loaded.

## Comments & Documentation

- Heavy use of *intent* comments explaining sign conventions, exclusivity of date
  bounds, and why-not decisions — e.g. the expense/income sign convention block
  at the top of `backend/tools.py`, "end_date is inclusive from a user's POV →
  make exclusive" in `resolve_period`.
- Docstrings describe return-tuple shapes precisely
  (`Returns (rows, skipped_count, detected_primary_currency)`).

## Conventions NOT present (gaps)

- No linter/formatter config committed (no `ruff`, `black`, `flake8`,
  `pyproject.toml`, `.editorconfig`, ESLint/Prettier config).
- No pre-commit hooks.
- No type-checker config (`mypy`/`pyright`) despite thorough annotations.
- No docstring style enforcement (Google/NumPy) — freeform but consistent.

---

*Conventions analysis: 2026-06-20*
