"""Allow only one durable resolution per feedback item.

Revision ID: 20261020_0003
Revises: 20261020_0002
Create Date: 2026-10-20
"""
from alembic import op


revision = "20261020_0003"
down_revision = "20261020_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_revision_records_feedback_resolution
          ON revision_records(feedback_id)
          WHERE feedback_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_revision_records_feedback_resolution")
