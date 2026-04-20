from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers import admin, artists, commissions, servers, users
from shared.config import settings
from shared.db import engine
from shared.redis import close_pool, get_pool
from shared.storage import close_client as close_storage_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_pool()
    yield
    await close_pool()
    await engine.dispose()
    await close_storage_client()

def create_app() -> FastAPI:
    app = FastAPI(
        title="ArtFlow API",
        description="Internal API for the ArtFlow Discord commission bot",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )

    app.include_router(users.router)
    app.include_router(artists.router)
    app.include_router(commissions.router)
    app.include_router(servers.router)
    app.include_router(admin.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    return app

app = create_app()