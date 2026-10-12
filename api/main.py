from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.dependencies import limiter
from api.routers import admin, artists, commissions, disputes, servers, users
from shared.config import settings
from shared.db import dispose_engine
from shared.redis import close_pool, get_pool
from shared.storage import close_client as close_storage_client

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_pool()
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

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(users.router)
    app.include_router(artists.router)
    app.include_router(commissions.router)
    app.include_router(disputes.router)
    app.include_router(servers.router)
    app.include_router(admin.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    return app

app = create_app()
