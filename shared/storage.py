import mimetypes
import uuid
from pathlib import PurePosixPath

from supabase import AsyncClient, acreate_client

from shared.config import settings

_client: AsyncClient | None = None

async def get_client() -> AsyncClient | None:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set before using storage"
            )
        _client = await acreate_client(
            settings.supabase_url,
            settings.supabase_service_key
        )

    return _client

async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.auth.close()
        _client = None


# Stored references
#
# What gets saved in the database is "<bucket>/<path>", never a signed URL:
# signed URLs expire, and a receipt has to stay readable for as long as a
# dispute can be raised. A URL is signed at the moment someone needs to open
# the file.

def file_ref(bucket: str, key: str) -> str:
    return f"{bucket}/{key}"


async def signed_url_for(ref: str, expires_in: int = 3600) -> str:
    # Rows written before references were stored hold a full URL; pass it through.
    if ref.startswith(("http://", "https://")):
        return ref
    bucket, _, key = ref.partition("/")
    return await get_signed_url(bucket, key, expires_in)


# Upload helpers. Each returns the reference to store, not a URL.
async def upload_wip_image(
        file_bytes: bytes,
        filename: str,
        commission_id: str,
        watermarked: bool = False
) -> str:
    ext = PurePosixPath(filename).suffix or ".jpg"
    variant = "watermarked" if watermarked else "original"
    key = f"{commission_id}/{variant}/{uuid.uuid4()}{ext}"
    await _upload(
        bucket=settings.storage_bucket_wip,
        key=key,
        data=file_bytes,
        content_type=_content_type(filename),
        upsert=False
    )
    return file_ref(settings.storage_bucket_wip, key)

async def upload_receipt(
        file_bytes: bytes,
        filename: str,
        commission_id: str
) -> str:
    ext = PurePosixPath(filename).suffix or ".jpg"
    key = f"{commission_id}/{uuid.uuid4()}{ext}"
    await _upload(
        bucket=settings.storage_bucket_receipts,
        key=key,
        data=file_bytes,
        content_type=_content_type(filename),
        upsert=False
    )
    return file_ref(settings.storage_bucket_receipts, key)

async def upload_delivery_file(
        file_bytes: bytes,
        filename: str,
        commission_id: str
) -> str:
    ext = PurePosixPath(filename).suffix or ".png"
    key = f"{commission_id}/final/{uuid.uuid4()}{ext}"
    await _upload(
        bucket=settings.storage_bucket_wip,
        key=key,
        data=file_bytes,
        content_type=_content_type(filename),
        upsert=False
    )
    return file_ref(settings.storage_bucket_wip, key)


# URL Helpers
async def get_signed_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    client = await get_client()
    response = await client.storage.from_(bucket).create_signed_url(key, expires_in)
    return response["signedUrl"]


# Bucket setup
async def ensure_buckets_exist() -> None:
    client = await get_client()
    existing = await client.storage.list_buckets()
    existing_names = {b.name for b in existing}

    # Both private: files are only ever reached through short-lived signed links.
    buckets = [
        (settings.storage_bucket_wip, False),
        (settings.storage_bucket_receipts, False)
    ]

    for name, is_public in buckets:
        if name not in existing_names:
            await client.storage.create_bucket(name, options={"public": is_public})


# Internal
async def _upload(
        bucket: str,
        key: str,
        data: bytes,
        content_type: str,
        upsert: bool = False
) -> str:
    client = await get_client()

    await client.storage.from_(bucket).upload(
        path=key,
        file=data,
        file_options={"content-type": content_type, "upsert": str(upsert).lower()},
    )
    return key

def _content_type(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"