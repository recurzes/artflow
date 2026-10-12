from __future__ import annotations

import discord

MB = 1024 * 1024
MAX_RECEIPT_BYTES = 10 * MB
# Attachments are read into memory before they are stored, so this is a hard cap
# regardless of what the uploader's Discord plan allows.
MAX_ARTWORK_BYTES = 25 * MB

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
RECEIPT_TYPES = (*IMAGE_TYPES, "application/pdf")


def check_attachment(
        attachment: discord.Attachment,
        *,
        allowed_types: tuple[str, ...] | None,
        max_bytes: int
) -> str | None:
    """Why an attachment cannot be accepted, or None when it is fine.

    `allowed_types=None` accepts any file type (a final delivery may be a PSD or a zip).
    """
    if attachment.size > max_bytes:
        return (
            f"That file is {attachment.size / MB:.1f} MB; "
            f"the limit is {max_bytes // MB} MB"
        )
    if allowed_types is not None:
        content_type = (attachment.content_type or "").split(";")[0].strip().lower()
        if content_type not in allowed_types:
            names = ", ".join(sorted({t.split("/")[1].upper() for t in allowed_types}))
            return f"That file type is not accepted here. Use one of: {names}"
    return None


def is_image(attachment: discord.Attachment) -> bool:
    content_type = (attachment.content_type or "").split(";")[0].strip().lower()
    return content_type in IMAGE_TYPES
