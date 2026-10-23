"""Add scoped versioned prompt configurations.

Revision ID: 20261022_0023
Revises: 20261022_0022
"""
from alembic import op


revision = "20261022_0023"
down_revision = "20261022_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE prompt_configurations (
            id uuid PRIMARY KEY,
            scope_type varchar(16) NOT NULL,
            scope_id uuid NULL,
            prompt_key varchar(64) NOT NULL,
            system_template text NOT NULL,
            user_template text NOT NULL,
            variables json NOT NULL DEFAULT '[]'::json,
            temperature double precision NULL,
            version integer NOT NULL DEFAULT 1,
            status varchar(16) NOT NULL DEFAULT 'published',
            updated_by uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at timestamp NOT NULL,
            updated_at timestamp NOT NULL,
            CONSTRAINT uq_prompt_configuration_scope_key UNIQUE (scope_type, scope_id, prompt_key)
        );
        CREATE INDEX ix_prompt_configurations_scope_type ON prompt_configurations(scope_type);
        CREATE INDEX ix_prompt_configurations_scope_id ON prompt_configurations(scope_id);
        CREATE INDEX ix_prompt_configurations_prompt_key ON prompt_configurations(prompt_key);
        CREATE INDEX ix_prompt_configurations_status ON prompt_configurations(status);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_configurations;")
