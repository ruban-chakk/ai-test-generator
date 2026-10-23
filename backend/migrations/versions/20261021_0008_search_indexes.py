"""Add full-text indexes for keyword and hybrid search.

Revision ID: 20261021_0008
Revises: 20261021_0007
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0008"
down_revision = "20261021_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_requirements_search_tsv
        ON requirements USING gin (
          to_tsvector(
            'simple'::regconfig,
            coalesce(external_id, '') || ' ' || coalesce(title, '') || ' ' || coalesce(description, '')
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_test_cases_search_tsv
        ON test_cases USING gin (
          to_tsvector(
            'simple'::regconfig,
            coalesce(title, '') || ' ' || coalesce(description, '') || ' ' || coalesce(prerequisite, '') || ' ' ||
            coalesce(priority, '') || ' ' || coalesce(severity, '') || ' ' || coalesce(category, '') || ' ' ||
            coalesce(type, '')
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_feedback_search_tsv
        ON feedback USING gin (
          to_tsvector(
            'simple'::regconfig,
            coalesce(comment, '') || ' ' || coalesce(feedback_type, '') || ' ' || coalesce(status, '')
          )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_feedback_search_tsv")
    op.execute("DROP INDEX IF EXISTS idx_test_cases_search_tsv")
    op.execute("DROP INDEX IF EXISTS idx_requirements_search_tsv")
