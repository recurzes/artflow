"""
Tests for the /admin reporting endpoints.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from shared.models.artist import ArtistStatus
from shared.models.commission import CommissionStatus
from tests.factories import make_artist, make_commission, make_server

S = CommissionStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def test_stats_count_only_this_servers_commissions(client, db):
    server = await make_server(db)
    artist = await make_artist(db, server=server)
    await make_commission(db, artist=artist, status=S.IN_PROGRESS)
    await make_commission(db, artist=artist, status=S.DISPUTED)
    await make_commission(db, artist=artist, status=S.CANCELLED)
    await make_commission(
        db, artist=artist, status=S.COMPLETED, completed_at=_now(), platform_fee_php=45
    )
    await make_commission(
        db,
        artist=artist,
        status=S.COMPLETED,
        completed_at=_now() - timedelta(days=70),
        platform_fee_php=900,
    )
    await make_commission(db, status=S.IN_PROGRESS)  # another server

    response = await client.get("/admin/stats", params={"server_id": str(server.id)})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "active_commissions": 2,
        "completed_today": 1,
        "revenue_php_this_month": "45.00",
    }


async def test_roster_lists_every_status_with_active_counts(client, db):
    server = await make_server(db)
    busy = await make_artist(db, server=server, display_name="Aki")
    await make_artist(db, server=server, display_name="Ben", status=ArtistStatus.PENDING)
    idle = await make_artist(db, server=server, display_name="Cy", nsfw_enabled=True)
    await make_commission(db, artist=busy, status=S.WIP)
    await make_commission(db, artist=busy, status=S.QUOTED)
    await make_commission(db, artist=busy, status=S.COMPLETED)
    await make_artist(db, display_name="Elsewhere")

    response = await client.get("/admin/artists", params={"server_id": str(server.id)})

    assert response.status_code == 200, response.text
    rows = response.json()["artists"]
    assert [(r["display_name"], r["status"], r["active_commission_count"]) for r in rows] == [
        ("Aki", "ACTIVE", 2),
        ("Ben", "PENDING", 0),
        ("Cy", "ACTIVE", 0),
    ]
    assert rows[2]["id"] == str(idle.id)
    assert rows[2]["nsfw_enabled"] is True


async def test_roster_is_paginated(client, db):
    server = await make_server(db)
    for name in ("A", "B", "C"):
        await make_artist(db, server=server, display_name=name)

    response = await client.get(
        "/admin/artists", params={"server_id": str(server.id), "limit": 2, "offset": 1}
    )

    data = response.json()
    assert [a["display_name"] for a in data["artists"]] == ["B", "C"]
    assert (data["limit"], data["offset"]) == (2, 1)


async def test_roster_does_not_run_a_query_per_artist(client, db, engine):
    server = await make_server(db)
    for index in range(6):
        await make_artist(db, server=server, display_name=f"Artist {index}")

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        response = await client.get("/admin/artists", params={"server_id": str(server.id)})
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)

    assert len(response.json()["artists"]) == 6
    assert len(statements) == 1, statements


async def test_summary_groups_by_status(client, db):
    server = await make_server(db)
    artist = await make_artist(db, server=server)
    await make_commission(db, artist=artist, status=S.INTAKE)
    await make_commission(db, artist=artist, status=S.INTAKE)
    await make_commission(db, artist=artist, status=S.DELIVERED)

    response = await client.get("/admin/commissions/summary", params={"server_id": str(server.id)})

    assert response.json() == {"by_status": {"INTAKE": 2, "DELIVERED": 1}}
