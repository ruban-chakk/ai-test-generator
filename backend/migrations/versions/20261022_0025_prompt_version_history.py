"""Add immutable prompt version history.

Revision ID: 20261022_0025
Revises: 20261022_0024
"""
from alembic import op


revision = "20261022_0025"
down_revision = "20261022_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE prompt_configuration_versions (
            id uuid PRIMARY KEY,
            prompt_configuration_id uuid NOT NULL REFERENCES prompt_configurations(id) ON DELETE CASCADE,
            prompt_key varchar(64) NOT NULL,
            scope_type varchar(16) NOT NULL,
            scope_id uuid NULL,
            version integer NOT NULL,
            system_template text NOT NULL,
            user_template text NOT NULL,
            variables json NOT NULL DEFAULT '[]'::json,
            temperature double precision NULL,
            change_notes text NULL,
            status varchar(16) NOT NULL,
            content_checksum varchar(64) NOT NULL,
            parent_configuration_id uuid NULL,
            parent_version integer NULL,
            created_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            approved_by uuid NULL REFERENCES users(id) ON DELETE RESTRICT,
            published_at timestamp NULL,
            created_at timestamp NOT NULL,
            CONSTRAINT uq_prompt_configuration_version UNIQUE (prompt_configuration_id, version)
        );
        CREATE INDEX ix_prompt_configuration_versions_config_id ON prompt_configuration_versions(prompt_configuration_id);
        CREATE INDEX ix_prompt_configuration_versions_prompt_key ON prompt_configuration_versions(prompt_key);
        CREATE INDEX ix_prompt_configuration_versions_scope_type ON prompt_configuration_versions(scope_type);
        CREATE INDEX ix_prompt_configuration_versions_scope_id ON prompt_configuration_versions(scope_id);
        CREATE INDEX ix_prompt_configuration_versions_created_at ON prompt_configuration_versions(created_at);
        INSERT INTO prompt_configuration_versions (
            id, prompt_configuration_id, prompt_key, scope_type, scope_id, version,
            system_template, user_template, variables, temperature, change_notes,
            status, content_checksum, parent_configuration_id, parent_version,
            created_by, approved_by, published_at, created_at
        )
        SELECT
            gen_random_uuid(), id, prompt_key, scope_type, scope_id, version,
            system_template, user_template, variables, temperature, change_notes,
            status, content_checksum, parent_configuration_id, parent_version,
            created_by, approved_by, published_at, created_at
        FROM prompt_configurations;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_configuration_versions;")
