"""
Pure per-turn agent-loop helpers (Phase 38).

No LlamaIndex import at module level (query.py and main.py load at startup,
llama stays lazy); later plans add the result cap and the tail reminder here.

tools_for_turn decides, in code and with no extra LLM call, which tools a turn
carries: the 18 reads always, the 16 propose_* writes only when the turn shows
write intent (LOOP-01). A smaller tool block is cheaper on every iteration and
the small default model picks from a shorter list more reliably.
"""

import re

# D-04 list, finalised from the eval questions. Biased towards false positives:
# an extra proposer on a read turn is harmless (it still needs the owner's
# confirm), a missing one makes the model refuse.
# Indonesian stems confirmed by the owner on 2026-10-17 (RESEARCH A3).
WRITE_RE = re.compile(
    r"\b(?:add|record|log|create|edit|change|fix|update|correct|delete|remove|rename|merge|move|"
    r"transfer|buy|bought|sell|sold|adjust|assign|reassign|(?:re)?categori[sz]e|reclassify|"
    r"deposit|withdraw|top[ -]?up)\b"
    r"|\b(?:tambah|catat|masukkan|buat|ubah|ganti|koreksi|perbaiki|hapus|buang|pindah|beli|jual|"
    r"sesuaikan|gabung|kategorikan)\w*",
    re.I,
)

_QUESTION_RE = re.compile(r"[^.?!\n]*\?")


def tools_for_turn(question: str, prior: list[dict] | None = None) -> frozenset[str]:
    """Tool names for one turn: READ_TOOL_NAMES, or every tool on write intent.

    `prior` is the thread's message dicts (the build_history input). Write
    intent is sticky from the last complete pair, so "yes, do that" after a
    proposal or an offer keeps the writes (D-04, D-04a). This is the seam
    Phases 39 and 41 extend by unioning their own names into the result.
    """
    from backend.chat_history import _pairs
    from backend.tools import READ_TOOL_NAMES, TOOLS

    sticky = False
    last = None
    for last in _pairs(prior or []):
        pass
    if last is not None:
        u, a = last
        parts = a.get("parts") or {}
        offered = any(WRITE_RE.search(s) for s in _QUESTION_RE.findall(a["content"] or ""))
        sticky = bool(
            WRITE_RE.search(u["content"] or "")
            or offered
            or parts.get("proposals")
            or any(str(s.get("tool", "")).startswith("propose_") for s in parts.get("steps") or [])
        )
    if sticky or WRITE_RE.search(question or ""):
        return frozenset(TOOLS)
    return READ_TOOL_NAMES
