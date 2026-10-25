"""Add durable bulk-operation controls."""
from alembic import op

revision = "20261026_0029"
down_revision = "20261025_0028"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("ALTER TABLE bulk_operation_jobs ADD COLUMN IF NOT EXISTS cancel_requested boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE bulk_operation_jobs ADD COLUMN IF NOT EXISTS max_concurrency integer NOT NULL DEFAULT 1")

def downgrade() -> None:
    op.execute("ALTER TABLE bulk_operation_jobs DROP COLUMN IF EXISTS max_concurrency")
    op.execute("ALTER TABLE bulk_operation_jobs DROP COLUMN IF EXISTS cancel_requested")
