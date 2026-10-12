"""store storage keys instead of signed URLs

Uploaded files were recorded as signed URLs, which expire. The columns now hold
"<bucket>/<path>" references that are signed when read. Rows written before
this revision keep their (already or soon expired) URLs; readers pass those
through unchanged.

Revision ID: e4c7a9d2b1f6
Revises: d3b8e6a1f2c5
Create Date: 2026-10-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4c7a9d2b1f6'
down_revision: Union[str, Sequence[str], None] = 'd3b8e6a1f2c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RENAMES = (
    ('commissions', 'payment_receipt_url', 'payment_receipt_key'),
    ('commissions', 'delivery_file_url', 'delivery_file_key'),
    ('wip_updates', 'image_url', 'image_key'),
    ('wip_updates', 'watermarked_url', 'watermarked_key'),
)


def upgrade() -> None:
    """Upgrade schema."""
    for table, old, new in RENAMES:
        op.alter_column(table, old, new_column_name=new)


def downgrade() -> None:
    """Downgrade schema."""
    for table, old, new in RENAMES:
        op.alter_column(table, new, new_column_name=old)
