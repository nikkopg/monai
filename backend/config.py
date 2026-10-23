"""
Backend configuration — database URL and LLM provider.

Env vars:
  DATABASE_URL    (default: postgresql+psycopg://monai:$POSTGRES_PASSWORD@localhost:5434/monai;
                  falls back to the dev default when POSTGRES_PASSWORD is unset)
  LLM_PROVIDER    ollama (default) | claude | openai
  OLLAMA_MODEL        (default: gemma4:31b-cloud)
  OLLAMA_EMBED_MODEL  (default: gemma4:31b-cloud)
  OLLAMA_BASE_URL     (default: http://localhost:11434)
  CLAUDE_MODEL        (default: claude-haiku-4-5-20251001)
  OPENAI_MODEL        (default: gpt-4o-mini)
  CHAT_IDLE_TIMEOUT_SECONDS  (default: 120) — chat run with no workflow event for
                      this long is cancelled with error idle_timeout. 120, not
                      90, to match Ollama's per-read request_timeout=120 (D-14a).
                      The watchdog starts slightly before the provider's read,
                      so on a fully hung call idle_timeout still fires first and
                      the provider's own timeout code is not reached; set this
                      above 120 if that code matters.
  CHAT_HISTORY_TOKEN_BUDGET  (default: 6000) — caps replayed chat history
                      (chars/4 estimate, newest turns kept, whole pairs only).
  OLLAMA_NUM_CTX      (default: 32768) — sent as options.num_ctx instead of
                      letting Ollama default to the model's maximum. Whether a
                      cloud model honours it is unverified (assumption A1,
                      retuned by the Phase 38 spike).
  MONAI_SKILLS_DIR    (default: /app/skills) — folder of SKILL.md packs, read at call
                      time by backend/skills.py.
  EXT_CONNECT_TIMEOUT_SECONDS  (default: 20) — connect and initialize limit for an
                      external MCP server (Phase 41).
  EXT_CALL_TIMEOUT_SECONDS  (default: 60) — limit for one external tool call.
  EXT_APPROVAL_TTL_SECONDS  (default: 600) — how long an external call waits for
                      the owner's decision before it counts as expired.
  MONAI_EXT_HOME      (default: ~/.cache/monai-ext) — home, tmp and npm/uv caches
                      for stdio MCP servers; the image sets /var/lib/monai-ext.
"""

import os
from urllib.parse import quote

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg://monai:{quote(os.environ.get('POSTGRES_PASSWORD') or 'monai', safe='')}@localhost:5434/monai",
)

# float so "90.5" parses; floored at 1 s so 0 or a negative cannot end every run at once.
CHAT_IDLE_TIMEOUT_SECONDS = max(1.0, float(os.getenv("CHAT_IDLE_TIMEOUT_SECONDS", "120")))

# Floored at 1 s, like the idle timeout.
EXT_CONNECT_TIMEOUT_SECONDS = max(1.0, float(os.getenv("EXT_CONNECT_TIMEOUT_SECONDS", "20")))
EXT_CALL_TIMEOUT_SECONDS = max(1.0, float(os.getenv("EXT_CALL_TIMEOUT_SECONDS", "60")))
EXT_APPROVAL_TTL_SECONDS = max(1.0, float(os.getenv("EXT_APPROVAL_TTL_SECONDS", "600")))
MONAI_EXT_HOME = os.getenv("MONAI_EXT_HOME", os.path.expanduser("~/.cache/monai-ext"))

# 0 disables replayed history; negatives clamp to 0.
CHAT_HISTORY_TOKEN_BUDGET = max(0, int(os.getenv("CHAT_HISTORY_TOKEN_BUDGET", "6000")))
# Floor 2048 so a typo cannot starve the model of context.
OLLAMA_NUM_CTX = max(2048, int(os.getenv("OLLAMA_NUM_CTX", "32768")))


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
        Settings.llm = Ollama(
            model=model, base_url=base_url, request_timeout=120.0,
            context_window=OLLAMA_NUM_CTX,
        )
        Settings.embed_model = OllamaEmbedding(model_name=embed_model, base_url=base_url)

    elif provider == "claude":
        from llama_index.llms.anthropic import Anthropic
        from llama_index.core.embeddings import MockEmbedding
        # Claude has no embeddings API and no embedding-based retrieval is used
        # by this app's tool-router agent (D-06 preserved); MockEmbedding avoids
        # requiring an extra llama-index-embeddings-* package or an OpenAI key
        # just to satisfy the Settings.embed_model singleton.
        Settings.embed_model = MockEmbedding(embed_dim=1)
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
