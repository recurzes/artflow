"""Small formatting helpers shared by the commission modules."""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import discord


def status_label(comm: dict[str, Any]) -> str:
    return str(comm.get("status", "")).replace("_", " ").lower()


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def discord_time(value: str | None) -> str | None:
    """A timestamp Discord renders in each reader's own timezone, with a countdown."""
    dt = _parse_iso_dt(value)
    if dt is None:
        return None
    unix = int(dt.timestamp())
    return f"<t:{unix}:f> (<t:{unix}:R>)"


def float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


def chunks(text: str, size: int = 3900) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def attached(raw: bytes, original_name: str, stem: str) -> tuple[discord.File, str]:
    """A file to post in the channel, under a name that is safe to reference
    from an embed (`attachment://...` breaks on spaces and odd characters)."""
    suffix = PurePosixPath(original_name).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ""
    name = f"{stem}{suffix}"
    return discord.File(io.BytesIO(raw), filename=name), name
