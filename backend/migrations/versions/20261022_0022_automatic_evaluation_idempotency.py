"""Add an idempotency link for automatic quality evaluations.

Revision ID: 20261022_0022
Revises: 20261022_0021
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0022"
down_revision = "20261022_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE quality_evaluations ADD COLUMN source_event_id uuid;
        ALTER TABLE quality_evaluations ADD CONSTRAINT fk_quality_evaluation_source_event
          FOREIGN KEY (source_event_id) REFERENCES outbox_events(id) ON DELETE SET NULL;
        CREATE UNIQUE INDEX uq_quality_evaluation_source_event
          ON quality_evaluations(source_event_id) WHERE source_event_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS uq_quality_evaluation_source_event;
        ALTER TABLE quality_evaluations DROP CONSTRAINT IF EXISTS fk_quality_evaluation_source_event;
        ALTER TABLE quality_evaluations DROP COLUMN IF EXISTS source_event_id;
        """
    )
