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
