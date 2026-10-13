import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from api.admin.routes import router as admin_router
from api.artists.routes import router as artists_router
from api.commissions.routes import router as commissions_router
from api.disputes.routes import router as disputes_router
from api.errors import register_error_handlers
from api.reviews.routes import router as reviews_router
from api.servers.routes import router as servers_router
from api.users.routes import router as users_router
from shared.config import settings
from shared.db import dispose_engine
from shared.redis import close_pool, get_pool
from shared.storage import close_client as close_storage_client
from shared.storage import ensure_buckets_exist

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.2,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
        send_default_pii=False,
    )


logger = logging.getLogger(__name__)


async def _prepare_storage() -> None:
    """Create the storage buckets on first run. Never fatal: everything except
    file uploads works without storage, and the logs say why uploads will not."""
    if not settings.supabase_url or not settings.supabase_service_key:
        logger.warning("Supabase Storage is not configured; file uploads will fail")
        return
    try:
        await ensure_buckets_exist()
    except Exception:
        logger.exception("Could not verify the storage buckets; file uploads may fail")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_pool()
    await _prepare_storage()
    yield
    await close_pool()
    await dispose_engine()
    await close_storage_client()

def create_app() -> FastAPI:
    settings.require("bot_secret", "database_url")

    # The API is internal; its schema is only browsable outside production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="ArtFlow API",
        description="Internal API for the ArtFlow Discord commission bot",
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan
    )

    register_error_handlers(app)

    app.include_router(users_router)
    app.include_router(artists_router)
    app.include_router(commissions_router)
    app.include_router(reviews_router)
    app.include_router(disputes_router)
    app.include_router(servers_router)
    app.include_router(admin_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    return app

app = create_app()
