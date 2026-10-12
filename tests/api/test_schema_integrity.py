"""
What the database itself guarantees, independent of the service layer.
"""
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from shared.models.artist import Artist
from shared.models.commission import Commission, CommissionStatus
from tests.conftest import ROOT, make_discord_id
from tests.factories import make_artist, make_commission, make_server, make_user

S = CommissionStatus


async def test_one_artist_profile_per_member_per_server(db):
    server, other_server, user = await make_server(db), await make_server(db), await make_user(db)
    server_id, other_server_id, user_id = server.id, other_server.id, user.id
    await make_artist(db, server=server, user=user)

    db.add(Artist(user_id=user_id, server_id=server_id, display_name="Duplicate"))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()

    # the same member can be an artist on another server
    db.add(Artist(user_id=user_id, server_id=other_server_id, display_name="Elsewhere"))
    await db.flush()


async def test_one_commission_per_ticket_channel(db):
    channel_id = make_discord_id()
    first = await make_commission(db, discord_ticket_channel_id=channel_id)
    ids = {
        "server_id": first.server_id,
        "artist_id": first.artist_id,
        "client_id": first.client_id,
    }

    db.add(Commission(**ids, status=S.INQUIRY, discord_ticket_channel_id=channel_id))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()

    # commissions that have no ticket yet do not collide with each other
    db.add(Commission(**ids, status=S.INQUIRY, discord_ticket_channel_id=None))
    db.add(Commission(**ids, status=S.INQUIRY, discord_ticket_channel_id=None))
    await db.flush()


async def test_api_refuses_a_ticket_channel_that_is_taken(client, db):
    channel_id = make_discord_id()
    await make_commission(db, status=S.INTAKE, discord_ticket_channel_id=channel_id)
    waiting = await make_commission(db, status=S.INQUIRY, discord_ticket_channel_id=None)

    response = await client.post(
        f"/commissions/{waiting.id}/ticket", json={"discord_ticket_channel_id": channel_id}
    )

    assert response.status_code == 409
    assert "already the ticket" in response.json()["detail"]


async def test_payment_reminder_flag_has_a_database_default(db):
    commission = await make_commission(db)

    new_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO commissions "
            "(id, server_id, artist_id, client_id, status, is_nsfw, revisions_used, "
            "revisions_allowed) "
            "VALUES (:id, :server, :artist, :client, 'INQUIRY', false, 0, 2)"
        ),
        {
            "id": new_id,
            "server": commission.server_id,
            "artist": commission.artist_id,
            "client": commission.client_id,
        },
    )

    flag = await db.scalar(
        text("SELECT payment_reminder_sent FROM commissions WHERE id = :id"), {"id": new_id}
    )
    assert flag is False


async def test_updated_at_moves_when_a_row_changes(client, db):
    artist = await make_artist(db)
    before = (await client.get(f"/artists/{artist.id}")).json()

    await client.patch(f"/artists/{artist.id}", json={"bio": "Now taking chibi commissions"})

    after = (await client.get(f"/artists/{artist.id}")).json()
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] > before["updated_at"]


# The revisions that existed before this test did. Their own downgrades leave the
# enum types behind, so the round trip stops there instead of going to base.
OLDEST_REVERSIBLE = "a8070a11f489"


def test_newer_migrations_can_be_reversed_and_reapplied(_schema):
    env = os.environ.copy()
    for command in (["downgrade", OLDEST_REVERSIBLE], ["upgrade", "head"]):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
