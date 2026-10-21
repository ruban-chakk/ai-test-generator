"""Add shared API rate-limit counters.

Revision ID: 20261021_0006
Revises: 20261021_0005
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0006"
down_revision = "20261021_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_rate_limits (
          bucket_key varchar PRIMARY KEY,
          window_start timestamptz NOT NULL,
          request_count integer NOT NULL DEFAULT 0
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_rate_limits")
