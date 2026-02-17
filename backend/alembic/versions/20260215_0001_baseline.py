"""baseline schema marker

Revision ID: 20260215_0001
Revises:
Create Date: 2026-02-15 10:00:00
"""

from __future__ import annotations

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "20260215_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline marker for existing environments.
    pass


def downgrade() -> None:
    pass
