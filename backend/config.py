"""
Backend configuration — database URL and the Ollama LLM (the only provider).

Env vars:
  DATABASE_URL    (default: postgresql+psycopg://monai:$POSTGRES_PASSWORD@localhost:5434/monai;
                  falls back to the dev default when POSTGRES_PASSWORD is unset)
  OLLAMA_MODEL        (default: gemma4:31b-cloud)
  OLLAMA_EMBED_MODEL  (default: gemma4:31b-cloud)
  OLLAMA_BASE_URL     (default: http://localhost:11434)
  CHAT_IDLE_TIMEOUT_SECONDS  (default: 120) — chat run with no workflow event for
                      this long is cancelled with error idle_timeout (D-14a).
                      Below Ollama's per-read request_timeout=300, so on a fully
                      hung call idle_timeout fires first and the provider's own
                      timeout code is not reached.
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
    """Set LlamaIndex Settings.llm + embed_model to Ollama.

    overrides: optional dict (e.g. backend.settings.get_effective_settings(db))
    whose llm_model takes precedence over OLLAMA_MODEL. Passing None keeps the
    env-var-only behavior.
    """
    from llama_index.core import Settings
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.llms.ollama import Ollama

    overrides = overrides or {}
    model = overrides.get("llm_model") or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "gemma4:31b-cloud")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    Settings.llm = Ollama(
        # Above attachments.VISION_TIMEOUT, or this fires first and cuts the vision
        # read short (261124-vto). Chat and compaction have the idle guard.
        model=model, base_url=base_url, request_timeout=300.0,
        context_window=OLLAMA_NUM_CTX,
        # Thinking off: on the local iGPU, gemma4:e2b ran the agent eval
        # 3x faster (17.5 vs 53 min) at the same score (15 vs 14 of 26).
        thinking=False,
    )
    Settings.embed_model = OllamaEmbedding(model_name=embed_model, base_url=base_url)
