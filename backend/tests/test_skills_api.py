"""Phase 40 /skills routes; synthetic packs under tmp_path; monai_test only."""
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend import skills
from backend.db import SessionLocal

ALPHA = "---\nname: zzeval-alpha\ndescription: Use when the owner asks for the zzeval review.\n---\nLook around.\n"


def _purge():
    with SessionLocal() as db:
        db.execute(text("DELETE FROM app_settings WHERE key = 'skills_enabled'"))
        db.execute(text("DELETE FROM audit_log WHERE entity = 'skill' AND after->>'name' LIKE 'zzeval-%'"))
        db.commit()


@pytest.fixture()
def env(client, api_key, tmp_path, monkeypatch):
    monkeypatch.setenv("MONAI_SKILLS_DIR", str(tmp_path))
    alpha = tmp_path / "zzeval-alpha"
    (alpha / "references").mkdir(parents=True)
    (alpha / "SKILL.md").write_text(ALPHA)
    (alpha / "references" / "format.md").write_text("Format: plain.")
    (tmp_path / "zzeval-broken").mkdir()
    (tmp_path / "zzeval-broken" / "SKILL.md").write_text("no frontmatter here\n")
    _purge()
    yield SimpleNamespace(client=client, h={"MONAI_API_KEY": api_key}, alpha=alpha)
    _purge()


def _audit():
    with SessionLocal() as db:
        return db.execute(text(
            "SELECT operation, before, after FROM audit_log WHERE entity = 'skill' AND after->>'name' LIKE 'zzeval-%' "
            "ORDER BY id")).all()


def _stored():
    with SessionLocal() as db:
        return db.execute(text("SELECT value FROM app_settings WHERE key = 'skills_enabled'")).scalar()


def _listed(env):
    return {s["name"]: s for s in env.client.get("/skills", headers=env.h).json()}


def _enable(env, name="zzeval-alpha", **body):
    return env.client.put(f"/skills/{name}", json={"enabled": True, **body}, headers=env.h)


def test_skill_routes_need_the_api_key(env):
    assert env.client.get("/skills").status_code == 401
    assert env.client.get("/skills/zzeval-alpha").status_code == 401
    assert env.client.put("/skills/zzeval-alpha", json={"enabled": False}).status_code == 401


def test_list_shows_packs_off_by_default(env):
    r = env.client.get("/skills", headers=env.h)
    assert r.status_code == 200
    rows = r.json()
    assert [s["name"] for s in rows] == ["zzeval-alpha", "zzeval-broken"]
    assert rows[0] == {"name": "zzeval-alpha", "description": "Use when the owner asks for the zzeval review.",
                       "valid": True, "reason": None, "enabled": False, "changed": False,
                       "declares_allowed_tools": False}
    assert (rows[1]["valid"], rows[1]["reason"], rows[1]["enabled"]) == (False, "no frontmatter", False)


def test_detail_returns_every_file_and_hash(env):
    r = env.client.get("/skills/zzeval-alpha", headers=env.h)
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == ALPHA
    assert body["files"] == [{"path": "references/format.md", "text": "Format: plain."}]
    assert re.fullmatch(r"[0-9a-f]{64}", body["hash"])


def test_detail_unknown_404_invalid_422(env):
    assert env.client.get("/skills/zzeval-nope", headers=env.h).status_code == 404
    r = env.client.get("/skills/zzeval-broken", headers=env.h)
    assert (r.status_code, r.json()["detail"]) == (422, "no frontmatter")


def test_enable_records_hash_and_audit(env):
    h = env.client.get("/skills/zzeval-alpha", headers=env.h).json()["hash"]
    r = _enable(env, hash=h)
    assert r.status_code == 200 and r.json() == {"name": "zzeval-alpha", "enabled": True}
    assert _stored() == {"zzeval-alpha": h}
    (op, before, after), = _audit()
    assert op == "enable" and before == {"enabled": False, "hash": None}
    assert after == {"name": "zzeval-alpha", "enabled": True, "hash": h}
    row = _listed(env)["zzeval-alpha"]
    assert (row["enabled"], row["changed"]) == (True, False)


def test_enable_stale_hash_409(env):
    h = env.client.get("/skills/zzeval-alpha", headers=env.h).json()["hash"]
    (env.alpha / "SKILL.md").write_text(ALPHA + "Sneaky edit.\n")
    assert _enable(env, hash=h).status_code == 409
    assert _enable(env).status_code == 409  # no hash at all
    assert _stored() is None and _audit() == []


def test_enable_invalid_422_unknown_404(env):
    assert _enable(env, "zzeval-broken", hash="x").status_code == 422
    assert _enable(env, "zzeval-nope", hash="x").status_code == 404
    assert _stored() is None and _audit() == []


def test_changed_since_enabled_is_flagged_and_suspended(env):
    h = env.client.get("/skills/zzeval-alpha", headers=env.h).json()["hash"]
    assert _enable(env, hash=h).status_code == 200
    assert [s.name for s in skills.effective()] == ["zzeval-alpha"]
    (env.alpha / "references" / "format.md").write_text("Format: changed.")
    row = _listed(env)["zzeval-alpha"]
    assert (row["enabled"], row["changed"]) == (True, True)
    assert skills.effective() == []


def test_disable_removes_and_audits(env):
    h = env.client.get("/skills/zzeval-alpha", headers=env.h).json()["hash"]
    _enable(env, hash=h)
    r = env.client.put("/skills/zzeval-alpha", json={"enabled": False}, headers=env.h)
    assert r.status_code == 200 and r.json() == {"name": "zzeval-alpha", "enabled": False}
    assert _stored() == {}
    assert [a[0] for a in _audit()] == ["enable", "disable"]
    after = _audit()[1][2]
    assert after == {"name": "zzeval-alpha", "enabled": False, "hash": None}
    assert _listed(env)["zzeval-alpha"]["enabled"] is False
