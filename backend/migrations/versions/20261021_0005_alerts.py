"""Add durable operational alerts and delivery state.

Revision ID: 20261021_0005
Revises: 20261021_0004
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0005"
down_revision = "20261021_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
          dedupe_key varchar NOT NULL UNIQUE,
          category varchar NOT NULL,
          severity varchar NOT NULL,
          title text NOT NULL,
          details jsonb NOT NULL DEFAULT '{}'::jsonb,
          status varchar NOT NULL DEFAULT 'open',
          delivery_status varchar NOT NULL DEFAULT 'not_configured',
          acknowledged_by varchar,
          acknowledged_at timestamptz,
          delivered_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_project ON alerts(project_id);
        CREATE INDEX IF NOT EXISTS idx_alerts_category ON alerts(category);
        CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
        CREATE INDEX IF NOT EXISTS idx_alerts_delivery_status ON alerts(delivery_status);
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Alert history is operational evidence and has no destructive automatic downgrade. "
        "Restore a verified backup into a replacement database instead."
    )
