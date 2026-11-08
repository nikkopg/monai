# monai

Your spending and investments in one place, with an assistant you can ask about them in plain language. It runs on your own machine, and nothing leaves it unless you choose a cloud model.

Two rules hold everywhere:

- **It never makes up a number.** Every figure comes from a fixed set of tested calculations, never from the model's own maths.
- **It never changes your data without asking.** Every change waits for you to approve it, and every change is logged.

## Features

- **Chat.** Ask things like "How much did I spend on food last month?" or "Add a grocery expense for yesterday." Answers stream in, link to the records behind each number, and conversations are saved. Attach a CSV, PDF statement or receipt to ask about it or import its rows.
- **Rupiah and dollar accounts.** Each account is IDR or USD, and every total converts to rupiah at the right day's rate.
- **Cashflow and records.** Net worth over time, spending by category, income against expenses, and every transaction with filters and bulk edits.
- **Investments.** Holdings across platforms with live prices and profit and loss. Buys and sells come from one of your accounts and can include the fee, and a sold-out position keeps its profit or loss as a record.
- **Inbox.** Every change waiting for your approval, from chat or from other apps, with likely duplicates flagged.
- **Works with Claude and other AI apps.** They can read your data and suggest changes, which still wait for your approval. You can also connect outside tools, approving each call before it runs.
- **Import.** Load CSV exports from the Wallet app by BudgetBakers.

## Setup

You need Docker on Linux. On Mac or Windows, change the compose file to use `host.docker.internal` instead of host networking.

**1. Create your secrets** in `.env`:

```sh
for k in MONAI_API_KEY POSTGRES_PASSWORD MONAI_UI_PASSWORD MONAI_APPROVER_KEY; do
  echo "$k=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
done
chmod 600 .env
```

- `MONAI_UI_PASSWORD` is your browser login (username `monai`).
- `MONAI_API_KEY` lets other apps read your data and suggest changes.
- `MONAI_APPROVER_KEY` lets the Inbox approve changes. **Never give it to another app**, so no app can approve its own changes.

**2. Start it:**

```sh
docker compose up -d --build
```

Open http://127.0.0.1:3001. monai only listens on the machine it runs on; from another computer, use `ssh -L 3001:127.0.0.1:3001 you@your-server`.

The assistant runs locally through [Ollama](https://ollama.com) by default, at `http://localhost:11434`. You can switch to Claude or OpenAI in Settings.

**3. Optional: use it from Claude.** Point Claude Desktop (through `mcp-remote`) or Claude Code at `http://127.0.0.1:8001/mcp`, with `MONAI_API_KEY` as a bearer token. Suggested changes appear in monai's Inbox with a short code to approve them.

To update, pull the latest code and run `docker compose up -d --build` again. How it's built: [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT
