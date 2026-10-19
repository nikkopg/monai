"""
Skill routes (Phase 40): list, view and switch the owner's SKILL.md packs.

All three routes sit behind require_api_key. A request `name` is matched against
the scan listing and never joined into a path. Enabling echoes the hash the owner
viewed (A-02): a file edited after the panel opened answers 409, so approval
always binds to the exact text that was seen. Every toggle writes an audit row in
the same commit as the setting.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend import skills
from backend.auth import require_api_key
from backend.db import get_session
from backend.models import AppSetting, AuditLog

router = APIRouter()


class SkillToggle(BaseModel):
    enabled: bool
    hash: str | None = None


def _find(name: str) -> skills.Skill:
    s = next((x for x in skills.scan() if x.name == name), None)
    if s is None:
        raise HTTPException(404, "No such skill")
    return s


@router.get("/skills", dependencies=[Depends(require_api_key)])
def list_skills(db: Session = Depends(get_session)):
    enabled = skills.read_enabled(db)
    return [
        {
            "name": s.name,
            "description": s.description,
            "valid": s.valid,
            "reason": s.reason,
            "enabled": s.name in enabled,
            "changed": s.name in enabled and enabled[s.name] != s.hash,
            "declares_allowed_tools": s.allowed_tools,
        }
        for s in skills.scan()
    ]


@router.get("/skills/{name}", dependencies=[Depends(require_api_key)])
def get_skill(name: str):
    s = _find(name)
    if not s.valid:
        raise HTTPException(422, s.reason)
    try:
        return skills.detail(s)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.put("/skills/{name}", dependencies=[Depends(require_api_key)])
def put_skill(name: str, body: SkillToggle, db: Session = Depends(get_session)):
    s = _find(name)
    cur = dict(skills.read_enabled(db))
    prior = cur.get(name)
    if body.enabled:
        if not s.valid:
            raise HTTPException(422, s.reason)
        if body.hash != s.hash:
            raise HTTPException(409, "This skill changed after you opened it. Review it again.")
        cur[name] = s.hash
    else:
        cur.pop(name, None)
    row = db.get(AppSetting, skills.KEY_SKILLS_ENABLED) or AppSetting(key=skills.KEY_SKILLS_ENABLED)
    row.value = cur  # a new dict: in-place JSONB mutation is not tracked
    row.updated_at = datetime.now(timezone.utc)
    db.merge(row)
    db.add(AuditLog(entity="skill", entity_id=None, operation="enable" if body.enabled else "disable",
                    before={"enabled": prior is not None, "hash": prior},
                    after={"name": name, "enabled": body.enabled, "hash": cur.get(name)}))
    db.commit()  # one transaction: setting + audit row
    return {"name": name, "enabled": body.enabled}
