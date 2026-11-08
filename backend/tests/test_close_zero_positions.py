"""Hand-run script converting zero-quantity positions into closed records (quick 261107-nq6).

Runs only against per-process scratch databases `monai_test_closezero_<token>`, created and
dropped on the same server as conftest's guarded DATABASE_URL. Never touches `monai` or
`monai_test`. CLI tests run the owner's real command as a subprocess. All values are
synthetic; no test reaches the network (past-date FX rates are cached, J's adapter is stubbed).
"""
import ast
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
REV_020 = "c4f2a8e61d93"
REV_021 = "e3b7a91c5d42"
REV_022 = "b8d4e2f09a17"
TOL = Decimal("0.00000001")
FLOOR = date(2026, 2, 7)
SCRATCH_PREFIX = "monai_test_closezero"
TOKEN = secrets.token_hex(4)  # per-process: concurrent runs must not FORCE-drop each other
WIPE = (
    "TRUNCATE closed_positions, portfolio_events, holdings, portfolio_value_history, "
    "fx_rate_cache, audit_log, transactions, accounts, platforms RESTART IDENTITY CASCADE"
)
TABLES_SQL = text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")


def _cfg(url: str):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.attributes["sqlalchemy.url"] = url  # raw string, never str(URL)
    return cfg, command


class _Scratch:
    """Create `<prefix>_<token>_<tag>` at a revision; drop it on exit."""

    def __init__(self, tag: str, revision: str):
        self.name = f"{SCRATCH_PREFIX}_{TOKEN}_{tag}"
        self.revision = revision
        base = make_url(os.environ["DATABASE_URL"])
        assert base.database != "monai" and self.name != "monai"
        self.base = base
        self.admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
        self.url = base.set(database=self.name).render_as_string(hide_password=False)

    def __enter__(self):
        self._drop()
        with self.admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{self.name}"'))
        mp = pytest.MonkeyPatch()
        mp.setattr("logging.config.fileConfig", lambda *a, **k: None)
        try:
            cfg, command = _cfg(self.url)
            command.upgrade(cfg, self.revision)
        finally:
            mp.undo()
        self.engine = create_engine(self.url)
        return self

    def __exit__(self, *exc):
        self.engine.dispose()
        self._drop()
        self.admin.dispose()

    def _drop(self):
        with self.admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))


@pytest.fixture(scope="module")
def scratch_head():
    with _Scratch("head", "head") as s:
        yield s


@pytest.fixture()
def seeded(scratch_head):
    """Fresh synthetic data A-I in the scratch DB. Returns ids by letter."""
    eng = scratch_head.engine
    with eng.begin() as c:
        assert c.execute(text("SELECT current_database()")).scalar() == scratch_head.name
        c.execute(text(WIPE))
    ids = _seed(eng)
    ids["engine"] = eng
    ids["url"] = scratch_head.url
    return ids


def _seed(eng) -> dict:
    ids: dict = {}
    with eng.begin() as c:
        def q(sql, **p):
            return c.execute(text(sql), p).scalar()

        plat = q("INSERT INTO platforms (name, kind) VALUES ('zzcz-plat', 'exchange') RETURNING id")
        acct = q("INSERT INTO accounts (name, type, currency) VALUES ('zzcz-acc', 'liquid', 'IDR') RETURNING id")
        ids["plat"] = plat

        def holding(letter, ticker, qty, avg="0", ccy="IDR", asset_type=None):
            ids[letter] = q(
                "INSERT INTO holdings (ticker, quantity, avg_cost, currency, asset_type, platform_id) "
                "VALUES (:t, :q, :a, :c, :at, :p) RETURNING id",
                t=ticker, q=qty, a=avg, c=ccy, at=asset_type, p=plat,
            )
            ids[f"{letter}_ticker"] = ticker

        def ev(ticker, kind, qty, price, day, ccy="IDR", tx=None):
            return q(
                "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, currency, transaction_id) "
                "VALUES (:d, :t, :k, :q, :pr, :p, :c, :tx) RETURNING id",
                d=day, t=ticker, k=kind, q=qty, pr=price, p=plat, c=ccy, tx=tx,
            )

        # A: IDR, sells to zero, a dividend, a linked cash transaction. Realized 80 + 50 + 180 = 310.
        holding("A", "ZZCZA", "0")
        ev("ZZCZA", "buy", "10", "100", "2026-01-05")
        ev("ZZCZA", "sell", "4", "120", "2026-02-05")
        ev("ZZCZA", "dividend", "1", "50", "2026-02-10")
        ids["A_tx"] = q(
            "INSERT INTO transactions (date, amount, currency, account_id, is_transfer, category) "
            "VALUES ('2026-03-05 10:00', 780, 'IDR', :a, true, 'Investment') RETURNING id", a=acct,
        )
        ev("ZZCZA", "sell", "6", "130", "2026-03-05", tx=ids["A_tx"])

        # B: USD, zero, exact-date cached rates. Realized (12*16000 - 10*15000) * 5 = 210000.
        holding("B", "ZZCZB", "0", ccy="USD")
        for day, rate in (("2026-01-10", "15000"), ("2026-02-10", "16000")):
            c.execute(text(
                "INSERT INTO fx_rate_cache (rate_date, base_currency, quote_currency, rate, source) "
                "VALUES (:d, 'USD', 'IDR', :r, 'zzcz')"), {"d": day, "r": rate})
        ev("ZZCZB", "buy", "5", "10", "2026-01-10", ccy="USD")
        ev("ZZCZB", "sell", "5", "12", "2026-02-10", ccy="USD")

        # C: zero row, a dividend but no sell.
        holding("C", "ZZCZC", "0")
        ev("ZZCZC", "dividend", "1", "20", "2026-01-15")
        # D: zero row whose ledger went negative first.
        holding("D", "ZZCZD", "0")
        ev("ZZCZD", "sell", "2", "10", "2026-01-01")
        ev("ZZCZD", "buy", "2", "10", "2026-01-02")
        # E: zero row hand-edited while the ledger sums to 3 (a recompute would overwrite it).
        holding("E", "ZZCZE", "0", avg="7")
        ev("ZZCZE", "buy", "5", "7", "2026-01-03")
        ev("ZZCZE", "sell", "2", "8", "2026-01-04")
        # F: dust.
        holding("F", "ZZCZF", "0.00000001", avg="9")
        ev("ZZCZF", "buy", "1", "9", "2026-01-06")
        ev("ZZCZF", "sell", "0.99999999", "9", "2026-01-07")
        # G: CASH zero row with a deposit.
        holding("G", "CASH", "0", asset_type="cash")
        ev("CASH", "deposit", "100", "1", "2026-01-08")
        # H: empty zero row.
        holding("H", "ZZCZH", "0")
        # I: open position with a partial sell.
        holding("I", "ZZCZI", "3", avg="50")
        ev("ZZCZI", "buy", "5", "50", "2026-01-09")
        ev("ZZCZI", "sell", "2", "60", "2026-01-12")

        c.execute(text(
            "INSERT INTO portfolio_value_history (snapshot_date, ticker, quantity, market_value, cost_basis, currency, platform_id) "
            "VALUES (:d, 'ZZCZI', 3, 150, 150, 'IDR', :p)"), {"d": FLOOR, "p": plat})
    return ids


def _dump(eng) -> dict[str, list[str]]:
    """Every public table as sorted jsonb text rows: equality means byte-identical."""
    with eng.connect() as c:
        names = sorted(r[0] for r in c.execute(TABLES_SQL))
        return {
            n: sorted(r[0] for r in c.execute(text(f'SELECT to_jsonb(t)::text FROM "{n}" t')))
            for n in names
        }


def _rows(eng, table: str, where: str, **p) -> list[str]:
    with eng.connect() as c:
        return sorted(r[0] for r in c.execute(text(f'SELECT to_jsonb(t)::text FROM "{table}" t WHERE {where}'), p))


def _session(eng):
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


def _cli(url: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "backend.close_zero_positions", *args],
        cwd=REPO_ROOT, env={**os.environ, "DATABASE_URL": url},
        capture_output=True, text=True, timeout=120,
    )


def _line(out: str, ticker: str) -> str:
    hits = [ln for ln in out.splitlines() if f"ticker={ticker} " in ln + " "]
    assert len(hits) == 1, (ticker, out)
    return hits[0]


def _field(line: str, name: str) -> str:
    return re.search(rf"{name}=(\S+)", line).group(1)


# --- boot: nothing runs, nothing blocks -------------------------------------------------


def test_boot_ignores_zero_rows():
    with _Scratch("boot", REV_020) as s:
        _seed(s.engine)  # zero rows, dust, CASH and an empty row, all at revision 020
        with s.engine.connect() as c:
            assert c.execute(text("SELECT to_regclass('closed_positions')")).scalar() is None
        before = _dump(s.engine)
        mp = pytest.MonkeyPatch()
        mp.setattr("logging.config.fileConfig", lambda *a, **k: None)
        try:
            cfg, command = _cfg(s.url)
            command.upgrade(cfg, REV_021)  # no flag, no environment variable
        finally:
            mp.undo()
        after = _dump(s.engine)
        assert after.pop("closed_positions") == []
        before.pop("alembic_version"), after.pop("alembic_version")
        assert after == before


def test_021_is_table_only():
    tree = ast.parse((REPO_ROOT / "alembic" / "versions" / "021_closed_positions.py").read_text())
    for node in ast.walk(tree):
        assert not isinstance(node, ast.Raise)
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("environ", "getenv", "execute")
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "backend" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "backend"


def _strip(dump: dict, table: str, col: str) -> list[str]:
    return sorted(json.dumps({k: v for k, v in json.loads(r).items() if k != col}, sort_keys=True) for r in dump[table])


def test_022_keeps_every_value():
    with _Scratch("r022", REV_021) as s:
        _seed(s.engine)
        with s.engine.begin() as c:
            c.execute(text("INSERT INTO platforms (name, kind) VALUES ('zzcz-other', 'broker')"))
        before = _dump(s.engine)
        with s.engine.connect() as c:
            prices = {r[0]: r[1] for r in c.execute(text("SELECT id, price FROM portfolio_events"))}
        mp = pytest.MonkeyPatch()
        mp.setattr("logging.config.fileConfig", lambda *a, **k: None)
        try:
            cfg, command = _cfg(s.url)
            command.upgrade(cfg, REV_022)
        finally:
            mp.undo()
        after = _dump(s.engine)
        with s.engine.connect() as c:
            new_prices = {r[0]: r[1] for r in c.execute(text("SELECT id, price FROM portfolio_events"))}
            currencies = [r[0] for r in c.execute(text("SELECT currency FROM platforms"))]
        assert prices and new_prices == prices
        assert currencies and set(currencies) == {"IDR"}
        for t in before:
            if t in ("alembic_version", "portfolio_events", "platforms"):
                continue
            assert after[t] == before[t], t
        assert _strip(after, "portfolio_events", "price") == _strip(before, "portfolio_events", "price")
        assert _strip(after, "platforms", "currency") == _strip(before, "platforms", "currency")


def test_022_alters_types_only():
    path = next((REPO_ROOT / "alembic" / "versions").glob("022_*.py"))
    for node in ast.walk(ast.parse(path.read_text())):
        assert not isinstance(node, ast.Raise)
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("environ", "getenv", "execute")
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "backend" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "backend"


def test_023_keeps_every_value():
    with _Scratch("r023", REV_022) as s:
        _seed(s.engine)
        before = _dump(s.engine)
        mp = pytest.MonkeyPatch()
        mp.setattr("logging.config.fileConfig", lambda *a, **k: None)
        try:
            cfg, command = _cfg(s.url)
            command.upgrade(cfg, "head")
        finally:
            mp.undo()
        after = _dump(s.engine)
        assert before["portfolio_events"]
        for t in before:
            if t not in ("alembic_version", "portfolio_events"):
                assert after[t] == before[t], t
        stripped = sorted(
            json.dumps({k: v for k, v in json.loads(r).items() if k not in ("fee", "fee_kind")}, sort_keys=True)
            for r in after["portfolio_events"]
        )
        assert stripped == sorted(json.dumps(json.loads(r), sort_keys=True) for r in before["portfolio_events"])
        assert all(json.loads(r)["fee"] is None and json.loads(r)["fee_kind"] is None for r in after["portfolio_events"])
        with s.engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM pg_constraint WHERE conname = 'ck_portfolio_events_fee'")).scalar() == 1


def test_023_check_allows_only_a_complete_fee():
    with _Scratch("r023c", "head") as s:
        _seed(s.engine)
        def insert(fee, kind):
            with s.engine.begin() as c:
                c.execute(text(
                    "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, fee, fee_kind) "
                    "SELECT '2026-01-01', 'ZZCZX', 'buy', 1, 1, id, :f, :k FROM platforms LIMIT 1"), {"f": fee, "k": kind})
        insert(None, None)
        insert("0.5", "coin")
        insert("2", "cash")
        for bad in (("0.5", None), (None, "coin"), ("0", "coin"), ("-1", "cash"), ("1", "zz")):
            with pytest.raises(Exception, match="ck_portfolio_events_fee"):
                insert(*bad)


def test_023_adds_columns_only():
    path = next((REPO_ROOT / "alembic" / "versions").glob("023_*.py"))
    for node in ast.walk(ast.parse(path.read_text())):
        assert not isinstance(node, ast.Raise)
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("environ", "getenv", "execute")
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "backend" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "backend"


def test_script_not_wired_to_boot():
    files = [
        "backend/entrypoint.sh", "backend/Dockerfile", "docker-compose.yml",
        "backend/main.py", "backend/scheduler.py", "alembic/env.py",
        *(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "alembic" / "versions").glob("*.py")),
    ]
    for f in files:
        assert "close_zero_positions" not in (REPO_ROOT / f).read_text(), f


# --- the CLI ----------------------------------------------------------------------------


def test_cli_defaults_to_dry_run(seeded):
    before = _dump(seeded["engine"])
    r = _cli(seeded["url"])
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert out.splitlines()[0].startswith(f"database: {make_url(seeded['url']).database} ")
    assert "dry run" in out.lower() and "convert: 2" in out
    a, b = _line(out, "ZZCZA"), _line(out, "ZZCZB")
    assert Decimal(_field(a, "realized")) == Decimal("310") and _field(a, "close_date") == "2026-03-05"
    assert _field(a, "events") == "4" and _field(a, "events_before_snapshot_floor") == "2"
    assert Decimal(_field(b, "realized")) == Decimal("210000") and _field(b, "close_date") == "2026-02-10"
    assert _field(b, "events") == "2" and _field(b, "events_before_snapshot_floor") == "1"
    assert "empty rows to delete (no events, no record): 1" in out
    assert "cash rows left alone: 1" in out
    assert _field(_line(out, "ZZCZC"), "left_alone") == "no_sell"
    assert _field(_line(out, "ZZCZD"), "left_alone") == "negative_running_quantity"
    assert _field(_line(out, "ZZCZE"), "left_alone") == "ledger_not_zero"
    assert _dump(seeded["engine"]) == before


def test_cli_apply_converts(seeded):
    eng = seeded["engine"]
    before = _dump(eng)
    keep_ids = ",".join(str(seeded[k]) for k in "CDEFGI")
    keep_tickers = "'ZZCZC','ZZCZD','ZZCZE','ZZCZF','CASH','ZZCZI'"
    held = _rows(eng, "holdings", f"id IN ({keep_ids})")
    held_ev = _rows(eng, "portfolio_events", f"ticker IN ({keep_tickers})")
    r = _cli(seeded["url"], "--apply")
    assert r.returncode == 0, r.stderr
    after = _dump(eng)
    assert after["transactions"] == before["transactions"]  # the sell's cash leg stays
    assert _rows(eng, "holdings", f"id IN ({keep_ids})") == held  # E's quantity is not overwritten
    assert _rows(eng, "portfolio_events", f"ticker IN ({keep_tickers})") == held_ev
    recs = {x["ticker"]: x for x in map(json.loads, after["closed_positions"])}
    assert set(recs) == {"ZZCZA", "ZZCZB"}
    assert Decimal(str(recs["ZZCZA"]["realized_pnl"])) == Decimal("310")
    assert Decimal(str(recs["ZZCZB"]["realized_pnl"])) == Decimal("210000")
    assert not _rows(eng, "holdings", "ticker IN ('ZZCZA','ZZCZB','ZZCZH')")
    assert not _rows(eng, "portfolio_events", "ticker IN ('ZZCZA','ZZCZB')")
    # H: deleted with an audit row and no record.
    assert len(_rows(eng, "audit_log", "entity='holding' AND operation='delete' AND entity_id=:i", i=seeded["H"])) == 1
    assert not any(x["ticker"] == "ZZCZH" for x in map(json.loads, after["closed_positions"]))
    assert "applied" in r.stdout.lower()


def test_cli_apply_is_idempotent(seeded):
    assert _cli(seeded["url"], "--apply").returncode == 0
    mid = _dump(seeded["engine"])
    r = _cli(seeded["url"], "--apply")
    assert r.returncode == 0, r.stderr
    assert "nothing to convert" in r.stdout.lower()
    assert _dump(seeded["engine"]) == mid


def test_cli_unknown_flag_writes_nothing(seeded):
    before = _dump(seeded["engine"])
    r = _cli(seeded["url"], "--force")
    assert r.returncode != 0
    assert _dump(seeded["engine"]) == before


def test_cli_missing_table():
    with _Scratch("old", REV_020) as s:
        r = _cli(s.url, "--apply")
        assert r.returncode != 0
        assert "alembic upgrade head" in r.stdout
        assert "Traceback" not in r.stdout + r.stderr
        assert len((r.stdout + r.stderr).strip().splitlines()) <= 3  # name, mode, one line


# --- run(): one transaction, one commit -------------------------------------------------


def test_apply_is_one_transaction(seeded, monkeypatch):
    import backend.close_zero_positions as czp

    real, calls = czp.close_position_if_flat, []

    def boom(db, ticker, platform_id):
        calls.append(ticker)
        if len(calls) == 2:
            raise RuntimeError("synthetic failure on the second position")
        return real(db, ticker, platform_id)

    monkeypatch.setattr(czp, "close_position_if_flat", boom)
    before = _dump(seeded["engine"])
    db = _session(seeded["engine"])
    try:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            czp.run(db, apply=True)
    finally:
        db.close()
    assert len(calls) == 2
    assert _dump(seeded["engine"]) == before  # the first position was rolled back too


def test_apply_aborts_if_cash_changes(seeded, monkeypatch):
    import backend.close_zero_positions as czp
    from backend.models import Transaction

    real = czp.close_position_if_flat

    def sneaky(db, ticker, platform_id):
        rec = real(db, ticker, platform_id)
        tx = db.get(Transaction, seeded["A_tx"])
        if tx is not None:
            db.delete(tx)
        return rec

    monkeypatch.setattr(czp, "close_position_if_flat", sneaky)
    before = _dump(seeded["engine"])
    db = _session(seeded["engine"])
    try:
        with pytest.raises(Exception, match="nothing was changed"):
            czp.run(db, apply=True)
    finally:
        db.close()
    assert _rows(seeded["engine"], "transactions", "id=:i", i=seeded["A_tx"])  # still there
    assert _dump(seeded["engine"]) == before


def test_realized_matches_and_total_unchanged(seeded, monkeypatch):
    import backend.close_zero_positions as czp
    from backend import fx
    from backend.portfolio import _realized_for_position, portfolio_summary

    # J: a USD position at zero with no cached rate; the adapter returns nothing, so no network.
    monkeypatch.setitem(fx.FX_ADAPTERS, "frankfurter", lambda base, quote, as_of: None)
    with seeded["engine"].begin() as c:
        c.execute(text("INSERT INTO holdings (ticker, quantity, avg_cost, currency, platform_id) VALUES ('ZZCZJ', 0, 0, 'USD', :p)"), {"p": seeded["plat"]})
        for kind, price, day in (("buy", "5", "2026-01-20"), ("sell", "6", "2026-01-21")):
            c.execute(text(
                "INSERT INTO portfolio_events (date, ticker, event_type, quantity, price, platform_id, currency) "
                "VALUES (:d, 'ZZCZJ', :k, 1, :pr, :p, 'USD')"), {"d": day, "k": kind, "pr": price, "p": seeded["plat"]})
    j_before = _rows(seeded["engine"], "holdings", "ticker='ZZCZJ'"), _rows(seeded["engine"], "portfolio_events", "ticker='ZZCZJ'")

    db = _session(seeded["engine"])
    try:
        read = {t: _realized_for_position(db, t, seeded["plat"])["realized_pnl"] for t in ("ZZCZA", "ZZCZB")}
        total_before = portfolio_summary(db)["total_realized_pnl"]
        dry = czp.run(db, apply=False)
        assert {c["ticker"]: c["realized"] for c in dry["convert"]} == read
        assert [x["ticker"] for x in dry["left"] if x["reason"] == "no_rate"] == ["ZZCZJ"]
        done = czp.run(db, apply=True)
    finally:
        db.close()
    assert {c["ticker"] for c in done["convert"]} == {"ZZCZA", "ZZCZB"}

    db = _session(seeded["engine"])
    try:
        stored = {r[0]: r[1] for r in db.execute(text("SELECT ticker, realized_pnl FROM closed_positions"))}
        assert set(stored) == {"ZZCZA", "ZZCZB"}
        for t, v in read.items():
            assert abs(stored[t] - v) <= TOL
        assert abs(portfolio_summary(db)["total_realized_pnl"] - total_before) <= TOL
    finally:
        db.close()
    assert (_rows(seeded["engine"], "holdings", "ticker='ZZCZJ'"), _rows(seeded["engine"], "portfolio_events", "ticker='ZZCZJ'")) == j_before
