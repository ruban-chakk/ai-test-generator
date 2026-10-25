"""Add durable bulk requirement operation jobs.

Revision ID: 20261025_0028
Revises: 20261023_0027
"""
from alembic import op


revision = "20261025_0028"
down_revision = "20261023_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bulk_operation_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            operation_type varchar(64) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'queued',
            requirement_ids json NOT NULL DEFAULT '[]'::json,
            total_count integer NOT NULL DEFAULT 0,
            completed_count integer NOT NULL DEFAULT 0,
            failed_count integer NOT NULL DEFAULT 0,
            result json NOT NULL DEFAULT '{}'::json,
            last_error_type varchar(255),
            requested_by varchar(255) NOT NULL,
            locked_at timestamp NULL,
            locked_by varchar(255) NULL,
            created_at timestamp NOT NULL DEFAULT now(),
            updated_at timestamp NOT NULL DEFAULT now(),
            completed_at timestamp NULL
        );
        CREATE INDEX ix_bulk_operation_jobs_project_id ON bulk_operation_jobs(project_id);
        CREATE INDEX ix_bulk_operation_jobs_status ON bulk_operation_jobs(status);
        CREATE INDEX ix_bulk_operation_jobs_operation_type ON bulk_operation_jobs(operation_type);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bulk_operation_jobs;")
