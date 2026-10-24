# How monai is built

## The parts

| Part | What it is | Where |
|------|------------|-------|
| Web app | Next.js (React). Asks for the browser password and passes requests to the backend. The backend key never reaches the browser. | `ui/`, port 3001 |
| Backend | Python and FastAPI. All the money logic, the chat assistant and the tool server for Claude. | `backend/`, port 8001 |
| Database | PostgreSQL. Its structure is updated automatically on start (Alembic). | `alembic/`, port 5434 |
| Assistant | Ollama by default, or Claude or OpenAI, chosen in Settings. | `backend/config.py` |

Everything listens on `127.0.0.1` only, and each part needs its own secret.

`poc/` is the original prototype. It isn't used.

## The main rule: the assistant never does its own maths

An early version let the AI write database queries itself. On real data it picked the wrong year, counted salary as spending, and returned the wrong answers with full confidence.

So now the assistant only *chooses* from a fixed list of tested calculations in `backend/tools.py` (spending totals, recurring charges, period comparisons, net worth and so on) and fills in their inputs. The calculations run in code and return the numbers. If no calculation fits the question, the assistant says so instead of guessing.

Each calculation's description doubles as its instructions to the assistant. A test locks down the full list (`backend/tests/agent_tool_surface.json`), so any change to it gets reviewed.

## How a chat question is answered

1. The browser sends the question. The backend runs it as a background task, so a reload or a closed tab doesn't lose it.
2. The assistant is shown only the calculations that are relevant to the question, which helps smaller models choose well.
3. It runs one or more calculations. Each one appears as a step in the answer as it happens.
4. The answer streams back as formatted text, with links to the records behind each number.
5. Conversations are stored as threads. In long threads, older messages are summarised to fit, but numbers are never carried over from old answers. They're always worked out again.

## How changes are kept safe

- The assistant can't write directly. It can only *suggest* a change, which is shown as a card or in the Inbox.
- A change is applied only when you approve it, and it's logged.
- Changes suggested by outside apps (over MCP) need either the Inbox or a 6-character code that only monai shows. The approver key is kept apart from the key those apps hold, so they can never approve their own changes.
- Text inside attached files is treated as data, never as instructions. When a file is attached, the assistant can only read and suggest that file's rows for approval. It can't call outside tools.
- Skills are plain text the assistant reads. Nothing in them is run. If a skill file changes, it's switched off until you check it again.
- Outside tool servers run separately. You approve each of their calls first, and their results are marked unverified.

## Importing from Wallet

monai reads CSV exports from the Wallet app (by BudgetBakers): semicolon-separated, dates as `YYYY-MM-DD HH:MM:SS`, negative amounts for expenses. Rows marked as transfers aren't counted as spending.
