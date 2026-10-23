"""Backfill immutable history for prompt configurations that predate it.

Revision ID: 20261022_0026
Revises: 20261022_0025
"""
from alembic import op


revision = "20261022_0026"
down_revision = "20261022_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing installations already have prompt configurations but no history
    # rows. Keep this idempotent so a partially applied deployment is safe to
    # retry. gen_random_uuid is used throughout the project's migrations.
    op.execute(
        """
        INSERT INTO prompt_configuration_versions (
            id, prompt_configuration_id, prompt_key, scope_type, scope_id, version,
            system_template, user_template, variables, temperature, change_notes,
            status, content_checksum, parent_configuration_id, parent_version,
            created_by, approved_by, published_at, created_at
        )
        SELECT
            gen_random_uuid(), pc.id, pc.prompt_key, pc.scope_type, pc.scope_id, pc.version,
            pc.system_template, pc.user_template, pc.variables, pc.temperature, pc.change_notes,
            pc.status, pc.content_checksum, pc.parent_configuration_id, pc.parent_version,
            pc.created_by, pc.approved_by, pc.published_at, pc.created_at
        FROM prompt_configurations pc
        WHERE NOT EXISTS (
            SELECT 1
            FROM prompt_configuration_versions pv
            WHERE pv.prompt_configuration_id = pc.id
              AND pv.version = pc.version
        );
        """
    )


def downgrade() -> None:
    # History is audit data; retain it on downgrade rather than deleting it.
    pass
