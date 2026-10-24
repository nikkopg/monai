"""
Env settings for chat context (D-15, D-15a).

Tests:
  test_env_defaults_and_floors — OLLAMA_NUM_CTX / CHAT_HISTORY_TOKEN_BUDGET defaults and floors
  test_ollama_gets_explicit_num_ctx — configure_llm builds Ollama with context_window
"""

import os
import subprocess
import sys
from pathlib import Path

from llama_index.core import Settings

from backend import config

ROOT = Path(__file__).resolve().parents[2]
CODE = "import backend.config as c; print(c.OLLAMA_NUM_CTX, c.CHAT_HISTORY_TOKEN_BUDGET)"


def _run(extra: dict) -> str:
    env = {k: v for k, v in os.environ.items()
           if k not in ("OLLAMA_NUM_CTX", "CHAT_HISTORY_TOKEN_BUDGET")}
    env.update(extra)
    r = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_env_defaults_and_floors():
    assert _run({}) == "32768 6000"
    assert _run({"OLLAMA_NUM_CTX": "0", "CHAT_HISTORY_TOKEN_BUDGET": "-5"}) == "2048 0"


def test_ollama_gets_explicit_num_ctx(monkeypatch):
    monkeypatch.setattr(Settings, "_llm", Settings._llm)
    monkeypatch.setattr(Settings, "_embed_model", Settings._embed_model)
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 12345)
    config.configure_llm({"llm_provider": "ollama"})
    assert Settings.llm.context_window == 12345
    assert Settings.llm._model_kwargs["num_ctx"] == 12345
