# ArtFlow

Discord-native art commission management platform built for Filipino artists and B2B art communities.

Artists accept commissions, post WIPs, and get paid — entirely inside Discord. Server owners get a white-label commission system with a 9-stage lifecycle, dispute resolution, role management, and subscription tiers.

---

## What It Does

- **Artist onboarding** — `/artist-apply` modal → admin approve/reject queue → auto-role assignment
- **Commission lifecycle** — 9 stages: `INQUIRY → INTAKE → QUOTED → TOS_PENDING → PAYMENT_PENDING → IN_PROGRESS → DELIVERED → COMPLETED → CANCELLED`
- **Payment handling** — GCash and PayPal receipts uploaded as screenshots; 24-hour payment deadline enforced by Celery Beat
- **WIP system** — artists post progress images that are auto-watermarked via Celery + Pillow before being shown to clients
- **Delivery + reviews** — 48-hour auto-accept timer; star ratings posted to `#reviews`
- **Dispute resolution** — `/dispute` freezes a ticket; mod panel with Full Refund / Partial Refund / resolution options
- **18+ age gating** — phone-verified Discord accounts auto-approved; others queued for mod review
- **B2B tiers** — FREE / STARTER / PRO / ENTERPRISE enforced per server; LemonSqueezy billing with webhook handler
- **Admin commands** — live stats, artist roster, commission pipeline overview

---

## Architecture

Four runtimes, one Python codebase:

```
Discord (WebSocket)
    └── bot/          discord.py — slash commands, cogs, events
            │ HTTP (X-Bot-Secret)
            ▼
         api/          FastAPI — business logic, DB access
            │
            ├── shared/models/    SQLAlchemy async ORM → PostgreSQL
            ├── shared/schemas/   Pydantic v2 contracts (all layers)
            └── shared/redis.py   Redis connection pool

    workers/           Celery — notifications, image processing, timers
            └── shared/           same models, same DB session
```

**Build order:** `shared/models` → Alembic migrations → `shared/schemas` → `api/` → `bot/` → `workers/`

The bot never touches the database directly. It calls the API over HTTP. Workers are queued by the API, not the bot.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Bot | discord.py 2.3 + aiohttp |
| API | FastAPI + uvicorn + gunicorn |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| Migrations | Alembic (autogenerate only) |
| Validation | Pydantic v2 |
| Cache / Queue | Redis |
| Workers | Celery + Celery Beat |
| Image processing | Pillow |
| File storage | Supabase Storage |
| Database | PostgreSQL (self-hosted Supabase) |
| Package manager | uv |
| Billing | LemonSqueezy |
| Deploy | Dokploy on Oracle Cloud VPS |
| CI/CD | GitHub Actions → Docker Hub → Dokploy webhook |

---

## Project Structure

```
artflow/
├── bot/
│   ├── cogs/
│   │   ├── verification.py     # TOS button, email flow, role assignment
│   │   ├── artist.py           # /artist-apply, /showcase, /commissions open/close
│   │   ├── commission.py       # /commission request, /quote, /pay, /wip, /deliver
│   │   ├── dispute.py          # /dispute command + mod resolution
│   │   └── admin.py            # /admin stats, artists, commissions
│   ├── events/
│   │   └── on_member_join.py   # Unverified role + welcome DM
│   ├── utils/
│   │   ├── embeds.py           # Reusable embed builders
│   │   └── api_client.py       # aiohttp wrapper — injects X-Bot-Secret on every call
│   └── main.py                 # AutoShardedBot, cog loader, error handler
│
├── api/
│   ├── routers/                # users, artists, commissions, servers, admin
│   ├── services/               # Business logic — user_service, artist_service, commission_service
│   ├── dependencies.py         # get_db(), verify_bot_secret(), rate limiting
│   └── main.py                 # FastAPI app factory + lifespan
│
├── workers/
│   ├── notifications.py        # DM reminders, deadline alerts
│   ├── images.py               # Pillow watermarking, thumbnail generation
│   ├── celery_app.py           # Celery app factory (Redis broker)
│   └── beat.py                 # Celery Beat schedule
│
├── shared/
│   ├── models/                 # 7 SQLAlchemy models — server, user, artist, commission, wip_update, review, dispute
│   ├── schemas/                # Pydantic v2 request/response shapes
│   ├── db.py                   # Async session factory
│   ├── redis.py                # Redis connection pool
│   ├── storage.py              # Supabase Storage client wrapper
│   └── config.py               # pydantic-settings — reads from .env
│
├── alembic/                    # Auto-generated migration scripts
├── docker-compose.yml          # Local dev: postgres + redis (+ full app profile)
├── Dockerfile                  # Single image; CMD overridden per service
└── pyproject.toml              # uv — one dependency file for the entire monorepo
```

---

## Local Development

### Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Docker](https://docs.docker.com/get-docker/) + Docker Compose

### Setup

```bash
git clone https://github.com/your-org/artflow.git
cd artflow

cp .env.example .env
# Edit .env — set DISCORD_TOKEN, BOT_SECRET, and Supabase credentials at minimum

uv sync

docker compose up -d postgres redis

uv run alembic upgrade head

# Terminal 1 — API
uv run uvicorn api.main:app --reload

# Terminal 2 — Bot
uv run python -m bot.main

# Terminal 3 — Celery worker (optional for local dev)
uv run celery -A workers.celery_app worker --loglevel=info
```

API docs available at `http://localhost:8000/docs` once the API is running.

### Full stack with Docker

```bash
docker compose --profile app up --build
```

### Database migrations

```bash
# After editing shared/models/
uv run alembic revision --autogenerate -m "describe_change"
uv run alembic upgrade head

# Roll back one migration
uv run alembic downgrade -1
```

---

## Environment Variables

See `.env.example` for the full reference. Required variables:

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from Discord Developer Portal |
| `BOT_SECRET` | Shared secret between bot and API — `openssl rand -hex 32` |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:port/db` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `SUPABASE_URL` | Supabase instance URL (for Storage) |
| `SUPABASE_SERVICE_KEY` | `service_role` JWT |
| `API_BASE_URL` | Used to build email verification links in DMs |

---

## Services

| Service | Port | Command |
|---|---|---|
| FastAPI | 8000 | `uvicorn api.main:app --reload` |
| Discord Bot | — | `python -m bot.main` |
| Celery Worker | — | `celery -A workers.celery_app worker` |
| Celery Beat | — | `celery -A workers.celery_app beat` |
| PostgreSQL | 5434 (local) | Docker |
| Redis | 6379 | Docker |

---

## Deployment

Deployed on Oracle Cloud VPS via [Dokploy](https://dokploy.com). GitHub Actions builds and pushes Docker images on every push to `main`, then triggers Dokploy deploy webhooks for each service.

Required GitHub Actions secrets:

| Secret | Value |
|---|---|
| `DOCKER_USERNAME` | Docker Hub username |
| `DOCKER_TOKEN` | Docker Hub access token |
| `DOKPLOY_TOKEN` | Dokploy API token |
| `DOKPLOY_WEBHOOK_URL_API` | Deploy webhook for API service |
| `DOKPLOY_WEBHOOK_URL_BOT` | Deploy webhook for Bot service |
| `DOKPLOY_WEBHOOK_URL_WORKERS` | Deploy webhook for Workers service |

---

## Roadmap

| Month | Goal |
|---|---|
| Month 1 (Weeks 1–4) | Flagship server live. Verification + artist apply flow end-to-end. 5 test artists onboarded. |
| Month 2 (Weeks 5–8) | Full 9-stage commission lifecycle. GCash payments. WIP watermarking. Reviews. 50 real artists. |
| Month 3 (Weeks 9–13) | NSFW + age gating. Dispute system. B2B `/setup` wizard + tier enforcement. 3 pilot servers. First paying B2B customer. |

See [`artflow-roadmap.md`](artflow-roadmap.md) for the full week-by-week breakdown.
