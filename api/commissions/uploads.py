"""
Files that arrive with a commission action: what is accepted, and how big.
"""
from dataclasses import dataclass

from shared.errors import InvalidInput

MB = 1024 * 1024
MAX_RECEIPT_BYTES = 10 * MB
# Uploads are held in memory on their way to storage, so this is a hard cap.
MAX_ARTWORK_BYTES = 25 * MB

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
RECEIPT_TYPES = (*IMAGE_TYPES, "application/pdf")


@dataclass(frozen=True)
class IncomingFile:
    filename: str
    content: bytes
    content_type: str | None


def check(
        file: IncomingFile,
        *,
        allowed_types: tuple[str, ...] | None,
        max_bytes: int
) -> None:
    """Refuse a file that is empty, too large or of the wrong kind.

    `allowed_types=None` accepts any type (a final delivery may be a PSD or a zip).
    """
    if not file.content:
        raise InvalidInput("The uploaded file is empty")
    if len(file.content) > max_bytes:
        raise InvalidInput(f"That file is too large; the limit is {max_bytes // MB} MB")
    if allowed_types is not None:
        content_type = (file.content_type or "").split(";")[0].strip().lower()
        if content_type not in allowed_types:
            names = ", ".join(sorted({t.split("/")[1].upper() for t in allowed_types}))
            raise InvalidInput(f"That file type is not accepted here. Use one of: {names}")
