from __future__ import annotations

import logging
from typing import Any

import discord

from bot.shared.embeds import base_embed
from shared.discord_layout import CHANNEL_ADMIN_LOGS

logger = logging.getLogger(__name__)

async def post_admin_log(
        guild: discord.Guild,
        *,
        title: str,
        description: str,
        fields: dict[str, str] | None = None
) -> None:
    ch = discord.utils.get(guild.channels, name=CHANNEL_ADMIN_LOGS)
    if not isinstance(ch, discord.TextChannel):
        return
    embed = base_embed(title=title, description=description[:4000])
    if fields:
        for k, v in list[tuple[str, str]](fields.items())[:25]:
            embed.add_field(name=k[:256], value=v[:1024], inline=False)

    try:
        await ch.send(embed=embed)
    except discord.HTTPException:
        logger.exception("admin log send failed")


def format_commission_snapshot(comm: dict[str, Any]) -> dict[str, str]:
    return {
        "Commission ID": str(comm.get("id", "")),
        "Status": str(comm.get("status", "")),
        "NSFW": str(comm.get("is_nsfw", False))
    }