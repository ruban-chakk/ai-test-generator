"""Add reusable import mappings and test-case custom fields.

Revision ID: 20261021_0011
Revises: 20261021_0010
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0011"
down_revision = "20261021_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS import_mapping_profiles (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name varchar(255) NOT NULL,
          entity_type varchar(32) NOT NULL,
          configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
          active boolean NOT NULL DEFAULT true,
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_import_mapping_profile_name UNIQUE (project_id, entity_type, name),
          CONSTRAINT ck_import_mapping_profile_entity CHECK (entity_type IN ('requirement', 'test_case'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_import_mapping_profiles_project "
        "ON import_mapping_profiles(project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_import_mapping_profiles_entity "
        "ON import_mapping_profiles(entity_type)"
    )
    op.execute(
        "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS custom_fields jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE test_case_versions ADD COLUMN IF NOT EXISTS custom_fields jsonb NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Import profiles and imported custom fields may contain durable customer configuration. "
        "Restore a verified backup into a replacement database instead."
    )
