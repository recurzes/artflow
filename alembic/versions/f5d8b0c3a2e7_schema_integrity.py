"""schema integrity: uniques, indexes and a missing default

- one artist profile per member per server
- one commission per ticket channel (and an index for the lookup that every
  command in a ticket performs)
- indexes on the foreign keys and deadlines that are filtered or joined on
- a server default for commissions.payment_reminder_sent, which was added as
  NOT NULL without one

If this fails on a unique constraint, the table already contains duplicates:
find them, merge or remove them, and run it again. The whole revision is one
transaction, so a failure changes nothing.

Revision ID: f5d8b0c3a2e7
Revises: e4c7a9d2b1f6
Create Date: 2026-10-13 00:04:54.261664

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5d8b0c3a2e7'
down_revision: Union[str, Sequence[str], None] = 'e4c7a9d2b1f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_artists_server_id'), 'artists', ['server_id'], unique=False)
    op.create_unique_constraint('uq_artist_user_server', 'artists', ['user_id', 'server_id'])
    op.create_index(op.f('ix_commissions_artist_id'), 'commissions', ['artist_id'], unique=False)
    op.create_index(op.f('ix_commissions_client_id'), 'commissions', ['client_id'], unique=False)
    op.create_index(
        op.f('ix_commissions_delivery_auto_accept_at'),
        'commissions',
        ['delivery_auto_accept_at'],
        unique=False,
    )
    op.create_index(
        op.f('ix_commissions_discord_ticket_channel_id'),
        'commissions',
        ['discord_ticket_channel_id'],
        unique=True,
    )
    op.create_index(
        op.f('ix_commissions_payment_deadline_at'),
        'commissions',
        ['payment_deadline_at'],
        unique=False,
    )
    op.create_index(op.f('ix_commissions_server_id'), 'commissions', ['server_id'], unique=False)
    op.create_index(op.f('ix_reviews_artist_id'), 'reviews', ['artist_id'], unique=False)
    op.create_index(
        op.f('ix_wip_updates_commission_id'), 'wip_updates', ['commission_id'], unique=False
    )
    op.alter_column('commissions', 'payment_reminder_sent', server_default=sa.false())


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('commissions', 'payment_reminder_sent', server_default=None)
    op.drop_index(op.f('ix_wip_updates_commission_id'), table_name='wip_updates')
    op.drop_index(op.f('ix_reviews_artist_id'), table_name='reviews')
    op.drop_index(op.f('ix_commissions_server_id'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_payment_deadline_at'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_discord_ticket_channel_id'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_delivery_auto_accept_at'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_client_id'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_artist_id'), table_name='commissions')
    op.drop_constraint('uq_artist_user_server', 'artists', type_='unique')
    op.drop_index(op.f('ix_artists_server_id'), table_name='artists')
