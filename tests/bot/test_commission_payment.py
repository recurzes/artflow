"""
Quote -> terms -> payment, driven with fake Discord objects.
"""
import re
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.cogs import commission as cog
from bot.cogs.commission import (
    CommissionCog,
    QuoteActionsView,
    TosAcceptButton,
    accept_quote_flow,
    tos_accept_view,
)
from bot.utils.api_client import APIError
from bot.utils.embeds import payment_instructions_embed
from bot.utils.uploads import MAX_RECEIPT_BYTES, RECEIPT_TYPES, check_attachment
from tests.bot.fakes import (
    make_channel,
    make_guild,
    make_interaction,
    make_member,
    reply_text,
    sent_embeds,
)

CLIENT_ID, ARTIST_ID = 1001, 2002
TOS_HASH = "ab" * 32


def _commission(status: str, **extra) -> dict:
    return {
        "id": "commission-uuid",
        "artist_id": "artist-uuid",
        "status": status,
        "client_discord_user_id": str(CLIENT_ID),
        "artist_discord_user_id": str(ARTIST_ID),
        **extra,
    }


def _artist(**extra) -> dict:
    return {
        "id": "artist-uuid",
        "display_name": "Mika",
        "tos_text": "No refunds after the sketch.",
        "tos_hash": TOS_HASH,
        "gcash_number": "09171234567",
        "paypal_email": None,
        **extra,
    }


def _scene(user_id: int, status: str, *, artist: dict | None = None, **commission_fields):
    api = AsyncMock()
    api.get_commission_for_channel.return_value = _commission(status, **commission_fields)
    api.get_artist.return_value = artist or _artist()
    channel = make_channel()
    member = make_member(user_id)
    interaction = make_interaction(member, guild=make_guild(member), channel=channel, api=api)
    return interaction, api, channel


def _attachment(*, size: int = 1000, content_type: str | None = "image/png") -> MagicMock:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.size = size
    attachment.content_type = content_type
    attachment.filename = "receipt.png"
    attachment.read = AsyncMock(return_value=b"bytes")
    return attachment


class TestAcceptQuote:
    async def test_client_accepts_and_sees_the_terms_with_a_versioned_button(self):
        interaction, api, channel = _scene(CLIENT_ID, "QUOTED")

        await accept_quote_flow(interaction)

        api.accept_quote.assert_awaited_once_with("commission-uuid")
        embed = sent_embeds(channel)[0]
        assert "No refunds after the sketch." in embed.description
        button = channel.send.await_args.kwargs["view"].children[0]
        assert button.custom_id == f"artflow:tos_accept:{TOS_HASH[:16]}"

    async def test_only_the_client_can_accept(self):
        interaction, api, channel = _scene(ARTIST_ID, "QUOTED")

        await accept_quote_flow(interaction)

        api.accept_quote.assert_not_awaited()
        assert "Only the client can accept the quote" in reply_text(interaction)

    async def test_artist_without_terms_is_prompted_and_no_button_is_posted(self):
        interaction, api, channel = _scene(CLIENT_ID, "QUOTED", artist=_artist(tos_text=None))

        await accept_quote_flow(interaction)

        assert "view" not in channel.send.await_args.kwargs
        assert "/settings tos" in sent_embeds(channel)[0].description

    async def test_api_refusal_is_shown_to_the_user(self):
        interaction, api, channel = _scene(CLIENT_ID, "INTAKE")
        api.accept_quote.side_effect = APIError(409, "Accepting the quote is only possible ...")

        await accept_quote_flow(interaction)

        channel.send.assert_not_awaited()
        assert "only possible" in reply_text(interaction)

    async def test_long_terms_are_shown_in_full(self):
        long_terms = "x" * 9000
        interaction, api, channel = _scene(
            CLIENT_ID, "QUOTED", artist=_artist(tos_text=long_terms)
        )

        await accept_quote_flow(interaction)

        shown = "".join(e.description for e in sent_embeds(channel))
        assert shown.count("x") == 9000
        assert [("view" in c.kwargs) for c in channel.send.await_args_list] == [False, False, True]


class TestTosAcceptButton:
    async def test_accepts_the_displayed_version_and_posts_payment_details(self):
        interaction, api, channel = _scene(CLIENT_ID, "TOS_PENDING")
        api.accept_tos.return_value = _commission(
            "PAYMENT_PENDING",
            quoted_price_php="1500.00",
            payment_deadline_at="2026-10-13T12:00:00Z",
        )

        await TosAcceptButton(TOS_HASH[:16]).callback(interaction)

        api.accept_tos.assert_awaited_once_with("commission-uuid", TOS_HASH)
        fields = {f.name: f.value for f in sent_embeds(channel)[0].fields}
        assert fields["Amount due"] == "₱1,500.00 PHP"
        assert fields["GCash number"] == "09171234567"
        assert fields["Pay by"].startswith("<t:")
        assert "PayPal" not in fields

    async def test_refuses_when_the_terms_changed_since_the_message(self):
        interaction, api, channel = _scene(
            CLIENT_ID, "TOS_PENDING", artist=_artist(tos_hash="cd" * 32)
        )

        await TosAcceptButton(TOS_HASH[:16]).callback(interaction)

        api.accept_tos.assert_not_awaited()
        assert "changed their terms" in reply_text(interaction)
        # the current version is posted with a fresh button
        new_button = channel.send.await_args.kwargs["view"].children[0]
        assert new_button.custom_id.endswith("cd" * 8)

    async def test_only_the_client_can_accept(self):
        interaction, api, _ = _scene(ARTIST_ID, "TOS_PENDING")

        await TosAcceptButton(TOS_HASH[:16]).callback(interaction)

        api.accept_tos.assert_not_awaited()

    async def test_button_is_restored_from_its_custom_id(self):
        button = tos_accept_view(TOS_HASH).children[0]
        match = re.fullmatch(TosAcceptButton.__discord_ui_compiled_template__, button.custom_id)

        restored = await TosAcceptButton.from_custom_id(None, None, match)

        assert restored.version == TOS_HASH[:16]


class TestPaymentEmbed:
    def test_never_has_an_empty_field(self):
        embed = payment_instructions_embed(
            artist_display_name="Mika",
            quoted_price_php=None,
            payment_deadline_display=None,
            gcash_number=None,
            paypal_email=None,
        )

        assert isinstance(embed, discord.Embed)
        assert [f.name for f in embed.fields] == ["Payment details"]
        assert all(f.value for f in embed.fields)


class TestPay:
    @pytest.fixture
    def upload(self, monkeypatch):
        upload = AsyncMock(return_value="https://storage/receipt.png")
        monkeypatch.setattr(cog, "upload_receipt", upload)
        return upload

    async def _pay(self, interaction, attachment) -> None:
        cog_instance = CommissionCog(interaction.client)
        await cog_instance.pay.callback(cog_instance, interaction, attachment)

    async def test_stores_the_receipt_and_shows_it_to_the_artist(self, upload):
        interaction, api, channel = _scene(CLIENT_ID, "PAYMENT_PENDING")

        await self._pay(interaction, _attachment())

        upload.assert_awaited_once()
        api.upload_receipt.assert_awaited_once_with(
            "commission-uuid", "https://storage/receipt.png"
        )
        assert sent_embeds(channel)[0].image.url == "https://storage/receipt.png"
        assert channel.send.await_args.kwargs["content"] == f"<@{ARTIST_ID}>"

    async def test_nothing_is_stored_before_the_terms_are_accepted(self, upload):
        interaction, api, _ = _scene(CLIENT_ID, "TOS_PENDING")

        await self._pay(interaction, _attachment())

        upload.assert_not_awaited()
        assert "tos pending" in reply_text(interaction)

    async def test_wrong_file_type_is_refused(self, upload):
        interaction, api, _ = _scene(CLIENT_ID, "PAYMENT_PENDING")

        await self._pay(interaction, _attachment(content_type="application/x-msdownload"))

        upload.assert_not_awaited()
        assert "file type is not accepted" in reply_text(interaction)

    async def test_only_the_client_can_pay(self, upload):
        interaction, api, _ = _scene(ARTIST_ID, "PAYMENT_PENDING")

        await self._pay(interaction, _attachment())

        upload.assert_not_awaited()


class TestOtherCommands:
    async def test_quote_is_sent_by_the_artist_with_action_buttons(self, monkeypatch):
        monkeypatch.setattr(cog, "php_to_usd", AsyncMock(return_value=None))
        interaction, api, channel = _scene(ARTIST_ID, "INTAKE")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.quote.callback(cog_instance, interaction, 1500.0, "two characters")

        api.quote.assert_awaited_once_with("commission-uuid", price_php="1500.00", price_usd=None)
        assert isinstance(channel.send.await_args.kwargs["view"], QuoteActionsView)
        assert "₱1,500.00" in sent_embeds(channel)[0].description

    async def test_confirm_tos_reposts_the_terms(self):
        interaction, api, channel = _scene(CLIENT_ID, "TOS_PENDING")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.confirm_tos.callback(cog_instance, interaction)

        assert "No refunds after the sketch." in sent_embeds(channel)[0].description
        api.accept_tos.assert_not_awaited()  # showing the terms is not accepting them

    async def test_confirm_payment_is_for_the_artist(self):
        interaction, api, channel = _scene(CLIENT_ID, "PAYMENT_PENDING")
        cog_instance = CommissionCog(interaction.client)

        await cog_instance.confirm_payment_cmd.callback(cog_instance, interaction)

        api.confirm_payment.assert_not_awaited()
        assert "Only the artist can confirm payment" in reply_text(interaction)


class TestAttachmentChecks:
    def test_size_limit(self):
        too_big = _attachment(size=MAX_RECEIPT_BYTES + 1)
        assert "limit is 10 MB" in check_attachment(
            too_big, allowed_types=RECEIPT_TYPES, max_bytes=MAX_RECEIPT_BYTES
        )

    def test_type_limit_and_any_type(self):
        archive = _attachment(content_type="application/zip")
        assert check_attachment(archive, allowed_types=RECEIPT_TYPES, max_bytes=10**9)
        assert check_attachment(archive, allowed_types=None, max_bytes=10**9) is None

    def test_accepts_a_normal_receipt(self):
        assert check_attachment(
            _attachment(content_type="image/jpeg; charset=binary"),
            allowed_types=RECEIPT_TYPES,
            max_bytes=MAX_RECEIPT_BYTES,
        ) is None
