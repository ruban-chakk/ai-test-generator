"""Add immutable requirement version snapshots.

Revision ID: 20261021_0010
Revises: 20261021_0009
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0010"
down_revision = "20261021_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE requirements ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS requirement_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          requirement_id uuid NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
          project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
          version integer NOT NULL,
          external_id varchar,
          title text NOT NULL,
          description text NOT NULL,
          source varchar NOT NULL,
          status varchar NOT NULL,
          metadata jsonb,
          vector_id varchar,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_versions_requirement_version "
        "ON requirement_versions(requirement_id, version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirement_versions_vector_id "
        "ON requirement_versions(vector_id) WHERE vector_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_requirement_versions_project ON requirement_versions(project_id)"
    )
    op.execute(
        """
        INSERT INTO requirement_versions (
          requirement_id, project_id, version, external_id, title, description, source, status, metadata, created_at
        )
        SELECT id, project_id, version, external_id, title, description, source, status, metadata, created_at
        FROM requirements
        ON CONFLICT (requirement_id, version) DO NOTHING
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Requirement version snapshots are durable history and have no destructive automatic downgrade. "
        "Restore a verified backup into a replacement database instead."
    )
