"""Track impact-analysis target scope.

Revision ID: 20261023_0027
Revises: 20261022_0026
"""
from alembic import op


revision = "20261023_0027"
down_revision = "20261022_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE impact_analyses
            ADD COLUMN target_level varchar(32) NOT NULL DEFAULT 'requirement',
            ADD COLUMN target_id uuid NULL;
        UPDATE impact_analyses SET target_id = requirement_id WHERE target_id IS NULL;
        CREATE INDEX ix_impact_analyses_target_level ON impact_analyses(target_level);
        CREATE INDEX ix_impact_analyses_target_id ON impact_analyses(target_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_impact_analyses_target_id;
        DROP INDEX IF EXISTS ix_impact_analyses_target_level;
        ALTER TABLE impact_analyses
            DROP COLUMN IF EXISTS target_id,
            DROP COLUMN IF EXISTS target_level;
        """
    )
