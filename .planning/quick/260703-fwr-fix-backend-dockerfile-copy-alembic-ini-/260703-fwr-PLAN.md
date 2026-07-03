---
phase: quick-260703-fwr
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/Dockerfile
autonomous: true
requirements: []
must_haves:
  truths:
    - "Backend container starts without the 'No script_location key found' Alembic error"
    - "The built image contains /app/alembic.ini and /app/alembic/versions/*.py"
    - "entrypoint.sh can run `alembic upgrade head` from /app and find script_location=alembic"
  artifacts:
    - "backend/Dockerfile with COPY steps for alembic.ini and alembic/"
  key_links:
    - "WORKDIR /app + script_location=alembic (relative) → alembic.ini and alembic/ must land at /app/alembic.ini and /app/alembic/"
---

<objective>
Fix `backend/Dockerfile` so the backend image contains the Alembic config and
migrations. Currently the Dockerfile only copies `backend/` into `/app`, but
`entrypoint.sh` runs `alembic upgrade head` from `/app`, which needs
`alembic.ini` (with `script_location = alembic`) and the `alembic/` migrations
directory — both of which live at the repo root, not inside `backend/`. The
container crash-loops on every start with:
`FAILED: No 'script_location' key found in configuration.`

Purpose: Unblock `docker compose up` — the backend container currently fails
every restart because migrations cannot run.
Output: Updated `backend/Dockerfile` that copies `alembic.ini` and `alembic/`
into `/app`, verified by inspecting the built image contents.
</objective>

<execution_context>
@/home/user/monai/.claude/gsd-core/workflows/execute-plan.md
@/home/user/monai/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@backend/Dockerfile
@backend/entrypoint.sh
@alembic.ini
@.dockerignore

# Facts confirmed during planning:
# - .dockerignore does NOT exclude alembic.ini or alembic/ (safe to COPY)
# - alembic/ contains: __init__.py, env.py, script.py.mako, versions/ (001_baseline.py, 002_new_tables.py)
# - docker-compose.yml builds this image with `context: .` (repo root), so
#   `COPY alembic.ini` / `COPY alembic/` resolve against the repo root.
# - alembic.ini uses `script_location = alembic` (relative to CWD, which is /app).
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add COPY steps for alembic.ini and alembic/ to backend/Dockerfile</name>
  <files>backend/Dockerfile</files>
  <action>
In `backend/Dockerfile`, after the existing `COPY backend/ ./backend/` line
(line 10) and before `EXPOSE 8001`, add two COPY steps so the Alembic config
and migrations land at the WORKDIR (`/app`):

- `COPY alembic.ini ./alembic.ini`
- `COPY alembic/ ./alembic/`

Because `WORKDIR /app` is set, these resolve to `/app/alembic.ini` and
`/app/alembic/`. Since `alembic.ini` declares `script_location = alembic`
(relative to CWD `/app`), Alembic will find migrations at `/app/alembic/`.
The build context is the repo root (docker-compose `context: .`), so the
source paths `alembic.ini` and `alembic/` resolve correctly. Do NOT modify
docker-compose.yml, entrypoint.sh, or alembic.ini. Add a short intent comment
above the new COPY lines noting these are required by `alembic upgrade head`
in entrypoint.sh.
  </action>
  <verify>
    <automated>grep -q 'COPY alembic.ini ./alembic.ini' backend/Dockerfile &amp;&amp; grep -q 'COPY alembic/ ./alembic/' backend/Dockerfile</automated>
  </verify>
  <done>backend/Dockerfile contains COPY steps for both alembic.ini and alembic/, placed after the backend/ copy and before EXPOSE, with WORKDIR /app in effect.</done>
</task>

<task type="auto">
  <name>Task 2: Build the image and verify it contains the Alembic files</name>
  <files>backend/Dockerfile</files>
  <action>
Build the backend image from the repo root (build context = repo root, matching
docker-compose `context: .`), then inspect the image filesystem to confirm the
Alembic config and migration scripts are present at /app. Do NOT run
`docker compose up` end-to-end (no Postgres/Ollama in this sandbox) — only build
and inspect the image contents.

Run:
- `docker build -f backend/Dockerfile -t monai-backend-verify .`
- `docker run --rm monai-backend-verify ls -la /app/alembic.ini /app/alembic/versions`

Confirm `/app/alembic.ini` exists and `/app/alembic/versions` lists
`001_baseline.py` and `002_new_tables.py`.

If `docker` is unavailable in this sandbox, fall back to a static verification:
confirm the Dockerfile COPY lines are correct and that `alembic.ini` and
`alembic/versions/*.py` exist at the repo root (they do), and note in the
SUMMARY that runtime image inspection was skipped due to no Docker daemon.
  </action>
  <verify>
    <automated>docker build -f backend/Dockerfile -t monai-backend-verify . &amp;&amp; docker run --rm monai-backend-verify ls -la /app/alembic.ini /app/alembic/versions</automated>
  </verify>
  <done>Either: the built image lists /app/alembic.ini and /app/alembic/versions/*.py; OR (if no Docker daemon) static verification confirms the COPY lines and source files, documented in SUMMARY.</done>
</task>

</tasks>

<verification>
- backend/Dockerfile copies alembic.ini and alembic/ into /app.
- Built image (if buildable) contains /app/alembic.ini and /app/alembic/versions/001_baseline.py + 002_new_tables.py.
- No changes to docker-compose.yml, entrypoint.sh, or alembic.ini.
</verification>

<success_criteria>
- `alembic upgrade head` running from /app can resolve `script_location = alembic`
  (files present at /app/alembic.ini and /app/alembic/).
- The "No 'script_location' key found in configuration" crash-loop is resolved.
- Only backend/Dockerfile was modified.
</success_criteria>

<output>
Create `.planning/quick/260703-fwr-fix-backend-dockerfile-copy-alembic-ini-/260703-fwr-SUMMARY.md` when done
</output>
