"""Version import mapping profiles.

Revision ID: 20261022_0013
Revises: 20261022_0012
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0013"
down_revision = "20261022_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS custom_field_schema jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE test_case_versions ADD COLUMN IF NOT EXISTS custom_field_schema jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE import_mapping_profiles ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE import_mapping_profiles ADD COLUMN IF NOT EXISTS parent_profile_id uuid NULL")
    op.execute("ALTER TABLE import_mapping_profiles ADD COLUMN IF NOT EXISTS superseded_at timestamptz NULL")
    op.execute("ALTER TABLE import_mapping_profiles DROP CONSTRAINT IF EXISTS uq_import_mapping_profile_name")
    op.execute(
        """
        DO $$ BEGIN
          ALTER TABLE import_mapping_profiles
            ADD CONSTRAINT fk_import_mapping_parent
            FOREIGN KEY (parent_profile_id) REFERENCES import_mapping_profiles(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          ALTER TABLE import_mapping_profiles
            ADD CONSTRAINT uq_import_mapping_profile_name_version
            UNIQUE (project_id, entity_type, name, version);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_import_mapping_profiles_parent "
        "ON import_mapping_profiles(parent_profile_id)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Mapping revisions are durable customer configuration. "
        "Restore a verified backup into a replacement database instead."
    )
