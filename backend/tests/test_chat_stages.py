"""Quick 261122-cpg: _ollama_loaded decides whether Chat shows "loading the model…".

No Ollama is needed: ollama.AsyncClient is replaced with a fake whose ps() lists
the given model names (or raises).
"""
import asyncio
from types import SimpleNamespace

import ollama
import pytest
from llama_index.llms.ollama import Ollama

from backend.query import _ollama_loaded


def _fake_client(monkeypatch, listed=None, error=None):
    class Fake:
        def __init__(self, host=None):
            pass

        async def ps(self):
            if error:
                raise error
            return SimpleNamespace(models=[SimpleNamespace(model=m) for m in listed])

    monkeypatch.setattr(ollama, "AsyncClient", Fake)


def _run(llm):
    return asyncio.run(_ollama_loaded(llm))


@pytest.mark.parametrize("listed, model, expected", [
    (["gemma4:e2b"], "gemma4:e2b", True),
    (["qwen3.5:0.8b"], "gemma4:e2b", False),
    ([], "gemma4:e2b", False),
    (["gemma4:latest"], "gemma4", True),  # an untagged name is :latest
    (["hf.co/Org/Model-GGUF:Q4_K_M"], "hf.co/Org/Model-GGUF:Q4_K_M", True),
])
def test_listed_or_not(monkeypatch, listed, model, expected):
    _fake_client(monkeypatch, listed=listed)
    assert _run(Ollama(model=model)) is expected


def test_unknown_cases_show_no_loading_stage(monkeypatch):
    _fake_client(monkeypatch, listed=[])
    assert _run(Ollama(model="gemma4:31b-cloud")) is None  # cloud: never in /api/ps
    assert _run(SimpleNamespace(model="claude-haiku")) is None  # not Ollama
    _fake_client(monkeypatch, error=ConnectionError("down"))
    assert _run(Ollama(model="gemma4:e2b")) is None  # no answer


async def test_cold_model_loads_before_the_run(monkeypatch):
    """A model not in memory: a loading step, the load, then the run's thinking step."""
    import backend.query as q
    from backend.tests.chat_stubs import StubLLM, _collect, _install_stub_workflow, _payloads

    order = []

    async def not_loaded(llm):
        return False

    async def load(llm):
        order.append("load")

    monkeypatch.setattr(q, "_ollama_loaded", not_loaded)
    monkeypatch.setattr(q, "_ollama_load", load)
    _install_stub_workflow(monkeypatch, StubLLM())

    payloads = _payloads(await _collect(q.agent_stream("synthetic question")))
    steps = [p.get("stage") for p in payloads if p.get("type") == "step"]
    assert steps[:2] == ["loading", "thinking"], payloads
    assert order == ["load"]
    assert [p["type"] for p in payloads][-1] == "answer"
