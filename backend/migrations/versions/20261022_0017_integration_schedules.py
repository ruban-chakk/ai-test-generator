"""Add durable scheduled integration synchronization.

Revision ID: 20261022_0017
Revises: 20261022_0016
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0017"
down_revision = "20261022_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_schedules (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name varchar(255) NOT NULL,
          integration_type varchar(32) NOT NULL DEFAULT 'jira',
          configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
          interval_seconds integer NOT NULL DEFAULT 3600,
          enabled boolean NOT NULL DEFAULT true,
          next_run_at timestamptz NOT NULL,
          last_run_at timestamptz,
          last_status varchar(32),
          last_error_type varchar(255),
          locked_at timestamptz,
          locked_by varchar(255),
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_integration_schedule_type CHECK (integration_type IN ('jira')),
          CONSTRAINT ck_integration_schedule_interval CHECK (interval_seconds >= 300)
        );
        CREATE INDEX IF NOT EXISTS idx_integration_schedules_project ON integration_schedules(project_id);
        CREATE INDEX IF NOT EXISTS idx_integration_schedules_enabled ON integration_schedules(enabled);
        CREATE INDEX IF NOT EXISTS idx_integration_schedules_next_run ON integration_schedules(next_run_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS integration_schedules")
