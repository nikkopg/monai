"""Phase 31 approval-path tests (APPR-01, APPR-02, APPR-05) against monai_test.

Synthetic values only. Every seeded row is deleted in a finally/teardown. Never
assert that a leftover row from another test is still pending: any
GET /proposals bulk-expires stale rows.
"""
import datetime
import types
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text


@pytest.fixture(scope="module")
def db_available():
    from backend.db import engine
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")
    return True


@pytest.fixture()
def db_session(db_available):
    from backend.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_PAYLOAD = {"operation": "add_transaction", "rows": []}


def _count(db) -> int:
    return db.execute(text("SELECT count(*) FROM proposals")).scalar()


def _make_and_check(db, channel, ttl):
    from backend.models import Proposal
    from backend.tools import _make_proposal

    pid, _token = (
        _make_proposal("add_transaction", _PAYLOAD)
        if channel is None
        else _make_proposal("add_transaction", _PAYLOAD, channel=channel)
    )
    try:
        row = db.get(Proposal, uuid.UUID(pid))
        assert row.channel == (channel or "chat")
        assert row.status == "pending"
        assert row.failed_attempts == 0
        if row.channel == "mcp":
            assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{6}", row.code)
        else:
            assert row.code is None
        assert abs((row.expires_at - row.created_at) - ttl) < timedelta(seconds=60)
    finally:
        db.rollback()
        db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": pid})
        db.commit()


def test_ttl_for_table():
    from backend.proposals import ttl_for

    assert ttl_for("chat") == timedelta(minutes=15)
    assert ttl_for("mcp") == timedelta(hours=48)
    for ch in ("discord", "upload"):
        with pytest.raises(ValueError):
            ttl_for(ch)


def test_ttl_make_proposal_chat_default(db_session):
    _make_and_check(db_session, None, timedelta(minutes=15))


def test_ttl_make_proposal_mcp(db_session):
    _make_and_check(db_session, "mcp", timedelta(hours=48))


def test_ttl_make_proposal_unknown_channel_raises(db_session):
    from backend.tools import _make_proposal

    before = _count(db_session)
    with pytest.raises(ValueError):
        _make_proposal("add_transaction", _PAYLOAD, channel="discord")
    db_session.rollback()
    assert _count(db_session) == before


def _fake(status="pending"):
    return types.SimpleNamespace(status=status, status_changed_at=None, confirmed_at=None)


def test_transition_confirmed_stamps_both_times():
    from backend.proposals import transition

    p = _fake()
    transition(p, "confirmed")
    assert p.status == "confirmed"
    assert p.status_changed_at is not None and p.status_changed_at.tzinfo is not None
    assert p.confirmed_at == p.status_changed_at


def test_transition_rejected_keeps_confirmed_at_none():
    from backend.proposals import transition

    p = _fake()
    transition(p, "rejected")
    assert p.status == "rejected"
    assert p.status_changed_at is not None
    assert p.confirmed_at is None


def test_transition_refuses_non_pending_and_unknown_target():
    from backend.proposals import transition

    for st in ("confirmed", "rejected", "expired"):
        with pytest.raises(ValueError, match=f"Proposal already {st}"):
            transition(_fake(st), "rejected")
    for bad in ("locked", "pending"):
        p = _fake()
        with pytest.raises(ValueError):
            transition(p, bad)
        assert p.status == "pending"


# ---------------------------------------------------------------------------
# Approver key dependencies (APPR-01, D-15)
# ---------------------------------------------------------------------------

def _set_keys(monkeypatch, api, approver):
    import backend.auth as auth

    monkeypatch.setattr(auth, "_CONFIGURED_KEY", api)
    monkeypatch.setattr(auth, "_CONFIGURED_APPROVER_KEY", approver, raising=False)
    return auth


def test_approver_auth_key_ok_matrix(monkeypatch):
    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    assert auth.approver_key_ok("appr-y") is True
    for bad in ("api-x", None, ""):
        assert auth.approver_key_ok(bad) is False
    auth = _set_keys(monkeypatch, "api-x", "api-x")
    for v in ("api-x", None, "", "appr-y"):
        assert auth.approver_key_ok(v) is False
    auth = _set_keys(monkeypatch, "api-x", "")
    for v in ("api-x", None, "", "appr-y"):
        assert auth.approver_key_ok(v) is False


def test_key_checks_non_ascii_is_false_not_error(monkeypatch):
    # str compare_digest raises TypeError on non-ASCII; that used to surface as a 500.
    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    assert auth.key_ok("api-\xe9") is False
    assert auth.approver_key_ok("appr-\xe9") is False


def test_approver_auth_require_dependency(monkeypatch):
    from fastapi import HTTPException

    auth = _set_keys(monkeypatch, "api-x", "")
    with pytest.raises(HTTPException) as e:
        auth.require_approver_key("anything")
    assert e.value.status_code == 503
    auth = _set_keys(monkeypatch, "api-x", "api-x")
    with pytest.raises(HTTPException) as e:
        auth.require_approver_key("api-x")
    assert e.value.status_code == 503
    assert "api-x" not in e.value.detail
    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    for bad in (None, "wrong"):
        with pytest.raises(HTTPException) as e:
            auth.require_approver_key(bad)
        assert e.value.status_code == 401
        assert e.value.detail == "Invalid or missing approver key"
        assert "appr-y" not in e.value.detail and "api-x" not in e.value.detail
    assert auth.require_approver_key("appr-y") is None
    assert auth.optional_approver("appr-y") is True
    assert auth.optional_approver("nope") is False
    assert auth.optional_approver(None) is False


def test_approver_auth_reject_scope_dependency(monkeypatch):
    from fastapi import HTTPException

    auth = _set_keys(monkeypatch, "api-x", "appr-y")
    assert auth.require_reject_scope("api-x", None) == "chat"
    assert auth.require_reject_scope(None, "appr-y") == "approver"
    for args in (("api-x", "wrong"), (None, None), ("wrong", None)):
        with pytest.raises(HTTPException) as e:
            auth.require_reject_scope(*args)
        assert e.value.status_code == 401


def test_mcp_guard_rejects_approver_key(client, api_key, approver_key):
    for headers in (
        {"MONAI_API_KEY": approver_key},
        {"Authorization": f"Bearer {approver_key}"},
        {"MONAI_APPROVER_KEY": approver_key},
    ):
        assert client.post("/mcp", json={}, headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# Approve / confirm / reject across channels (APPR-01, APPR-05; D-12..D-17, D-24)
# ---------------------------------------------------------------------------

import re
import secrets
from pathlib import Path

EXPIRED_MSG = "Proposal expired — ask again to redo this"
CHAT_ONLY_MSG = "Token confirm is chat-only; approve this proposal in monai"
REJECT_SCOPE_MSG = "Rejecting a non-chat proposal requires the approver key"


@pytest.fixture()
def seed(db_available):
    from backend.db import SessionLocal
    from backend.models import Proposal

    ids: list[uuid.UUID] = []

    def _seed(*, channel="chat", status="pending", expires_delta=timedelta(minutes=15),
              code=None, payload=None):
        payload = payload or {"operation": "add_transaction", "rows": []}
        token = secrets.token_urlsafe(32)
        db = SessionLocal()
        try:
            p = Proposal(
                token=token, operation=payload["operation"], payload=payload,
                status=status, channel=channel, code=code,
                expires_at=datetime.datetime.now(datetime.timezone.utc) + expires_delta,
            )
            db.add(p)
            db.commit()
            ids.append(p.id)
            return str(p.id), token
        finally:
            db.close()

    yield _seed
    db = SessionLocal()
    try:
        for i in ids:
            db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": i})
        db.commit()
    finally:
        db.close()


def _row(pid: str):
    from backend.db import SessionLocal
    from backend.models import Proposal

    db = SessionLocal()
    try:
        p = db.get(Proposal, uuid.UUID(pid))
        db.expunge(p)
        return p
    finally:
        db.close()


def _api(api_key):
    return {"MONAI_API_KEY": api_key}


def _appr(approver_key):
    return {"MONAI_APPROVER_KEY": approver_key}


def test_legacy_pending_chat_proposal_confirms_by_token(client, api_key, db_available):
    from backend.db import SessionLocal

    pid, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO proposals (id, token, operation, payload, status, expires_at) "
                "VALUES (:i, :t, 'add_transaction', CAST(:p AS jsonb), 'pending', "
                "now() + interval '15 minutes')"
            ),
            {"i": pid, "t": token, "p": '{"operation": "add_transaction", "rows": []}'},
        )
        db.commit()
        row = _row(pid)
        assert row.channel == "chat" and row.failed_attempts == 0
        assert row.status_changed_at is not None
        r = client.post(f"/proposals/{pid}/confirm", json={"token": token}, headers=_api(api_key))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "confirmed"
    finally:
        db.execute(text("DELETE FROM proposals WHERE id = :i"), {"i": pid})
        db.commit()
        db.close()


def test_confirm_chat_outcomes_unchanged(client, api_key, seed):
    h = _api(api_key)
    r = client.post(f"/proposals/{uuid.uuid4()}/confirm", json={"token": "x"}, headers=h)
    assert (r.status_code, r.json()["detail"]) == (404, "Proposal not found")

    pid, tok = seed(status="rejected")
    r = client.post(f"/proposals/{pid}/confirm", json={"token": tok}, headers=h)
    assert (r.status_code, r.json()["detail"]) == (409, "Proposal already rejected")

    pid, tok = seed(expires_delta=timedelta(minutes=-1))
    r = client.post(f"/proposals/{pid}/confirm", json={"token": tok}, headers=h)
    assert (r.status_code, r.json()["detail"]) == (410, EXPIRED_MSG)

    pid, tok = seed()
    r = client.post(f"/proposals/{pid}/confirm", json={"token": "wrong"}, headers=h)
    assert (r.status_code, r.json()["detail"]) == (401, "Invalid confirmation token")
    assert _row(pid).status == "pending"

    pid, tok = seed(status="expired")
    r = client.post(f"/proposals/{pid}/confirm", json={"token": tok}, headers=h)
    assert (r.status_code, r.json()["detail"]) == (410, EXPIRED_MSG)


@pytest.mark.parametrize("channel", ["mcp", "discord", "upload"])
def test_confirm_chat_only_403_for_non_chat(client, api_key, seed, channel):
    pid, tok = seed(channel=channel)
    r = client.post(f"/proposals/{pid}/confirm", json={"token": tok}, headers=_api(api_key))
    assert (r.status_code, r.json()["detail"]) == (403, CHAT_ONLY_MSG)
    assert _row(pid).status == "pending"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "confirmed"},
        {"status": "expired"},
        {"expires_delta": timedelta(minutes=-1)},
    ],
)
def test_confirm_chat_only_403_precedes_status_and_expiry(client, api_key, seed, kwargs):
    pid, tok = seed(channel="mcp", **kwargs)
    r = client.post(f"/proposals/{pid}/confirm", json={"token": tok}, headers=_api(api_key))
    assert (r.status_code, r.json()["detail"]) == (403, CHAT_ONLY_MSG)


@pytest.mark.parametrize("channel", ["chat", "mcp", "discord", "upload"])
def test_approver_approves_every_channel(client, api_key, approver_key, seed, channel):
    pid, tok = seed(channel=channel)
    r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert "token" not in body and "code" not in body
    row = _row(pid)
    assert row.status == "confirmed" and row.confirmed_at == row.status_changed_at


def test_approver_approve_applies_effects_once(client, api_key, approver_key, seed, db_session):
    from backend.models import Transaction

    tx = Transaction(
        date=datetime.datetime(2020, 5, 1, 12, 0, 0), amount=-30000, currency="IDR",
        category="ZZ31Cat", merchant="ZZ31Merchant", is_transfer=False,
    )
    db_session.add(tx)
    db_session.commit()
    tx_id = tx.id
    payload = {
        "operation": "edit_transaction",
        "rows": [{
            "id": tx_id,
            "before": {"id": tx_id, "category": "ZZ31Cat", "amount": "-30000"},
            "after": {"id": tx_id, "category": "ZZ31New", "amount": "-30000"},
        }],
    }
    pid, _ = seed(channel="mcp", payload=payload)
    try:
        r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
        assert r.status_code == 200, r.text
        db_session.expire_all()
        assert db_session.get(Transaction, tx_id).category == "ZZ31New"
        n = db_session.execute(
            text("SELECT count(*) FROM audit_log WHERE entity='transaction' AND entity_id=:i"),
            {"i": tx_id},
        ).scalar()
        assert n == 1
        r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
        assert (r.status_code, r.json()["detail"]) == (409, "Proposal already confirmed")
    finally:
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM audit_log WHERE entity='transaction' AND entity_id=:i"), {"i": tx_id}
        )
        db_session.execute(text("DELETE FROM transactions WHERE id=:i"), {"i": tx_id})
        db_session.commit()


@pytest.mark.parametrize(
    "kwargs", [{"status": "expired"}, {"expires_delta": timedelta(minutes=-1)}]
)
def test_approver_approve_expired_410(client, approver_key, seed, kwargs):
    pid, _ = seed(channel="mcp", **kwargs)
    r = client.post(f"/proposals/{pid}/approve", headers=_appr(approver_key))
    assert (r.status_code, r.json()["detail"]) == (410, EXPIRED_MSG)


def test_approver_auth_on_approve_route(client, api_key, approver_key, seed, monkeypatch):
    import backend.auth as auth

    pid, _ = seed(channel="mcp")
    url = f"/proposals/{pid}/approve"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=_api(api_key)).status_code == 401
    assert client.post(url, headers=_appr("wrong")).status_code == 401
    monkeypatch.setattr(auth, "_CONFIGURED_APPROVER_KEY", "")
    assert client.post(url, headers=_appr(approver_key)).status_code == 503
    monkeypatch.setattr(auth, "_CONFIGURED_APPROVER_KEY", api_key)
    assert client.post(url, headers=_appr(api_key)).status_code == 503
    assert _row(pid).status == "pending"


@pytest.mark.parametrize("channel", ["chat", "mcp", "discord", "upload"])
def test_approver_rejects_every_channel(client, approver_key, seed, channel):
    pid, _ = seed(channel=channel)
    r = client.post(f"/proposals/{pid}/reject", headers=_appr(approver_key))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    row = _row(pid)
    assert row.status == "rejected" and row.confirmed_at is None
    assert row.status_changed_at is not None


@pytest.mark.parametrize("channel", ["chat", "mcp", "discord", "upload"])
def test_reject_scope_api_key_chat_only(client, api_key, approver_key, seed, channel):
    pid, _ = seed(channel=channel)
    r = client.post(f"/proposals/{pid}/reject", headers=_api(api_key))
    if channel == "chat":
        assert r.status_code == 200 and _row(pid).status == "rejected"
    else:
        assert (r.status_code, r.json()["detail"]) == (403, REJECT_SCOPE_MSG)
        assert _row(pid).status == "pending"


def test_reject_scope_wrong_approver_header_401(client, api_key, approver_key, seed):
    pid, _ = seed(channel="chat")
    r = client.post(
        f"/proposals/{pid}/reject", headers={**_api(api_key), **_appr("wrong")}
    )
    assert r.status_code == 401
    assert _row(pid).status == "pending"


def test_reject_expired_status_409_and_pending_past_expiry_200(client, api_key, seed):
    pid, _ = seed(status="expired")
    r = client.post(f"/proposals/{pid}/reject", headers=_api(api_key))
    assert (r.status_code, r.json()["detail"]) == (409, "Proposal already expired")
    pid, _ = seed(expires_delta=timedelta(minutes=-1))
    r = client.post(f"/proposals/{pid}/reject", headers=_api(api_key))
    assert r.status_code == 200 and r.json()["status"] == "rejected"


_STATUS_ATTR = re.compile(r"\.status\s*=(?!=)")
_STATUS_SQL = re.compile(r"\bSET\s+status\b", re.IGNORECASE)
_STATUS_VALUES = re.compile(r"values\([^)]*\bstatus\s*=")


def test_transition_grep_no_status_writes_outside_proposals_module():
    backend = Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend)
        if rel.parts[0] in ("tests", "tests_live_audit") or rel == Path("proposals.py"):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if _STATUS_ATTR.search(line) or _STATUS_SQL.search(line) or _STATUS_VALUES.search(line):
                offenders.append(f"{rel}:{n}")
    assert offenders == []
    assert any(_STATUS_ATTR.search(l) for l in (backend / "proposals.py").read_text().splitlines())


# ---------------------------------------------------------------------------
# Lazy-expiry reads, approver-only code, counts (APPR-02; D-11, D-19..D-21, D-25)
# ---------------------------------------------------------------------------

CODE = "ABCD-EF12"


def _has_key(obj, names) -> bool:
    if isinstance(obj, dict):
        return any(k in names or _has_key(v, names) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_has_key(v, names) for v in obj)
    return False


def test_expired_never_reads_pending(client, seed):
    pid, _ = seed(expires_delta=timedelta(minutes=-1))
    r = client.get("/proposals?status=pending")
    assert r.status_code == 200
    assert pid not in [p["id"] for p in r.json()]
    row = _row(pid)
    assert row.status == "expired" and row.status_changed_at >= row.created_at
    r = client.get("/proposals?status=expired")
    assert [p["status"] for p in r.json() if p["id"] == pid] == ["expired"]


def test_expired_flip_then_confirm_410(client, api_key, seed):
    pid, tok = seed(expires_delta=timedelta(minutes=-1))
    client.get("/proposals")
    r = client.post(f"/proposals/{pid}/confirm", json={"token": tok}, headers=_api(api_key))
    assert (r.status_code, r.json()["detail"]) == (410, EXPIRED_MSG)


def test_counts_returns_pending_after_lazy_expiry(client, seed):
    r = client.get("/proposals/counts")
    assert r.status_code == 200 and set(r.json()) == {"pending"}
    base = r.json()["pending"]
    seed()
    seed(channel="mcp", expires_delta=timedelta(hours=48))
    seed(expires_delta=timedelta(minutes=-1))
    r = client.get("/proposals/counts")
    assert set(r.json()) == {"pending"} and r.json()["pending"] == base + 2


def test_code_visibility_list_requires_approver_and_mcp(client, api_key, approver_key, seed, monkeypatch):
    import backend.auth as auth

    mcp_id, _ = seed(channel="mcp", expires_delta=timedelta(hours=48), code=CODE)
    chat_id, _ = seed()

    r = client.get("/proposals")
    assert r.status_code == 200 and not _has_key(r.json(), {"code", "token"})
    assert CODE not in r.text

    r = client.get("/proposals", headers=_appr(approver_key))
    items = {p["id"]: p for p in r.json()}
    assert items[mcp_id]["code"] == CODE
    assert "code" not in items[chat_id]
    assert not _has_key(r.json(), {"token"})

    r = client.get("/proposals", headers=_appr("wrong"))
    assert r.status_code == 200 and not _has_key(r.json(), {"code"})

    monkeypatch.setattr(auth, "_CONFIGURED_APPROVER_KEY", api_key)
    r = client.get("/proposals", headers=_appr(api_key))
    assert r.status_code == 200 and not _has_key(r.json(), {"code"})


def test_code_visibility_never_in_action_responses(client, api_key, approver_key, seed):
    a, _ = seed(channel="mcp", expires_delta=timedelta(hours=48), code=CODE)
    b, _ = seed(channel="mcp", expires_delta=timedelta(hours=48), code=CODE)
    c, tok = seed(channel="mcp", expires_delta=timedelta(hours=48), code=CODE)
    for r in (
        client.post(f"/proposals/{a}/approve", headers=_appr(approver_key)),
        client.post(f"/proposals/{b}/reject", headers=_appr(approver_key)),
    ):
        assert r.status_code == 200
        assert "code" not in r.json() and CODE not in r.text
    r = client.post(f"/proposals/{c}/confirm", json={"token": tok}, headers=_api(api_key))
    assert r.status_code == 403 and CODE not in r.text


# ---------------------------------------------------------------------------
# QA-01: transition() stays the only writer of proposal status (D-09)
# ---------------------------------------------------------------------------

def test_transition_is_the_only_status_writer_and_allows_superseded():
    import re
    from pathlib import Path

    from backend.proposals import transition

    p = _fake()
    transition(p, "superseded")
    assert p.status == "superseded"

    assign = re.compile(r"\.status\s*=(?!=)")
    set_sql = re.compile(r"SET\s+status\b", re.I)
    assigns, sqls = [], []
    for f in Path(__file__).resolve().parent.parent.glob("*.py"):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if assign.search(line):
                assigns.append((f.name, line.strip()))
            if set_sql.search(line):
                sqls.append((f.name, n))
    assert assigns == [("proposals.py", "proposal.status = new_status")]
    assert [f for f, _ in sqls] == ["proposals.py"]
