"""Preserve unresolved mapped-import records for later reconciliation.

Revision ID: 20261022_0016
Revises: 20261022_0015
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0016"
down_revision = "20261022_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mapped_import_jobs ADD COLUMN IF NOT EXISTS unresolved_record_count integer NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS unresolved_import_records (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          profile_id uuid NOT NULL REFERENCES import_mapping_profiles(id) ON DELETE RESTRICT,
          import_job_id uuid REFERENCES mapped_import_jobs(id) ON DELETE SET NULL,
          entity_type varchar(32) NOT NULL DEFAULT 'test_case',
          external_id varchar(255) NOT NULL,
          missing_reference varchar(255) NOT NULL,
          canonical_payload jsonb NOT NULL,
          dedupe_sha256 varchar(64) NOT NULL,
          status varchar(32) NOT NULL DEFAULT 'pending',
          retry_count integer NOT NULL DEFAULT 0,
          last_error_type varchar(255),
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          resolved_at timestamptz,
          CONSTRAINT uq_unresolved_import_dedupe UNIQUE (dedupe_sha256),
          CONSTRAINT ck_unresolved_import_status CHECK (status IN ('pending', 'resolved', 'dismissed'))
        );
        CREATE INDEX IF NOT EXISTS idx_unresolved_import_project ON unresolved_import_records(project_id);
        CREATE INDEX IF NOT EXISTS idx_unresolved_import_profile ON unresolved_import_records(profile_id);
        CREATE INDEX IF NOT EXISTS idx_unresolved_import_job ON unresolved_import_records(import_job_id);
        CREATE INDEX IF NOT EXISTS idx_unresolved_import_reference ON unresolved_import_records(missing_reference);
        CREATE INDEX IF NOT EXISTS idx_unresolved_import_status ON unresolved_import_records(status);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS unresolved_import_records")
    op.execute("ALTER TABLE mapped_import_jobs DROP COLUMN IF EXISTS unresolved_record_count")
