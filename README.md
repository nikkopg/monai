# monai

Your money, in one place, and an assistant you can ask about it. It runs on your own machine.

## What it does

monai keeps your spending and your investments together and lets you ask about them in plain language:

- "How much did I spend on food last month?"
- "What are my recurring charges?"
- "Compare this month with the same month last year."
- "Add a grocery expense for yesterday."

Two rules hold everywhere:

- **It never makes up a number.** The assistant can't do its own maths. It picks from a fixed set of tested calculations, and every figure comes from those.
- **It never changes your data without asking.** Any change shows up as a card with Approve and Reject buttons. Nothing is written until you approve, and every change is logged.

## What's in it

- **Chat.** Answers appear as they're written, show which calculations were used, and link to the records behind each number. Conversations are saved, so you can return to them, and reloading the page loses nothing. You can stop an answer at any time, and errors are always shown, never silent.
- **Files in chat.** Attach a CSV, a PDF bank statement or a photo of a receipt, then ask about it. Its rows are suggested as one batch for you to approve. Text inside a file can't make the assistant change anything.
- **Skills.** Put instruction files (`SKILL.md`) in the `skills/` folder and switch them on in Settings. The assistant reads them when they're relevant. Nothing in a skill is ever run.
- **Outside tools.** Connect other AI tool servers in Settings. You approve each call, with its exact inputs, before it runs. Their answers are marked "external, unverified", and they can't touch your data.
- **Cashflow.** Your net worth, spending by category, income against expenses, monthly trends and account balances. The net-worth chart shows months with missing data as gaps instead of guessing.
- **Records.** Every transaction, grouped by day, with filters and bulk edits. Add an expense, income or transfer from one form.
- **Investments.** Holdings across platforms with live prices, profit and loss, USD to IDR conversion, cash and gold, and allocation charts. You can buy or sell using money from one of your accounts.
- **Inbox.** Every change waiting for your approval, whether it came from chat or from Claude, with likely duplicates flagged.
- **Use it from Claude.** Claude Desktop and other AI apps can read your data. They can also suggest changes, but those wait for your approval in monai.
- **Import.** Load CSV exports from the Wallet app by BudgetBakers.

## Privacy

Everything stays on your machine. By default the assistant runs locally through [Ollama](https://ollama.com). Claude or OpenAI is used only if you choose it in Settings. monai is only reachable from the machine it runs on.

## Setup

You need Docker on Linux. On Mac or Windows, change the compose file to use `host.docker.internal` instead of host networking.

**1. Create your passwords.** These commands write four random secrets to `.env`:

```sh
for k in MONAI_API_KEY POSTGRES_PASSWORD MONAI_UI_PASSWORD MONAI_APPROVER_KEY; do
  echo "$k=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
done
chmod 600 .env
```

- `MONAI_UI_PASSWORD` is what your browser asks for. The username is `monai`.
- `MONAI_API_KEY` lets other apps such as Claude read your data and suggest changes.
- `MONAI_APPROVER_KEY` lets the Inbox approve changes. **Never give it to Claude or any other app.** Keeping it separate means no outside app can approve its own changes.

**2. Choose the assistant.** By default monai uses Ollama on `http://localhost:11434` with the model set in `docker-compose.yml`. You can switch to Claude or OpenAI in Settings later.

**3. Start it:**

```sh
docker compose up -d --build
```

Open http://127.0.0.1:3001. To use monai from another computer, tunnel in with `ssh -L 3001:127.0.0.1:3001 you@your-server`.

### Using monai from Claude

Point Claude Desktop (through `mcp-remote`) or Claude Code at `http://127.0.0.1:8001/mcp` and send `MONAI_API_KEY` as a bearer token. When Claude suggests a change, it shows up in monai's Inbox along with a 6-character code. Approve it there, or give Claude the code. After too many wrong codes, Claude is locked out and the change can only be approved in the Inbox.

## Updating

Pull the latest code and run `docker compose up -d --build` again. Database updates apply automatically on start.

**Changing the database password on an existing install.** `POSTGRES_PASSWORD` only takes effect on a new database. To change it on one you already have, back it up first:

```sh
mkdir -p ~/monai-backups && chmod 700 ~/monai-backups
D=~/monai-backups/monai_$(date +%F).dump
docker exec monai-db pg_dump -U monai -Fc monai > "$D" && chmod 600 "$D" && ls -l "$D"
PW=$(grep '^POSTGRES_PASSWORD=' .env | tail -1 | cut -d= -f2-)
printf "ALTER USER monai WITH PASSWORD '%s';\n" "$PW" | docker exec -i monai-db psql -U monai -d monai -v ON_ERROR_STOP=1
unset PW
docker compose up -d --build
```

Check that the backup file isn't empty before you continue. If the rebuild fails, set the old password back the same way and try again.

**Very old installs (before June 2026).** If your database predates automatic updates, back it up, run `alembic stamp 3a1f8c2d9e04`, then run `alembic upgrade head`. Running the upgrade without the stamp fails with "relation accounts already exists".

## Development

- **Backend tests:** run `pytest` from the repo root. It uses a separate `monai_test` database and refuses to touch your real one. Export only the database password first:
  `export POSTGRES_PASSWORD="$(grep '^POSTGRES_PASSWORD=' .env | tail -1 | cut -d= -f2-)"`
- **UI tests:** run `cd ui && CI=1 npm run e2e`. They use fake data on port 3099.
- **Inbox live test:** `ui/e2e/inbox-live.spec.ts` writes real rows, so it's opt-in. It needs a backend on `monai_test` with test-only keys. Set `E2E_SCRATCH_DB_CONFIRMED=monai_test` only after checking that backend's database:

  ```sh
  DATABASE_URL=postgresql+psycopg://monai:$POSTGRES_PASSWORD@127.0.0.1:5434/monai_test MONAI_API_KEY=e2e-api-key-synthetic-0001 MONAI_APPROVER_KEY=e2e-approver-key-synthetic-0002 TZ=Asia/Jakarta PGTZ=Asia/Jakarta .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8011
  cd ui && CI=1 E2E_LIVE=1 E2E_SCRATCH_DB_CONFIRMED=monai_test E2E_BACKEND=http://127.0.0.1:8011 E2E_API_KEY=e2e-api-key-synthetic-0001 E2E_APPROVER_KEY=e2e-approver-key-synthetic-0002 MONAI_API=http://127.0.0.1:8011 MONAI_API_KEY=e2e-api-key-synthetic-0001 MONAI_APPROVER_KEY=e2e-approver-key-synthetic-0002 npx playwright test e2e/inbox-live.spec.ts
  ```

- **Assistant quality check:** asks a fixed set of questions and checks the answers. It's run by hand and isn't part of CI. Run `env -u DATABASE_URL python -m backend.evals.agent_eval`, or add `--case 4` to run a single question.
- **Before pushing:** this repo is public, but monai runs on real finances. Run `git config core.hooksPath .githooks` once. After that, each push is blocked if it contains planning notes, data files, secrets or real-looking amounts.

How it's built: [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT
