"""
LLM provider configuration.

Set LLM_PROVIDER env var to select the backend:
  LLM_PROVIDER=ollama   (default) — local Ollama, no data sent to cloud
  LLM_PROVIDER=claude   — Anthropic Claude API (requires ANTHROPIC_API_KEY)
  LLM_PROVIDER=openai   — OpenAI API (requires OPENAI_API_KEY)

Model overrides:
  OLLAMA_MODEL   (default: gemma4:31b-cloud)
  CLAUDE_MODEL   (default: claude-haiku-4-5-20251001)
  OPENAI_MODEL   (default: gpt-4o-mini)
"""

import os
from llama_index.core import Settings


def configure_llm() -> None:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from llama_index.llms.ollama import Ollama
        from llama_index.embeddings.ollama import OllamaEmbedding
        model = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        embed_model = os.getenv("OLLAMA_EMBED_MODEL", "gemma4:31b-cloud")
        Settings.llm = Ollama(model=model, request_timeout=120.0)
        Settings.embed_model = OllamaEmbedding(model_name=embed_model)

    elif provider == "claude":
        from llama_index.llms.anthropic import Anthropic
        from llama_index.core import Settings as S
        # Claude has no embedding API — use a local model
        S.embed_model = "local"
        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        Settings.llm = Anthropic(model=model)

    elif provider == "openai":
        from llama_index.llms.openai import OpenAI
        from llama_index.embeddings.openai import OpenAIEmbedding
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        Settings.llm = OpenAI(model=model)
        Settings.embed_model = OpenAIEmbedding()

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER={provider!r}. "
            "Valid values: ollama, claude, openai"
        )
