"""artist applications are stored as artist rows

Adds the REJECTED status and the two columns that record a rejection, so an
application no longer lives only in a Discord message.

Revision ID: d3b8e6a1f2c5
Revises: c1a2f0b7d9e4
Create Date: 2026-10-12 19:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd3b8e6a1f2c5'
down_revision: Union[str, Sequence[str], None] = 'c1a2f0b7d9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE artiststatus ADD VALUE IF NOT EXISTS 'REJECTED'")
    op.add_column('artists', sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('artists', sa.Column('rejection_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL cannot drop a value from an enum type; 'REJECTED' stays behind unused.
    op.drop_column('artists', 'rejection_reason')
    op.drop_column('artists', 'rejected_at')
