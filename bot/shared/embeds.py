
import discord

# Brand Color Constants
COLOR_PRIMARY = discord.Color.from_str("#5865F2")
COLOR_SUCCESS = discord.Color.green()
COLOR_WARNING = discord.Color.orange()
COLOR_ERROR = discord.Color.red()


def base_embed(
        title: str,
        description: str = "",
        color: discord.Color = COLOR_PRIMARY
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="ArtFlow")
    return embed

def success_embed(title: str, description: str = "") -> discord.Embed:
    return base_embed(title, description, color=COLOR_SUCCESS)

def error_embed(message: str) -> discord.Embed:
    return base_embed("Error", message, color=COLOR_ERROR)

def warning_embed(title: str, description: str = "") -> discord.Embed:
    return base_embed(title, description, color=COLOR_WARNING)

def artist_profile_embed(
        display_name: str,
        styles: list[str],
        price_min: float | None,
        price_max: float | None,
        rating_avg: float,
        rating_count: int,
        status: str,
        portfolio_images: list[str] | None = None
) -> discord.Embed:
    price_str = "Price on request"
    if price_min and price_max:
        price_str = f"₱{price_min:,.0f} – ₱{price_max:,.0f}"
    elif price_min:
        price_str = f"From ₱{price_min:,.0f}"

    stars = "⭐" * round(rating_avg) if rating_count > 0 else "No reviews yet"
    rating_str = f"{stars} ({rating_count} reviews)" if rating_avg > 0 else stars

    embed = base_embed(display_name)
    embed.add_field(name="Styles", value=", ".join(styles) or "Not specified", inline=True)
    embed.add_field(name="Pricing", value=price_str, inline=True)
    embed.add_field(name="Rating", value=rating_str, inline=True)
    embed.add_field(name="Status", value=status.title(), inline=True)

    if portfolio_images:
        embed.set_image(url=portfolio_images[0])

    return embed

def payment_instructions_embed(
        *,
        artist_display_name: str,
        quoted_price_php: float | None,
        payment_deadline_display: str | None,
        gcash_number: str | None,
        paypal_email: str | None
) -> discord.Embed:
    embed = base_embed(
        title="Payment instructions",
        description=(
            f"Pay **{artist_display_name}** for this commission. "
            "Upload your receipt with `/pay` when done"
        ),
        color=COLOR_WARNING
    )
    if quoted_price_php is not None:
        embed.add_field(name="Amount due", value=f"₱{quoted_price_php:,.2f} PHP", inline=True)
    if payment_deadline_display:
        embed.add_field(name="Pay by", value=payment_deadline_display, inline=True)
    # Discord rejects a field with an empty value, so only add what the artist has set.
    if gcash_number:
        embed.add_field(name="GCash number", value=gcash_number, inline=False)
    if paypal_email:
        embed.add_field(name="PayPal", value=paypal_email, inline=False)
    if not gcash_number and not paypal_email:
        embed.add_field(
            name="Payment details",
            value="The artist has not saved any. Ask them in this channel where to pay",
            inline=False
        )
    return embed

def public_review_embed(
        *,
        artist_name: str,
        rating: int,
        body: str | None
) -> discord.Embed:
    stars = "⭐" * rating
    desc = f"{stars} ({rating}/5)"
    if body:
        desc += f"\n\n{body}"
    return base_embed(f"Review — {artist_name}", desc, color=COLOR_SUCCESS)

def completed_work_embed(
        *,
        artist_name: str,
        commission_id_display: str,
        image_filename: str | None = None
) -> discord.Embed:
    """`image_filename` names a file attached to the same message."""
    embed = base_embed(
        title="Completed work",
        description=f"Artist: **{artist_name}**\nCommission: `{commission_id_display}`",
        color=COLOR_SUCCESS
    )
    if image_filename:
        embed.set_image(url=f"attachment://{image_filename}")
    return embed
