"""
WIP -> delivery -> completion -> review, driven with fake Discord objects.
"""
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.cogs import commission as cog
from bot.cogs.commission import (
    CommissionCog,
    ReviewPromptView,
    _attached,
    announce_completed,
    submit_review,
)
from bot.utils.api_client import APIError
from tests.bot.fakes import (
    make_channel,
    make_guild,
    make_interaction,
    make_member,
    reply_text,
    sent_embeds,
)

CLIENT_ID, ARTIST_ID = 1001, 2002
SHOWCASE_ID, REVIEWS_ID = 7001, 7002


def _commission(status: str, **extra) -> dict:
    return {
        "id": "commission-uuid",
        "artist_id": "artist-uuid",
        "client_id": "client-uuid",
        "status": status,
        "is_nsfw": False,
        "client_discord_user_id": str(CLIENT_ID),
        "artist_discord_user_id": str(ARTIST_ID),
        **extra,
    }


def _attachment(
        filename: str = "My Sketch (v2).PNG",
        *,
        content_type: str = "image/png",
        size: int = 2048
) -> MagicMock:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = filename
    attachment.content_type = content_type
    attachment.size = size
    attachment.read = AsyncMock(return_value=b"image-bytes")
    return attachment


def _scene(user_id: int, status: str, **commission_fields):
    api = AsyncMock()
    api.get_commission_for_channel.return_value = _commission(status, **commission_fields)
    api.get_artist.return_value = {"id": "artist-uuid", "display_name": "Mika"}
    api.get_server.return_value = {
        "settings": {
            "channel_completed_works": str(SHOWCASE_ID),
            "channel_reviews": str(REVIEWS_ID),
        }
    }
    ticket = make_channel(5001)
    showcase, reviews = make_channel(SHOWCASE_ID), make_channel(REVIEWS_ID)
    member = make_member(user_id)
    guild = make_guild(member)
    guild.get_channel = lambda channel_id: {SHOWCASE_ID: showcase, REVIEWS_ID: reviews}.get(
        channel_id
    )
    interaction = make_interaction(member, guild=guild, channel=ticket, api=api)
    return interaction, api, ticket, showcase, reviews


@pytest.fixture
def storage(monkeypatch):
    wip = AsyncMock(return_value="https://storage/wip.png")
    final = AsyncMock(return_value="https://storage/final.png")
    monkeypatch.setattr(cog, "upload_wip_image", wip)
    monkeypatch.setattr(cog, "upload_delivery_file", final)
    return wip, final


def test_attached_files_get_a_name_an_embed_can_reference():
    file, name = _attached(b"x", "My Sketch (v2).PNG", "wip")
    assert name == "wip.png"
    assert file.filename == "wip.png"
    assert _attached(b"x", "no-extension", "final")[1] == "final"
    assert _attached(b"x", "weird.p n g", "final")[1] == "final"


class TestWip:
    async def _wip(self, interaction, attachment, note="first sketch") -> None:
        cog_instance = CommissionCog(interaction.client)
        await cog_instance.wip.callback(cog_instance, interaction, attachment, note)

    async def test_the_client_sees_the_image_in_the_ticket(self, storage):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "IN_PROGRESS")

        await self._wip(interaction, _attachment())

        api.post_wip.assert_awaited_once_with(
            "commission-uuid", "https://storage/wip.png", "first sketch"
        )
        sent = ticket.send.await_args.kwargs
        assert sent["file"].filename == "wip.png"
        assert sent["embed"].image.url == "attachment://wip.png"
        assert sent["content"] == f"<@{CLIENT_ID}>"

    async def test_nothing_is_stored_before_payment(self, storage):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "PAYMENT_PENDING")

        await self._wip(interaction, _attachment())

        storage[0].assert_not_awaited()
        ticket.send.assert_not_awaited()
        assert "once payment is confirmed" in reply_text(interaction)

    async def test_only_images_are_accepted(self, storage):
        interaction, api, _, _, _ = _scene(ARTIST_ID, "WIP")

        await self._wip(interaction, _attachment("notes.pdf", content_type="application/pdf"))

        storage[0].assert_not_awaited()

    async def test_only_the_artist_can_post(self, storage):
        interaction, api, _, _, _ = _scene(CLIENT_ID, "WIP")

        await self._wip(interaction, _attachment())

        storage[0].assert_not_awaited()
        assert "Only the artist" in reply_text(interaction)


class TestDeliver:
    async def _deliver(self, interaction, attachment) -> None:
        cog_instance = CommissionCog(interaction.client)
        await cog_instance.deliver.callback(cog_instance, interaction, attachment)

    async def test_the_final_file_is_posted_with_the_auto_accept_time(self, storage):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "WIP")
        api.deliver.return_value = _commission(
            "DELIVERED", delivery_auto_accept_at="2026-10-14T12:00:00Z"
        )

        await self._deliver(interaction, _attachment("final.png"))

        api.deliver.assert_awaited_once_with("commission-uuid", "https://storage/final.png")
        sent = ticket.send.await_args.kwargs
        assert sent["file"].filename == "final.png"
        assert "/complete" in sent["embed"].description
        assert "<t:" in sent["embed"].description

    async def test_any_file_type_can_be_delivered(self, storage):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "WIP")
        api.deliver.return_value = _commission("DELIVERED")

        await self._deliver(interaction, _attachment("layers.zip", content_type="application/zip"))

        sent = ticket.send.await_args.kwargs
        assert sent["file"].filename == "final.zip"
        assert not sent["embed"].image  # nothing to preview

    async def test_delivery_needs_a_wip_first(self, storage):
        interaction, api, _, _, _ = _scene(ARTIST_ID, "IN_PROGRESS")

        await self._deliver(interaction, _attachment())

        storage[1].assert_not_awaited()
        assert "/wip" in reply_text(interaction)


class TestComplete:
    async def test_completion_invites_a_review_and_showcases_the_piece(self):
        interaction, api, ticket, showcase, _ = _scene(CLIENT_ID, "DELIVERED")
        api.complete.return_value = _commission(
            "COMPLETED", delivery_file_url="https://storage/final.png"
        )
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.complete_cmd.callback(cog_instance, interaction)

        assert isinstance(ticket.send.await_args.kwargs["view"], ReviewPromptView)
        assert sent_embeds(showcase)[0].image.url == "https://storage/final.png"

    async def test_nsfw_work_is_never_showcased(self):
        interaction, api, ticket, showcase, _ = _scene(CLIENT_ID, "DELIVERED")

        await announce_completed(
            api, interaction.guild, ticket, _commission("COMPLETED", is_nsfw=True)
        )

        ticket.send.assert_awaited_once()
        showcase.send.assert_not_awaited()

    async def test_only_the_client_can_complete(self):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "DELIVERED")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.complete_cmd.callback(cog_instance, interaction)

        api.complete.assert_not_awaited()
        ticket.send.assert_not_awaited()


class TestReview:
    async def test_review_is_saved_and_published(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")

        await submit_review(interaction, _commission("COMPLETED"), 5, "Lovely")

        api.review.assert_awaited_once_with(
            "commission-uuid", reviewer_id="client-uuid", rating=5, body="Lovely"
        )
        published = sent_embeds(reviews)[0]
        assert "Mika" in published.title
        assert "Lovely" in published.description
        assert "Thank you" in reply_text(interaction)

    async def test_nsfw_reviews_stay_private(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")

        await submit_review(interaction, _commission("COMPLETED", is_nsfw=True), 4, None)

        api.review.assert_awaited_once()
        reviews.send.assert_not_awaited()

    async def test_a_refused_review_is_not_published(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")
        api.review.side_effect = APIError(409, "This commission has already been reviewed")

        await submit_review(interaction, _commission("COMPLETED"), 5, None)

        reviews.send.assert_not_awaited()
        assert "already been reviewed" in reply_text(interaction)

    async def test_publishing_failure_does_not_undo_the_thanks(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")
        api.get_server.side_effect = APIError(503, "unavailable")

        await submit_review(interaction, _commission("COMPLETED"), 5, None)

        assert "Thank you" in reply_text(interaction)

    async def test_review_command_uses_the_same_flow(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.review_cmd.callback(cog_instance, interaction, 3, "")

        api.review.assert_awaited_once_with(
            "commission-uuid", reviewer_id="client-uuid", rating=3, body=None
        )
        reviews.send.assert_awaited_once()

    async def test_review_button_waits_for_completion(self):
        interaction, api, _, _, _ = _scene(CLIENT_ID, "DELIVERED")
        interaction.response.is_done.return_value = False
        view = ReviewPromptView()

        await view.review_btn.callback(interaction)

        interaction.response.send_modal.assert_not_awaited()
        assert "once it is completed" in reply_text(interaction)
