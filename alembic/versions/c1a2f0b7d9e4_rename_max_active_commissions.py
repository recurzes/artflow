"""rename artists.max_active_commission to max_active_commissions

The schemas and every reader use the plural name; the column was the odd one out.

Revision ID: c1a2f0b7d9e4
Revises: a8070a11f489
Create Date: 2026-10-12 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1a2f0b7d9e4'
down_revision: Union[str, Sequence[str], None] = 'a8070a11f489'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('artists', 'max_active_commission', new_column_name='max_active_commissions')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('artists', 'max_active_commissions', new_column_name='max_active_commission')
