FROM python:3.12-slim
LABEL authors="decurzion"

FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install dependencies (no project install — we mount source in dev)
RUN uv pip install --system --no-cache -r pyproject.toml 2>/dev/null || \
    uv pip install --system --no-cache \
        "discord-py>=2.3" \
        "aiohttp>=3.9" \
        "fastapi>=0.111" \
        "uvicorn[standard]>=0.29" \
        "gunicorn>=22.0" \
        "pydantic[email]>=2.7" \
        "pydantic-settings>=2.3" \
        "sqlalchemy[asyncio]>=2.0" \
        "asyncpg>=0.29" \
        "alembic>=1.13" \
        "redis[asyncio]>=5.0" \
        "celery[redis]>=5.4" \
        "Pillow>=10.3" \
        "httpx>=0.27" \
        "python-multipart>=0.0.9"

COPY . .

# CMD is overridden per service in docker-compose.yml
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
