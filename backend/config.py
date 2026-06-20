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


def configure_llm() -> None:
    """Set LlamaIndex Settings.llm + embed_model from LLM_PROVIDER."""
    from llama_index.core import Settings

    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from llama_index.llms.ollama import Ollama
        from llama_index.embeddings.ollama import OllamaEmbedding
        model = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        embed_model = os.getenv("OLLAMA_EMBED_MODEL", "gemma4:31b-cloud")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        Settings.llm = Ollama(model=model, base_url=base_url, request_timeout=120.0)
        Settings.embed_model = OllamaEmbedding(model_name=embed_model, base_url=base_url)

    elif provider == "claude":
        from llama_index.llms.anthropic import Anthropic
        Settings.embed_model = "local"
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
            f"Unknown LLM_PROVIDER={provider!r}. Valid: ollama, claude, openai"
        )
