"""Add durable automated test execution runs.

Revision ID: 20261021_0004
Revises: 20261020_0003
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0004"
down_revision = "20261020_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS test_execution_runs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          test_case_id uuid NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
          test_case_version integer NOT NULL,
          environment varchar NOT NULL DEFAULT 'default',
          runner varchar NOT NULL DEFAULT 'generic',
          status varchar NOT NULL DEFAULT 'queued',
          idempotency_key varchar NOT NULL UNIQUE,
          external_run_id varchar,
          result jsonb NOT NULL DEFAULT '{}'::jsonb,
          requested_by varchar NOT NULL,
          started_at timestamptz,
          completed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_test_execution_runs_project ON test_execution_runs(project_id);
        CREATE INDEX IF NOT EXISTS idx_test_execution_runs_test_case ON test_execution_runs(test_case_id);
        CREATE INDEX IF NOT EXISTS idx_test_execution_runs_status ON test_execution_runs(status);
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Execution history is audit evidence and has no destructive automatic downgrade. "
        "Restore a verified backup into a replacement database instead."
    )
