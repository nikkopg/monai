# monai

A personal finance app that keeps your spending and your investments in one place, with an assistant you can ask about your money in plain language. It runs on your own computer.

## Features

- **Your money and investments together.** Track bank accounts, cash, spending, income and investments across all your platforms, with net worth over time. Accounts can be in rupiah or US dollars, and every total is shown in rupiah.
- **An assistant that's honest and private.** Ask "How much did I spend on food last month?" or "Add a grocery expense for yesterday." It never makes up a number: every figure comes from a tested calculation. It never changes your data until you approve. It runs on your computer by default, so your data stays with you.
- **Add your own skills and tools.** Teach the assistant with instruction files, and connect outside tools it can use. You approve each tool use before it happens.
- **Use it from other AI apps.** Claude and other AI assistants can connect to monai to read your finances and suggest changes, which still wait for your approval in monai.

## Setup

You need Docker on Linux. On Mac or Windows, change the compose file to use `host.docker.internal` instead of host networking.

**1. Create your passwords** in `.env`:

```sh
for k in MONAI_API_KEY POSTGRES_PASSWORD MONAI_UI_PASSWORD MONAI_APPROVER_KEY; do
  echo "$k=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
done
chmod 600 .env
```

- `MONAI_UI_PASSWORD` is your browser login (username `monai`).
- `MONAI_API_KEY` lets other AI apps connect to monai.
- `MONAI_APPROVER_KEY` is what approves changes. **Never give it to another app**, so no app can approve its own changes.

**2. Start it:**

```sh
docker compose up -d --build
```

Open http://127.0.0.1:3001. monai can only be reached from the computer it runs on; from another computer, use `ssh -L 3001:127.0.0.1:3001 you@your-server`.

The assistant uses [Ollama](https://ollama.com) on your computer by default. You can switch to Claude or OpenAI in Settings.

**3. Optional: connect another AI app.** In Claude Desktop (through `mcp-remote`) or Claude Code, add `http://127.0.0.1:8001/mcp` with your `MONAI_API_KEY`.

To update, pull the latest code and run `docker compose up -d --build` again. How it's built: [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT
