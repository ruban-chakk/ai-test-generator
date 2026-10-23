"""Link evaluation feedback and snapshot AI usage pricing.

Revision ID: 20261022_0021
Revises: 20261022_0020
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0021"
down_revision = "20261022_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE feedback ADD COLUMN quality_evaluation_id uuid;
        ALTER TABLE feedback ADD CONSTRAINT fk_feedback_quality_evaluation
          FOREIGN KEY (quality_evaluation_id) REFERENCES quality_evaluations(id) ON DELETE SET NULL;
        CREATE INDEX idx_feedback_quality_evaluation ON feedback(quality_evaluation_id);

        ALTER TABLE ai_usage_records ADD COLUMN input_rate_per_million double precision NOT NULL DEFAULT 0;
        ALTER TABLE ai_usage_records ADD COLUMN output_rate_per_million double precision NOT NULL DEFAULT 0;
        ALTER TABLE ai_usage_records ADD COLUMN pricing_source varchar(64) NOT NULL DEFAULT 'unpriced';

        UPDATE ai_usage_records
        SET input_rate_per_million = 0.75,
            output_rate_per_million = 4.50,
            pricing_source = 'openai_catalog_2026-10-22',
            cost_micros = round(input_tokens * 0.75 + output_tokens * 4.50)
        WHERE lower(model) = 'gpt-5.4-mini'
          AND cost_micros = 0;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_feedback_quality_evaluation;
        ALTER TABLE feedback DROP CONSTRAINT IF EXISTS fk_feedback_quality_evaluation;
        ALTER TABLE feedback DROP COLUMN IF EXISTS quality_evaluation_id;
        ALTER TABLE ai_usage_records DROP COLUMN IF EXISTS pricing_source;
        ALTER TABLE ai_usage_records DROP COLUMN IF EXISTS output_rate_per_million;
        ALTER TABLE ai_usage_records DROP COLUMN IF EXISTS input_rate_per_million;
        """
    )
