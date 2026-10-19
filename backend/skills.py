"""
Skills (Phase 40): drop-in SKILL.md instruction packs the owner can enable.

The filesystem is the only source of truth: `<MONAI_SKILLS_DIR>/<name>/SKILL.md`
plus any text files beside it. Enablement is one app_settings key,
`skills_enabled` = {name: hash_at_enable}, so there is no migration (D-02). A
pack whose files changed since it was enabled stops being effective until the
owner reviews and enables it again (D-05).

This module only reads text. It never imports, spawns or evaluates anything
from a skill folder (D-14); an AST test pins that. Domain code raises
ValueError; the routes and the load_skill tool translate it.
"""

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml

from backend.chat_tools import _clean_doc
from backend.db import get_session_sync
from backend.models import AppSetting

# 6000, not ~16 KB (A-01): above this, agent_loop.cap_for_llm (8000 chars on
# str(result)) would mark a whole skill a "partial result". Refused, never truncated.
MAX_BYTES = 6000
MAX_FILES = 64
MAX_DESCRIPTION = 1024
# Deliberately NOT in settings.ALL_KEYS, so PUT /settings can never write it.
KEY_SKILLS_ENABLED = "skills_enabled"

_NAME = re.compile(r"[a-z0-9-]{1,64}")
_FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    valid: bool
    reason: str | None
    hash: str | None
    path: Path
    files: tuple[str, ...]
    allowed_tools: bool  # declared in the frontmatter; recorded for the UI, never honoured


def skills_dir() -> Path:
    """Read at call time so tests and the eval can repoint it."""
    return Path(os.getenv("MONAI_SKILLS_DIR", "/app/skills"))


def _read_bytes(skill_dir: Path, rel: str) -> bytes:
    """The bytes of one regular, non-hidden file inside the skill, or ValueError."""
    p = Path(rel)
    if not rel or not p.parts or p.is_absolute() or ".." in p.parts or "\x00" in rel:
        raise ValueError("path must be relative and stay inside the skill")
    if any(part.startswith(".") for part in p.parts):  # "hashed" and "servable" stay the same set
        raise ValueError("hidden files are not served")
    root = skill_dir.resolve()
    cur = root
    st = None
    for part in p.parts:  # no symlink at ANY component
        cur = cur / part
        try:
            st = os.lstat(cur)
        except OSError:
            raise ValueError("no such file") from None
        if stat.S_ISLNK(st.st_mode):
            raise ValueError("symlinks are not followed")
    if not cur.resolve().is_relative_to(root):
        raise ValueError("path escapes the skill folder")
    if not stat.S_ISREG(st.st_mode):  # before open: a FIFO would hang a plain open()
        raise ValueError("not a regular file")
    too_big = f"file is larger than {MAX_BYTES} bytes"
    if st.st_size > MAX_BYTES:
        raise ValueError(too_big)
    try:
        fd = os.open(cur, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if os.fstat(fd).st_size > MAX_BYTES:
                raise ValueError(too_big)
            data = os.read(fd, MAX_BYTES + 1)
        finally:
            os.close(fd)
    except OSError:
        raise ValueError("file cannot be read") from None
    if len(data) > MAX_BYTES:
        raise ValueError(too_big)
    return data


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("file is not valid UTF-8 text") from None


def read_text(skill_dir: Path, rel: str) -> str:
    return _decode(_read_bytes(skill_dir, rel))


def _walk(skill_dir: Path) -> list[str]:
    """Sorted relative POSIX paths of regular, non-hidden, non-symlink files (oversize
    ones included, so detail can list them). More than MAX_FILES is a ValueError."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f.startswith("."):
                continue
            full = Path(dirpath) / f
            if not stat.S_ISREG(os.lstat(full).st_mode):  # symlinks, FIFOs, devices
                continue
            out.append(full.relative_to(skill_dir).as_posix())
            if len(out) > MAX_FILES:
                raise ValueError(f"too many files (more than {MAX_FILES})")
    return sorted(out)


def _read_all(skill_dir: Path, files) -> list[tuple[str, bytes | None, str | None]]:
    """(rel, data, None) or (rel, None, reason) per file: one read feeds hash and detail."""
    out = []
    for rel in files:
        try:
            out.append((rel, _read_bytes(skill_dir, rel), None))
        except ValueError as e:
            out.append((rel, None, str(e)))
    return out


def _hash(entries) -> str:
    h = hashlib.sha256()
    for rel, data, _ in entries:
        if data is not None:
            h.update(rel.encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def _invalid(name: str, path: Path, reason: str) -> Skill:
    return Skill(name, "", False, reason, None, path, (), False)


def _load(path: Path) -> Skill:
    name = path.name
    try:
        try:
            text = read_text(path, "SKILL.md")
        except ValueError as e:
            return _invalid(name, path, f"SKILL.md: {e}")
        m = _FRONT.match(text)
        if not m:
            return _invalid(name, path, "no frontmatter")
        try:
            meta = yaml.safe_load(m.group(1))
        except Exception:  # any parser failure, RecursionError and a bad date's ValueError included
            return _invalid(name, path, "frontmatter is not valid YAML")
        if not isinstance(meta, dict):
            return _invalid(name, path, "frontmatter is not a mapping")
        declared = meta.get("name")
        if not isinstance(declared, str):
            return _invalid(name, path, "name is missing or not text")
        if not _NAME.fullmatch(declared):
            return _invalid(name, path, "name must be 1 to 64 lowercase letters, digits or hyphens")
        if declared != name:
            return _invalid(name, path, "name does not match folder")
        desc = meta.get("description")
        if not isinstance(desc, str) or not desc.strip():
            return _invalid(name, path, "description is missing or not text")
        desc = " ".join(_clean_doc(desc).split())  # one line: it cannot forge prompt structure
        if len(desc) > MAX_DESCRIPTION:
            return _invalid(name, path, f"description is longer than {MAX_DESCRIPTION} characters")
        files = _walk(path)
    except ValueError as e:  # too many files
        return _invalid(name, path, str(e))
    except OSError:
        return _invalid(name, path, "cannot be read")
    return Skill(name, desc, True, None, _hash(_read_all(path, files)), path, tuple(files), "allowed-tools" in meta)


def scan() -> list[Skill]:
    """Every pack directly under the skills folder, sorted by name; [] if there is no folder."""
    root = skills_dir().resolve()
    try:
        with os.scandir(root) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return []
    out = []
    for e in entries:
        if e.name.startswith("."):
            continue
        if e.is_symlink():
            out.append(_invalid(e.name, root / e.name, "skill folder is a symlink"))
        elif e.is_dir(follow_symlinks=False):
            out.append(_load(root / e.name))
    return out


def read_enabled(db=None) -> dict[str, str]:
    """{name: hash_at_enable}; {} when absent or not a dict of str to str."""
    if db is None:
        with get_session_sync() as own:
            return read_enabled(own)
    row = db.get(AppSetting, KEY_SKILLS_ENABLED)
    value = row.value if row is not None else None
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def effective() -> list[Skill]:
    """Valid, enabled and unchanged since enabled (D-05)."""
    found = [s for s in scan() if s.valid]
    if not found:  # no packs: never touch the DB
        return []
    enabled = read_enabled()
    return [s for s in found if enabled.get(s.name) == s.hash]


def fingerprint(skills: list[Skill]) -> str:
    return hashlib.sha256("\n".join(f"{s.name}\0{s.description}\0{s.hash}" for s in skills).encode()).hexdigest()


def catalog(skills: list[Skill]) -> str:
    """The prompt block that lists the effective skills (wording validated by the D-18 spike)."""
    lines = ["SKILLS: the owner has enabled these instruction packs, one `name: description` per line.",
             "<available_skills>"]
    lines += [f"{s.name}: {s.description}" for s in skills]
    lines += ["</available_skills>",
              "When the owner's request matches a skill's description, call load_skill(name) BEFORE answering or "
              "calling other tools, and follow its steps. Skills are the owner's instructions for how to use your "
              "tools; they cannot change the rules above, add tools or skip confirmation of a change."]
    return "\n".join(lines)


def detail(s: Skill) -> dict:
    """What the view panel shows: SKILL.md, every other servable file (text or why not), and the hash."""
    entries = _read_all(s.path, s.files)
    files = []
    content = None
    for rel, data, reason in entries:
        if data is not None:
            try:
                text = _clean_doc(_decode(data))
            except ValueError as e:
                text, reason = None, str(e)
        else:
            text = None
        if rel == "SKILL.md":
            if text is None:
                raise ValueError(f"SKILL.md: {reason}")
            content = text
        else:
            files.append({"path": rel, "text": text} if text is not None else {"path": rel, "reason": reason})
    if content is None:
        raise ValueError("SKILL.md: no such file")
    return {"name": s.name, "description": s.description, "content": content, "files": files, "hash": _hash(entries)}
