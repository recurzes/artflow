"""
WIP -> delivery -> completion -> review, driven with fake Discord objects.
"""
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.commissions import completion
from bot.commissions.cog import CommissionCog
from bot.commissions.completion import ReviewPromptView, announce_completed, submit_review
from bot.commissions.formatting import attached
from bot.shared import layout
from bot.shared.api_client import APIError
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
    ticket = make_channel(5001)
    showcase, reviews = make_channel(SHOWCASE_ID), make_channel(REVIEWS_ID)
    member = make_member(user_id)
    guild = make_guild(member)
    guild.get_channel = lambda channel_id: {SHOWCASE_ID: showcase, REVIEWS_ID: reviews}.get(
        channel_id
    )
    # what the bot last learned about this server from the API
    layout.remember(
        guild.id,
        {"channel_completed_works": str(SHOWCASE_ID), "channel_reviews": str(REVIEWS_ID)},
    )
    interaction = make_interaction(member, guild=guild, channel=ticket, api=api)
    return interaction, api, ticket, showcase, reviews


def test_attached_files_get_a_name_an_embed_can_reference():
    file, name = attached(b"x", "My Sketch (v2).PNG", "wip")
    assert name == "wip.png"
    assert file.filename == "wip.png"
    assert attached(b"x", "no-extension", "final")[1] == "final"
    assert attached(b"x", "weird.p n g", "final")[1] == "final"


class TestWip:
    async def _wip(self, interaction, attachment, note="first sketch") -> None:
        cog_instance = CommissionCog(interaction.client)
        await cog_instance.wip.callback(cog_instance, interaction, attachment, note)

    async def test_the_client_sees_the_image_in_the_ticket(self):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "IN_PROGRESS")

        await self._wip(interaction, _attachment())

        api.post_wip.assert_awaited_once_with(
            "commission-uuid",
            actor=ARTIST_ID,
            filename="My Sketch (v2).PNG",
            content=b"image-bytes",
            content_type="image/png",
            note="first sketch",
        )
        sent = ticket.send.await_args.kwargs
        assert sent["file"].filename == "wip.png"
        assert sent["embed"].image.url == "attachment://wip.png"
        assert sent["content"] == f"<@{CLIENT_ID}>"

    async def test_nothing_is_stored_before_payment(self):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "PAYMENT_PENDING")

        await self._wip(interaction, _attachment())

        api.post_wip.assert_not_awaited()
        ticket.send.assert_not_awaited()
        assert "once payment is confirmed" in reply_text(interaction)

    async def test_only_images_are_accepted(self):
        interaction, api, _, _, _ = _scene(ARTIST_ID, "WIP")

        await self._wip(interaction, _attachment("notes.pdf", content_type="application/pdf"))

        api.post_wip.assert_not_awaited()

    async def test_the_api_refusing_the_actor_is_relayed(self):
        interaction, api, ticket, _, _ = _scene(CLIENT_ID, "WIP")
        api.post_wip.side_effect = APIError(403, "Only the artist can post a WIP update")

        await self._wip(interaction, _attachment())

        ticket.send.assert_not_awaited()
        assert "Only the artist" in reply_text(interaction)


class TestDeliver:
    async def _deliver(self, interaction, attachment) -> None:
        cog_instance = CommissionCog(interaction.client)
        await cog_instance.deliver.callback(cog_instance, interaction, attachment)

    async def test_the_final_file_is_posted_with_the_auto_accept_time(self):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "WIP")
        api.deliver.return_value = _commission(
            "DELIVERED", delivery_auto_accept_at="2026-10-14T12:00:00Z"
        )

        await self._deliver(interaction, _attachment("final.png"))

        api.deliver.assert_awaited_once_with(
            "commission-uuid",
            actor=ARTIST_ID,
            filename="final.png",
            content=b"image-bytes",
            content_type="image/png",
        )
        sent = ticket.send.await_args.kwargs
        assert sent["file"].filename == "final.png"
        assert "/complete" in sent["embed"].description
        assert "<t:" in sent["embed"].description

    async def test_any_file_type_can_be_delivered(self):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "WIP")
        api.deliver.return_value = _commission("DELIVERED")

        await self._deliver(interaction, _attachment("layers.zip", content_type="application/zip"))

        sent = ticket.send.await_args.kwargs
        assert sent["file"].filename == "final.zip"
        assert not sent["embed"].image  # nothing to preview

    async def test_delivery_needs_a_wip_first(self):
        interaction, api, _, _, _ = _scene(ARTIST_ID, "IN_PROGRESS")

        await self._deliver(interaction, _attachment())

        api.deliver.assert_not_awaited()
        assert "/wip" in reply_text(interaction)


class TestComplete:
    @pytest.fixture
    def download(self, monkeypatch):
        download = AsyncMock(return_value=b"png-bytes")
        monkeypatch.setattr(completion, "download", download)
        return download

    async def test_completion_invites_a_review_and_showcases_the_piece(self, download):
        interaction, api, ticket, showcase, _ = _scene(CLIENT_ID, "DELIVERED")
        api.complete.return_value = _commission(
            "COMPLETED", delivery_file_key="wip/commission-uuid/final/b.png"
        )
        api.get_commission_files.return_value = {
            "receipt_url": None,
            "delivery_url": "https://signed.example/final.png?token=abc",
        }
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.complete_cmd.callback(cog_instance, interaction)

        assert isinstance(ticket.send.await_args.kwargs["view"], ReviewPromptView)
        assert ticket.edit.await_args.kwargs["name"].startswith("closed-")
        download.assert_awaited_once_with("https://signed.example/final.png?token=abc")
        # attached, so the showcase post does not depend on a link that expires
        posted = showcase.send.await_args.kwargs
        assert posted["file"].filename == "completed.png"
        assert posted["embed"].image.url == "attachment://completed.png"

    async def test_non_image_deliveries_are_showcased_without_a_file(self, download):
        interaction, api, ticket, showcase, _ = _scene(CLIENT_ID, "DELIVERED")

        await announce_completed(
            api,
            interaction.guild,
            ticket,
            _commission("COMPLETED", delivery_file_key="wip/commission-uuid/final/layers.zip"),
        )

        download.assert_not_awaited()
        posted = showcase.send.await_args.kwargs
        assert "file" not in posted
        assert not posted["embed"].image

    async def test_showcase_still_posts_when_the_file_cannot_be_fetched(self, download):
        interaction, api, ticket, showcase, _ = _scene(CLIENT_ID, "DELIVERED")
        api.get_commission_files.return_value = {"delivery_url": "https://signed.example/x.png"}
        download.return_value = None

        await announce_completed(
            api,
            interaction.guild,
            ticket,
            _commission("COMPLETED", delivery_file_key="wip/commission-uuid/final/b.png"),
        )

        assert "file" not in showcase.send.await_args.kwargs

    async def test_nsfw_work_is_never_showcased(self):
        interaction, api, ticket, showcase, _ = _scene(CLIENT_ID, "DELIVERED")

        await announce_completed(
            api, interaction.guild, ticket, _commission("COMPLETED", is_nsfw=True)
        )

        ticket.send.assert_awaited_once()
        showcase.send.assert_not_awaited()

    async def test_the_api_refusing_the_actor_is_relayed(self):
        interaction, api, ticket, _, _ = _scene(ARTIST_ID, "DELIVERED")
        api.complete.side_effect = APIError(403, "Only the client can accept the delivery")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.complete_cmd.callback(cog_instance, interaction)

        api.complete.assert_awaited_once_with("commission-uuid", actor=ARTIST_ID)
        ticket.send.assert_not_awaited()
        assert "Only the client can accept the delivery" in reply_text(interaction)


class TestReview:
    async def test_review_is_saved_and_published(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")

        await submit_review(interaction, _commission("COMPLETED"), 5, "Lovely")

        api.review.assert_awaited_once_with(
            "commission-uuid", actor=CLIENT_ID, rating=5, body="Lovely"
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
        api.get_artist.side_effect = APIError(503, "unavailable")

        await submit_review(interaction, _commission("COMPLETED"), 5, None)

        assert "Thank you" in reply_text(interaction)

    async def test_review_command_uses_the_same_flow(self):
        interaction, api, _, _, reviews = _scene(CLIENT_ID, "COMPLETED")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.review_cmd.callback(cog_instance, interaction, 3, "")

        api.review.assert_awaited_once_with(
            "commission-uuid", actor=CLIENT_ID, rating=3, body=None
        )
        reviews.send.assert_awaited_once()

    async def test_review_button_waits_for_completion(self):
        interaction, api, _, _, _ = _scene(CLIENT_ID, "DELIVERED")
        interaction.response.is_done.return_value = False
        view = ReviewPromptView()

        await view.review_btn.callback(interaction)

        interaction.response.send_modal.assert_not_awaited()
        assert "once it is completed" in reply_text(interaction)
