"""external MCP servers, per-thread selection and external calls (Phase 41)

Revision ID: 20116eb89bff
Revises: 22645aa717c0
Create Date: 2026-10-22

Adds three tables:
- `mcp_servers`: owner-registered external MCP servers. Off by default.
  `headers` and `env` hold secrets. `approved_tools` is the reviewed tool
  snapshot, `tool_policies` maps a tool name to ask/always/deny.
- `thread_mcp_servers`: which servers a thread uses. Cascades from both sides.
- `ext_calls`: one row per external tool call, both the approval and the
  receipt. Only the result's sha256 and size are kept, never the result.
  `thread_id` cascades with its thread; `message_id` and `server_id` are SET
  NULL (`server_slug` stays) so deleting a message or a server keeps the record.

Arming: none, additive, nothing is deleted or rewritten.

Idempotent: `backend/entrypoint.sh` runs `alembic upgrade head` under `set -e`
on every container start, so every statement is IF NOT EXISTS.

Imports nothing from backend.*: raw SQL via op.execute only.

downgrade(): drops the indexes then ext_calls, thread_mcp_servers, mcp_servers;
server config, selections and call records are lost.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20116eb89bff"
down_revision: Union[str, None] = "22645aa717c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS mcp_servers ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "slug VARCHAR(24) NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9-]{1,24}$'), "
        "transport VARCHAR(8) NOT NULL CHECK (transport IN ('http','sse','stdio')), "
        "url TEXT NULL, "
        "headers JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "command VARCHAR(8) NULL CHECK (command IN ('npx','uvx')), "
        "args JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "env JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "enabled BOOLEAN NOT NULL DEFAULT false, "
        "approved_tools JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "tool_policies JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "changed_count INT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_mcp_transport_shape CHECK ("
        "(transport = 'stdio') = (command IS NOT NULL) "
        "AND (transport = 'stdio') = (url IS NULL)))"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS thread_mcp_servers ("
        "thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE, "
        "server_id UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE, "
        "PRIMARY KEY (thread_id, server_id))"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS ext_calls ("
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE, "
        "turn_id UUID NOT NULL, "
        "message_id UUID NULL REFERENCES messages(id) ON DELETE SET NULL, "
        "server_id UUID NULL REFERENCES mcp_servers(id) ON DELETE SET NULL, "
        "server_slug VARCHAR(24) NOT NULL, "
        "tool TEXT NOT NULL, "
        "args JSONB NOT NULL, "
        "args_sha256 CHAR(64) NOT NULL, "
        "destination TEXT NOT NULL, "
        "leaves_machine BOOLEAN NOT NULL, "
        "reason VARCHAR(16) NULL CHECK (reason IN ('ledger_read')), "
        "approval VARCHAR(8) NOT NULL DEFAULT 'pending' "
        "CHECK (approval IN ('pending','approved','denied','expired')), "
        "decided_via VARCHAR(8) NULL "
        "CHECK (decided_via IN ('user','policy','stop','expiry')), "
        "decided_at TIMESTAMPTZ NULL, "
        "expires_at TIMESTAMPTZ NOT NULL, "
        "receipt VARCHAR(9) NULL "
        "CHECK (receipt IN ('pending','confirmed','failed','unknown')), "
        "result_sha256 CHAR(64) NULL, "
        "result_bytes INT NULL, "
        "error TEXT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "CONSTRAINT ck_ext_decided CHECK "
        "((approval = 'pending') = (decided_via IS NULL)))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ext_calls_pending "
        "ON ext_calls (thread_id) WHERE approval = 'pending'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ext_calls_turn ON ext_calls (turn_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ext_calls_thread ON ext_calls (thread_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ext_calls_thread")
    op.execute("DROP INDEX IF EXISTS ix_ext_calls_turn")
    op.execute("DROP INDEX IF EXISTS ix_ext_calls_pending")
    op.execute("DROP TABLE IF EXISTS ext_calls")
    op.execute("DROP TABLE IF EXISTS thread_mcp_servers")
    op.execute("DROP TABLE IF EXISTS mcp_servers")
