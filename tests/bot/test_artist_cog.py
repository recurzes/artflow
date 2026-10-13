"""
The pure parts of artist onboarding: parsing the application form and building
the moderation embed and its persistent buttons.
"""
import re

from bot.artists.applications import (
    APPROVE_BUTTON_ID,
    ApproveApplicationButton,
    RejectApplicationButton,
    _parse_payment_info,
    _parse_price_range,
    _parse_social_links,
    application_review_view,
    build_application_embed,
)

ARTIST_ID = "0d9f6b1e-5a52-4b6e-9a53-0c1f6f0f9f11"


def test_price_range():
    assert _parse_price_range("500 - 3000") == (500.0, 3000.0)
    assert _parse_price_range("1,500–3,000") == (1500.0, 3000.0)
    assert _parse_price_range("800") == (800.0, None)
    assert _parse_price_range("ask me") == (None, None)


def test_payment_info():
    assert _parse_payment_info("0917 123 4567") == ("09171234567", None)
    assert _parse_payment_info("+63 917-123-4567") == ("639171234567", None)
    assert _parse_payment_info("artist@example.com") == (None, "artist@example.com")
    assert _parse_payment_info("ask me in DMs") == (None, None)


def test_social_links():
    links = _parse_social_links(
        "Twitter: https://x.com/mika\n\nhttps://pixiv.net/users/1\nIG : https://instagram.com/mika"
    )
    assert links == {
        "Twitter": "https://x.com/mika",
        "Link 2": "https://pixiv.net/users/1",
        "IG": "https://instagram.com/mika",
    }


def test_application_embed_handles_missing_optional_fields():
    artist = {
        "id": ARTIST_ID,
        "display_name": "Mika",
        "discord_user_id": "123456789012345678",
        "styles": [],
        "social_links": {},
        "price_min_php": None,
        "price_max_php": None,
        "gcash_number": None,
        "paypal_email": None,
    }

    embed = build_application_embed(artist, None)

    fields = {field.name: field.value for field in embed.fields}
    assert fields["Status"] == "PENDING"
    assert fields["GCash"] == "–"
    assert fields["PayPal"] == "–"
    assert all(value for value in fields.values())  # Discord rejects empty field values


async def test_review_buttons_carry_the_artist_id_and_can_be_restored():
    view = application_review_view(ARTIST_ID)

    assert view.timeout is None
    custom_ids = [item.custom_id for item in view.children]
    assert custom_ids[0] == f"{APPROVE_BUTTON_ID}:{ARTIST_ID}"

    # What discord.py does after a restart: match the custom_id, rebuild the item.
    for cls, custom_id in zip((ApproveApplicationButton, RejectApplicationButton), custom_ids):
        match = re.fullmatch(cls.__discord_ui_compiled_template__, custom_id)
        assert match is not None
        restored = await cls.from_custom_id(None, None, match)
        assert restored.artist_id == ARTIST_ID
