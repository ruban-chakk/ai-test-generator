"""Add resumable mapped import jobs.

Revision ID: 20261022_0014
Revises: 20261022_0013
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0014"
down_revision = "20261022_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mapped_import_jobs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          profile_id uuid NOT NULL REFERENCES import_mapping_profiles(id) ON DELETE RESTRICT,
          profile_version integer NOT NULL,
          entity_type varchar(32) NOT NULL,
          mapping_snapshot jsonb NOT NULL,
          original_filename varchar(255) NOT NULL,
          storage_key varchar(64) NOT NULL UNIQUE,
          sha256 varchar(64) NOT NULL,
          byte_size bigint NOT NULL,
          status varchar(32) NOT NULL DEFAULT 'queued',
          checkpoint_row integer NOT NULL DEFAULT 0,
          source_record_count integer NOT NULL DEFAULT 0,
          mapped_record_count integer NOT NULL DEFAULT 0,
          created_record_count integer NOT NULL DEFAULT 0,
          updated_record_count integer NOT NULL DEFAULT 0,
          existing_record_count integer NOT NULL DEFAULT 0,
          skipped_record_count integer NOT NULL DEFAULT 0,
          warning_count integer NOT NULL DEFAULT 0,
          error_count integer NOT NULL DEFAULT 0,
          result jsonb NOT NULL DEFAULT '{}'::jsonb,
          last_error_type varchar(255),
          requested_by varchar(255) NOT NULL,
          locked_at timestamptz,
          locked_by varchar(255),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT uq_mapped_import_job_source UNIQUE (project_id, profile_id, sha256),
          CONSTRAINT ck_mapped_import_job_status CHECK (
            status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')
          ),
          CONSTRAINT ck_mapped_import_job_entity CHECK (entity_type IN ('requirement', 'test_case'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_mapped_import_jobs_project ON mapped_import_jobs(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mapped_import_jobs_profile ON mapped_import_jobs(profile_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mapped_import_jobs_status ON mapped_import_jobs(status)")


def downgrade() -> None:
    raise RuntimeError(
        "Import jobs contain durable progress and audit evidence. "
        "Restore a verified backup into a replacement database instead."
    )
