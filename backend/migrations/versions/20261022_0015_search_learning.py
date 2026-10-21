"""Add search telemetry, judgments, saved searches, and fuzzy matching.

Revision ID: 20261022_0015
Revises: 20261022_0014
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0015"
down_revision = "20261022_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_events (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          query text NOT NULL,
          mode varchar(32) NOT NULL,
          entity_type varchar(32),
          result_count integer NOT NULL DEFAULT 0,
          "offset" integer NOT NULL DEFAULT 0,
          latency_ms integer NOT NULL DEFAULT 0,
          semantic_fallback boolean NOT NULL DEFAULT false,
          requested_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_search_events_project ON search_events(project_id);
        CREATE INDEX IF NOT EXISTS idx_search_events_created ON search_events(created_at);

        CREATE TABLE IF NOT EXISTS search_judgments (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          search_event_id uuid NOT NULL REFERENCES search_events(id) ON DELETE CASCADE,
          entity_type varchar(32) NOT NULL,
          entity_id varchar(255) NOT NULL,
          rank integer NOT NULL,
          judgment varchar(32) NOT NULL,
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_search_judgment_result UNIQUE (search_event_id, entity_type, entity_id),
          CONSTRAINT ck_search_judgment_value CHECK (judgment IN ('clicked', 'relevant', 'not_relevant')),
          CONSTRAINT ck_search_judgment_rank CHECK (rank > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_search_judgments_event ON search_judgments(search_event_id);

        CREATE TABLE IF NOT EXISTS saved_searches (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name varchar(255) NOT NULL,
          query text NOT NULL,
          mode varchar(32) NOT NULL DEFAULT 'hybrid',
          entity_type varchar(32),
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_saved_search_owner_name UNIQUE (project_id, created_by, name),
          CONSTRAINT ck_saved_search_mode CHECK (mode IN ('semantic', 'keyword', 'hybrid'))
        );
        CREATE INDEX IF NOT EXISTS idx_saved_searches_project ON saved_searches(project_id);
        CREATE INDEX IF NOT EXISTS idx_saved_searches_owner ON saved_searches(created_by);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_searches")
    op.execute("DROP TABLE IF EXISTS search_judgments")
    op.execute("DROP TABLE IF EXISTS search_events")
