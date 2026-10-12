"""
End-to-end walks through the commission lifecycle, using only the HTTP API the
bot uses. If these pass, a commission can get from request to review.
"""
from tests.conftest import make_discord_id

TOS = "50% refund before the sketch, none after."


class Scene:
    """A registered server with one artist and one client, built through the API."""

    def __init__(self, client) -> None:
        self.client = client

    async def post(self, path: str, json: dict | None = None, *, expect: int = 200) -> dict:
        response = await self.client.post(path, json=json)
        assert response.status_code == expect, f"{path}: {response.status_code} {response.text}"
        return response.json()

    async def get(self, path: str) -> dict:
        response = await self.client.get(path)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        return response.json()

    async def build(self) -> "Scene":
        self.server = await self.post(
            "/servers",
            {"discord_guild_id": make_discord_id(), "name": "Art Hub"},
            expect=201,
        )
        self.artist_user = await self.post("/users", {"discord_user_id": make_discord_id()})
        self.buyer = await self.post("/users", {"discord_user_id": make_discord_id()})
        self.artist = await self.post(
            "/artists",
            {
                "user_id": self.artist_user["id"],
                "server_id": self.server["id"],
                "display_name": "Mika",
                "styles": ["anime"],
                "gcash_number": "09171234567",
            },
            expect=201,
        )
        response = await self.client.patch(
            f"/artists/{self.artist['id']}", json={"tos_text": TOS}
        )
        assert response.status_code == 200, response.text
        self.artist = response.json()
        return self

    async def open_commission(self) -> dict:
        commission = await self.post(
            "/commissions",
            {
                "server_id": self.server["id"],
                "artist_id": self.artist["id"],
                "client_id": self.buyer["id"],
            },
            expect=201,
        )
        self.base = f"/commissions/{commission['id']}"
        self.channel_id = make_discord_id()
        return await self.post(
            f"{self.base}/ticket", {"discord_ticket_channel_id": self.channel_id}
        )

    async def advance_to_in_progress(self) -> dict:
        await self.open_commission()
        await self.post(f"{self.base}/intake", {"notes": "A portrait of my cat, anime style"})
        await self.post(f"{self.base}/quote", {"quoted_price_php": "1500.00"})
        await self.post(f"{self.base}/accept-quote")
        await self.post(f"{self.base}/tos-accept", {"tos_version_hash": self.artist["tos_hash"]})
        await self.post(f"{self.base}/receipt", {"payment_receipt_url": "receipts/proof.png"})
        return await self.post(f"{self.base}/confirm-payment")


async def test_commission_from_request_to_review(client):
    scene = await Scene(client).build()

    commission = await scene.open_commission()
    assert commission["status"] == "INTAKE"
    by_channel = await scene.get(f"/commissions/by-discord-channel/{scene.channel_id}")
    assert by_channel["id"] == commission["id"]

    assert (await scene.post(f"{scene.base}/intake", {"notes": "A cat"}))["status"] == "INTAKE"
    quoted = await scene.post(f"{scene.base}/quote", {"quoted_price_php": "1500.00"})
    assert quoted["status"] == "QUOTED"

    # The client pushes back once; the artist re-quotes.
    assert (
        await scene.post(f"{scene.base}/counter-offer", {"notes": "1200?"})
    )["status"] == "INTAKE"
    requoted = await scene.post(f"{scene.base}/quote", {"quoted_price_php": "1300.00"})
    assert float(requoted["quoted_price_php"]) == 1300.0

    assert (await scene.post(f"{scene.base}/accept-quote"))["status"] == "TOS_PENDING"
    pending = await scene.post(
        f"{scene.base}/tos-accept", {"tos_version_hash": scene.artist["tos_hash"]}
    )
    assert pending["status"] == "PAYMENT_PENDING"
    assert pending["payment_deadline_at"] is not None

    await scene.post(f"{scene.base}/receipt", {"payment_receipt_url": "receipts/proof.png"})
    paid = await scene.post(f"{scene.base}/confirm-payment")
    assert paid["status"] == "IN_PROGRESS"
    assert paid["payment_confirmed_at"] is not None

    assert (
        await scene.post(f"{scene.base}/wip-update", {"image_url": "wip/sketch.png"})
    )["status"] == "WIP"
    assert (
        await scene.post(f"{scene.base}/wip-update", {"image_url": "wip/colour.png"})
    )["status"] == "WIP"

    delivered = await scene.post(f"{scene.base}/deliver", {"final_file_url": "wip/final.png"})
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivery_auto_accept_at"] is not None

    done = await scene.post(f"{scene.base}/complete")
    assert done["status"] == "COMPLETED"
    assert float(done["platform_fee_php"]) == 39.0  # 3% of 1300

    await scene.post(
        f"{scene.base}/review",
        {"reviewer_id": scene.buyer["id"], "rating": 5, "body": "Perfect"},
        expect=201,
    )
    artist = await scene.get(f"/artists/{scene.artist['id']}")
    assert float(artist["rating_avg"]) == 5.0
    assert artist["rating_count"] == 1

    capacity = await scene.get(f"/artists/{scene.artist['id']}/active-commission-count")
    assert capacity["count"] == 0  # a completed commission no longer occupies a slot


async def test_steps_cannot_be_skipped(client):
    scene = await Scene(client).build()
    await scene.open_commission()

    # Straight from the brief to payment, delivery or completion: all refused.
    for path, body in (
        ("accept-quote", None),
        ("tos-accept", {"tos_version_hash": scene.artist["tos_hash"]}),
        ("confirm-payment", None),
        ("deliver", {"final_file_url": "wip/final.png"}),
        ("complete", None),
    ):
        response = await client.post(f"{scene.base}/{path}", json=body)
        assert response.status_code == 409, f"{path}: {response.text}"

    assert (await scene.get(scene.base))["status"] == "INTAKE"


async def test_dispute_freezes_the_commission_until_resolved(client):
    scene = await Scene(client).build()
    await scene.advance_to_in_progress()
    await scene.post(f"{scene.base}/wip-update", {"image_url": "wip/sketch.png"})

    dispute = await scene.post(
        "/disputes",
        {
            "commission_id": scene.base.rsplit("/", 1)[1],
            "raised_by_discord_user_id": scene.buyer["discord_user_id"],
            "reason": "The sketch is not what we agreed",
        },
        expect=201,
    )
    assert (await scene.get(scene.base))["status"] == "DISPUTED"

    # Frozen: neither side can move it forward.
    for path, body in (
        ("wip-update", {"image_url": "wip/again.png"}),
        ("deliver", {"final_file_url": "wip/final.png"}),
        ("complete", None),
    ):
        response = await client.post(f"{scene.base}/{path}", json=body)
        assert response.status_code == 409, f"{path}: {response.text}"
        assert "dispute" in response.json()["detail"]

    response = await client.patch(
        f"/disputes/{dispute['id']}/resolve",
        json={
            "resolution": "Refund agreed between both parties",
            "set_commission_status": "CANCELLED",
            "resolved_by_discord_user_id": make_discord_id(),
        },
    )
    assert response.status_code == 200, response.text
    assert (await scene.get(scene.base))["status"] == "CANCELLED"

    # A cancelled commission cannot be reviewed.
    review = await client.post(
        f"{scene.base}/review", json={"reviewer_id": scene.buyer["id"], "rating": 1}
    )
    assert review.status_code == 409


async def test_artist_at_capacity_frees_a_slot_when_a_commission_ends(client):
    scene = await Scene(client).build()
    response = await client.patch(
        f"/artists/{scene.artist['id']}", json={"max_active_commissions": 1}
    )
    assert response.status_code == 200
    await scene.advance_to_in_progress()

    second_buyer = await scene.post("/users", {"discord_user_id": make_discord_id()})
    body = {
        "server_id": scene.server["id"],
        "artist_id": scene.artist["id"],
        "client_id": second_buyer["id"],
    }
    assert (await client.post("/commissions", json=body)).status_code == 409

    await scene.post(f"{scene.base}/wip-update", {"image_url": "wip/sketch.png"})
    await scene.post(f"{scene.base}/deliver", {"final_file_url": "wip/final.png"})
    await scene.post(f"{scene.base}/complete")

    assert (await client.post("/commissions", json=body)).status_code == 201
