# monai

Personal wealth intelligence layer. Self-hosted, AI-queryable, yours.

## What it is

A self-hosted app that combines your **spending history** and **investment holdings** in one place, with a conversational AI layer over all of it.

Not a budgeting app. Not another Mint clone. The gap this fills: every self-hosted finance tool does one thing — Actual Budget does spending, Ghostfolio does investments. None of them talk to each other, and none have a natural language query layer. monai is the bridge.

**What you can ask it:**
- "How much did I spend on food in April 2024?"
- "You bought NVDA in March — since then you've spent 40% more on eating out. Correlation or celebration?"
- "Which subscriptions did I stop using 3 months before I cancelled them?"

## Status

🚧 Early development — not usable yet.

- [ ] v1 — spending import + AI query (Weeks 1–6)
- [ ] v1.1 — investment holdings + portfolio+spending correlation queries (Weeks 7–12)
- [ ] v2 — open source release (TBD)

## Architecture (planned)

**Proof of concept (current focus):**
- Python + SQLite
- LlamaIndex `NLSQLTableQueryEngine` for natural language queries
- Ollama (local) or Claude API via `LLM_PROVIDER` env var
- Streamlit chat UI

**Production (Approach C):**
- Python FastAPI + PostgreSQL
- LlamaIndex + custom `FunctionTool` wrappers for correlation queries
- Next.js frontend
- Docker Compose — single `docker compose up` to run

## Getting started

> Not ready yet. Check back once the PoC is working.

## Privacy

All data stays on your machine. AI inference runs locally via Ollama by default. Cloud API (Claude/OpenAI) only activates if you explicitly set `LLM_PROVIDER=claude` or `LLM_PROVIDER=openai`.

## Data safety

- SQLite WAL mode enabled
- Daily backup: `cp monai.db monai.db.$(date +%Y%m%d).bak`

## Migration

Built with migration from mobile money apps (Spendee, Wallet, Money Lover) as a Day 1 requirement. Import pipeline TBD — export format determines architecture.

## License

MIT
