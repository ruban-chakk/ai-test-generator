"""Add historical test-case identity and immutable vector records.

Revision ID: 20261021_0009
Revises: 20261021_0008
Create Date: 2026-10-21
"""
from alembic import op


revision = "20261021_0009"
down_revision = "20261021_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE test_scenarios ADD COLUMN IF NOT EXISTS external_id varchar")
    op.execute("ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS external_id varchar")
    op.execute(
        "ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS source varchar NOT NULL DEFAULT 'generated'"
    )
    op.execute("ALTER TABLE test_case_versions ADD COLUMN IF NOT EXISTS external_id varchar")
    op.execute(
        "ALTER TABLE test_case_versions ADD COLUMN IF NOT EXISTS source varchar NOT NULL DEFAULT 'generated'"
    )
    op.execute("ALTER TABLE test_case_versions ADD COLUMN IF NOT EXISTS vector_id varchar")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_test_scenarios_requirement_external_id
        ON test_scenarios(requirement_id, external_id)
        WHERE external_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_test_cases_requirement_external_id
        ON test_cases(requirement_id, external_id)
        WHERE external_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_test_case_versions_case_version
        ON test_case_versions(test_case_id, version)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_test_case_versions_vector_id "
        "ON test_case_versions(vector_id) WHERE vector_id IS NOT NULL"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Historical import identities and immutable version vectors are durable audit data and have no "
        "destructive automatic downgrade. Restore a verified backup into a replacement database instead."
    )
