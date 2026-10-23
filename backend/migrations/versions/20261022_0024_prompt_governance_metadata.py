"""Add prompt governance and inheritance metadata.

Revision ID: 20261022_0024
Revises: 20261022_0023
"""
from alembic import op


revision = "20261022_0024"
down_revision = "20261022_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompt_configurations
            ADD COLUMN change_notes text NULL,
            ADD COLUMN content_checksum varchar(64) NOT NULL DEFAULT '',
            ADD COLUMN parent_configuration_id uuid NULL REFERENCES prompt_configurations(id) ON DELETE SET NULL,
            ADD COLUMN parent_version integer NULL,
            ADD COLUMN created_by uuid NULL REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN approved_by uuid NULL REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN published_at timestamp NULL;
        UPDATE prompt_configurations SET created_by = updated_by WHERE created_by IS NULL;
        ALTER TABLE prompt_configurations ALTER COLUMN created_by SET NOT NULL;
        CREATE INDEX ix_prompt_configurations_parent_id ON prompt_configurations(parent_configuration_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_prompt_configurations_parent_id;
        ALTER TABLE prompt_configurations
            DROP COLUMN IF EXISTS published_at,
            DROP COLUMN IF EXISTS approved_by,
            DROP COLUMN IF EXISTS created_by,
            DROP COLUMN IF EXISTS parent_version,
            DROP COLUMN IF EXISTS parent_configuration_id,
            DROP COLUMN IF EXISTS content_checksum,
            DROP COLUMN IF EXISTS change_notes;
        """
    )
