"""Phase 39 locality rule (D-14, D-14a): where would a file go? Synthetic values only."""
import pytest

from backend import settings
from backend.attachments import current_locality, locality

LOCAL = {"local": True, "destination": None}


def cloud(dest):
    return {"local": False, "destination": dest}


@pytest.mark.parametrize(
    "provider,model,url,want",
    [
        ("ollama", "gemma4:31b-cloud", "http://localhost:11434", cloud("Ollama Cloud (gemma4:31b-cloud)")),
        ("ollama", "gemma4:cloud", "http://127.0.0.1:11434", cloud("Ollama Cloud (gemma4:cloud)")),
        ("ollama", "gemma4:31b", "http://localhost:11434", LOCAL),
        ("ollama", "gemma4:31b", "http://[::1]:11434", LOCAL),
        ("ollama", "gemma4:31b", "http://host.docker.internal:11434", LOCAL),
        ("ollama", "gemma4:31b", "https://ollama.com", cloud("Ollama at ollama.com (gemma4:31b)")),
        ("ollama", "gemma4:31b", "http://192.168.1.20:11434", cloud("Ollama at 192.168.1.20 (gemma4:31b)")),
        ("ollama", "gemma4:31b", "localhost:11434", LOCAL),
    ],
)
def test_locality(provider, model, url, want):
    assert locality(provider, model, url) == want


def test_default_config_is_not_local(monkeypatch):
    for var in ("OLLAMA_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "get_effective_settings", lambda db: {"llm_model": "gemma4:31b-cloud"})
    assert current_locality(None) == cloud("Ollama Cloud (gemma4:31b-cloud)")
