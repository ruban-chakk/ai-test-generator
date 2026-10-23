"""Persist user interface preferences.

Revision ID: 20261022_0019
Revises: 20261022_0018
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0019"
down_revision = "20261022_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS settings jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS settings")
