"""
Backend configuration — database URL and LLM provider.

Env vars:
  DATABASE_URL    (default: postgresql+psycopg://monai:monai@localhost:5434/monai)
  LLM_PROVIDER    ollama (default) | claude | openai
  OLLAMA_MODEL        (default: gemma4:31b-cloud)
  OLLAMA_EMBED_MODEL  (default: gemma4:31b-cloud)
  OLLAMA_BASE_URL     (default: http://localhost:11434)
  CLAUDE_MODEL        (default: claude-haiku-4-5-20251001)
  OPENAI_MODEL        (default: gpt-4o-mini)
"""

import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://monai:monai@localhost:5434/monai",
)


def configure_llm(overrides: dict | None = None) -> None:
    """Set LlamaIndex Settings.llm + embed_model from LLM_PROVIDER.

    overrides: optional dict (e.g. backend.settings.get_effective_settings(db,
    raw_keys=True)) whose values take precedence over the os.getenv() defaults
    below. Keys consulted: llm_provider, llm_model, anthropic_api_key,
    openai_api_key. Passing None (or omitting the argument) preserves the
    original env-var-only behavior — the zero-arg call in query.py's
    _get_llm() keeps working unchanged.
    """
    from llama_index.core import Settings

    overrides = overrides or {}

    provider = (overrides.get("llm_provider") or os.getenv("LLM_PROVIDER", "ollama")).lower()

    if provider == "ollama":
        from llama_index.llms.ollama import Ollama
        from llama_index.embeddings.ollama import OllamaEmbedding
        model = overrides.get("llm_model") or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        embed_model = os.getenv("OLLAMA_EMBED_MODEL", "gemma4:31b-cloud")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        Settings.llm = Ollama(model=model, base_url=base_url, request_timeout=120.0)
        Settings.embed_model = OllamaEmbedding(model_name=embed_model, base_url=base_url)

    elif provider == "claude":
        from llama_index.llms.anthropic import Anthropic
        Settings.embed_model = "local"
        model = overrides.get("llm_model") or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        api_key = overrides.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY")
        Settings.llm = Anthropic(model=model, api_key=api_key)

    elif provider == "openai":
        from llama_index.llms.openai import OpenAI
        from llama_index.embeddings.openai import OpenAIEmbedding
        model = overrides.get("llm_model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = overrides.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
        Settings.llm = OpenAI(model=model, api_key=api_key)
        Settings.embed_model = OpenAIEmbedding(api_key=api_key)

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER={provider!r}. Valid: ollama, claude, openai"
        )
