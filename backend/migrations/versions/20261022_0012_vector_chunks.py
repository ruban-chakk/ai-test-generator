"""Track logical vector chunks.

Revision ID: 20261022_0012
Revises: 20261021_0011
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0012"
down_revision = "20261021_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_chunks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          aggregate_type varchar(64) NOT NULL,
          aggregate_id uuid NOT NULL,
          entity_type varchar(32) NOT NULL,
          entity_id uuid NOT NULL,
          vector_id varchar(512) NOT NULL,
          chunk_index integer NOT NULL,
          chunk_count integer NOT NULL,
          content_sha256 varchar(64) NOT NULL,
          indexed_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_vector_chunk_aggregate_index UNIQUE (aggregate_type, aggregate_id, chunk_index),
          CONSTRAINT uq_vector_chunk_vector_id UNIQUE (vector_id),
          CONSTRAINT ck_vector_chunk_index CHECK (chunk_index >= 0),
          CONSTRAINT ck_vector_chunk_count CHECK (chunk_count > 0 AND chunk_index < chunk_count)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_vector_chunks_project ON vector_chunks(project_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vector_chunks_aggregate "
        "ON vector_chunks(aggregate_type, aggregate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_vector_chunks_entity "
        "ON vector_chunks(entity_type, entity_id)"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Vector chunk inventory is operational recovery evidence. "
        "Restore a verified backup into a replacement database instead."
    )
