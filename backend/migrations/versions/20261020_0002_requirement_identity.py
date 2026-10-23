"""Enforce project-scoped external requirement identity.

Revision ID: 20261020_0002
Revises: 20261020_0001
Create Date: 2026-10-20
"""
from alembic import op


revision = "20261020_0002"
down_revision = "20261020_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_requirements_project_external_id
          ON requirements(project_id, external_id)
          WHERE external_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_requirements_project_external_id")
