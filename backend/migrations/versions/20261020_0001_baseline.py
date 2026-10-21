"""Create the AI test generator application schema.

Revision ID: 20261020_0001
Revises: None
Create Date: 2026-10-20
"""
from pathlib import Path

from alembic import op


revision = "20261020_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema_file = Path(__file__).resolve().parents[1] / "001_create_schema.sql"
    op.get_bind().exec_driver_sql(schema_file.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise RuntimeError(
        "The baseline owns durable application and audit data and has no automatic downgrade. "
        "Restore a verified backup into a replacement database instead."
    )
