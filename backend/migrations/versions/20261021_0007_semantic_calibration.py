"""Add semantic impact calibration evidence.

Revision ID: 20261021_0007
Revises: 20261021_0006
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0007"
down_revision = "20261021_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_calibration_runs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          dataset_digest varchar NOT NULL,
          sample_count integer NOT NULL,
          label_distribution jsonb NOT NULL DEFAULT '{}'::jsonb,
          previous_thresholds jsonb NOT NULL DEFAULT '{}'::jsonb,
          proposed_thresholds jsonb NOT NULL DEFAULT '{}'::jsonb,
          metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
          status varchar NOT NULL DEFAULT 'proposed',
          requested_by varchar NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          applied_at timestamptz,
          CONSTRAINT uq_semantic_calibration_dataset UNIQUE (project_id, dataset_digest)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_semantic_calibration_project ON semantic_calibration_runs(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_semantic_calibration_status ON semantic_calibration_runs(status)")


def downgrade() -> None:
    # Calibration records are governance evidence, so automated rollback keeps them intact.
    pass
