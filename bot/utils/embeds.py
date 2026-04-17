import discord

# Brand Color Constants
COLOR_PRIMARY = discord.Color.from_str("#5865F2")
COLOR_SUCCESS = discord.Color.green()
COLOR_WARNING = discord.Color.orange()
COLOR_ERROR = discord.Color.red()
COLOR_INFO = discord.Color.blurple()


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