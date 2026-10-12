FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/

# Dependencies first for layer caching. They are installed from the lockfile into
# /opt/venv, outside /app, so the dev bind mount of the source does not hide them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

RUN useradd --create-home --uid 1000 artflow
USER artflow

# CMD is overridden per service (bot, worker, beat) in docker-compose.yml and Dokploy
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
