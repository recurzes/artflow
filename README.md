# ArtFlow

A Discord bot that runs art commissions inside a server, built for Filipino artists and art communities.

A client picks an artist with `/commission` and gets a private ticket channel. The commission then moves through brief, quote, terms, payment, work-in-progress updates, delivery and review, with the bot keeping both sides on the same step and a record of every one.

---

## What it does

| Area | What works |
|---|---|
| **Member verification** | Members accept the server terms with a button and get the Verified User role. |
| **Artist onboarding** | `/artist-apply` → moderators Approve / Reject in the verification queue → role, directory post and welcome DM. A rejected applicant can reapply after 7 days. |
| **Commissions** | The lifecycle below, enforced by the API. Each artist has a limit on active commissions. |
| **Payments** | The client pays the artist directly (GCash / PayPal) and uploads the receipt with `/pay`; the artist confirms. ArtFlow records, it does not move money. |
| **Timers** | Unpaid commissions are cancelled 24 hours after the terms are accepted (with a reminder in the last 12). Deliveries are auto-accepted after 48 hours. |
| **Disputes** | `/dispute` freezes a commission until a moderator rules: cancel it or mark it completed. |
| **Reviews** | 1–5 stars after completion, posted to `#reviews`; the artist's rating is the average. |
| **18+ gating** | Accounts 90+ days old are approved on request; newer ones go to moderators. NSFW commissions need an 18+ client and an artist who opted in. |
| **Admin** | `/admin stats`, `artists`, `commissions`, `repair-permissions`. |

**Not built yet:** billing and subscription tiers (the `subscription_tier` column exists and is always `FREE`), WIP watermarking, revision tracking (`/revision` only explains this), and a `/setup` command (a server is provisioned when the bot joins it).

### Commission lifecycle

```
INQUIRY ─► INTAKE ─► QUOTED ─► TOS_PENDING ─► PAYMENT_PENDING ─► IN_PROGRESS ─► WIP ─► DELIVERED ─► COMPLETED
              ▲          │
              └──────────┘  counter-offer
```

- **CANCELLED** is reachable from any step until a payment receipt is uploaded (`/cancel`, or the payment deadline passing with no receipt).
- **DISPUTED** is reachable once a receipt is uploaded and until completion. Only a moderator moves it on, to COMPLETED or CANCELLED.
- A commission is cancelled automatically only when no receipt was uploaded. A receipt the artist has not confirmed is a dispute, not a lapse.

Every transition goes through one function in [`api/commissions/service.py`](api/commissions/service.py); a move that is not in its table cannot happen.

### Commands

| Who | Commands |
|---|---|
| Client | `/commission`, `/accept-quote`, `/confirm-tos`, `/pay`, `/complete`, `/review` |
| Artist | `/artist-apply`, `/quote`, `/confirm-payment`, `/wip`, `/deliver`, `/showcase`, `/settings tos`, `/settings nsfw`, `/commissions open`, `/commissions close` |
| Either party | `/cancel`, `/dispute` |
| Moderator | `/dispute-resolve`, `/age-approve`, `/age-gate-post`, Approve / Reject buttons |
| Admin | `/setup-tos`, `/admin …` |

Most steps also have a button under the relevant message. Buttons keep working after the bot restarts.

---

## Architecture

Two processes do the work, plus an optional third:

```
Discord ◄──► bot/      discord.py: slash commands, buttons, the timers' announcements
               │  HTTP, X-Bot-Secret + X-Actor-Discord-Id
               ▼
             api/      FastAPI: every rule and all data access
               │
               ├── PostgreSQL        (SQLAlchemy async, Alembic)
               ├── Redis             (pending 18+ requests)
               └── Supabase Storage  (receipts, WIP images, deliveries)

             workers/  Celery: reserved for image work; nothing is queued yet
```

**The bot holds no credentials except its Discord token and the shared secret.** It never touches the database, Redis or storage; it sends files and requests to the API.

**The API decides, the bot reports.** Each action names the member who triggered it (`X-Actor-Discord-Id`), and the API checks that this member is the client or the artist the action belongs to. The bot has no copy of those rules. The one thing the API cannot know is Discord roles, so the bot states when the actor is a moderator.

**Timers run in the bot.** Every five minutes it asks the API which commissions are overdue or due for a reminder; the API changes them and returns them, and the bot posts in each ticket. A worker could change the records but could not tell anyone.

### Code layout

Both `api/` and `bot/` are grouped by feature.

```
api/
├── main.py, dependencies.py, errors.py
└── <feature>/               users, artists, commissions, reviews, disputes, servers, admin
    ├── routes.py            parse the request, call the service, return the result
    ├── service.py           the rules; raises NotFound / Forbidden / Conflict / InvalidState
    ├── repository.py        named queries; the only place that builds SQL
    └── schemas.py           request and response shapes

bot/
├── main.py
├── commissions/             cog.py (commands), opening.py, payment.py, completion.py,
│                            tickets.py, sweeps.py (timers), formatting.py
├── artists/                 cog.py, applications.py
├── disputes/, verification/, admin/, servers/
└── shared/                  api_client.py, layout.py, embeds.py, permissions.py, ...

shared/                      used by more than one process:
                             config, db, redis, storage, models/, errors, discord_layout
workers/                     Celery app and the watermark placeholder
alembic/                     migrations
tests/                       api/ (against Postgres), bot/ (fake Discord objects)
```

The layering is enforced by [`tests/test_architecture.py`](tests/test_architecture.py): routes and services may not build queries, a feature may not import another feature's repository, and the bot may not import the API or any infrastructure.

---

## Local development

### Prerequisites

- [uv](https://docs.astral.sh/uv/)
- Docker

### Setup

```bash
cp .env.example .env
# Set DISCORD_TOKEN and BOT_SECRET. Supabase is only needed for file uploads.

uv sync --extra dev
docker compose up -d postgres redis
uv run alembic upgrade head

uv run uvicorn api.main:app --reload      # terminal 1: API on :8000, docs at /docs
uv run python -m bot.main                 # terminal 2: bot
```

Or everything in containers:

```bash
docker compose --profile app up --build
```

### Tests and lint

```bash
docker compose up -d postgres
uv run --extra dev pytest
uv run --extra dev ruff check .
```

The suite creates and uses its own `artflow_test` database, builds the schema with Alembic, and rolls every test back. API tests walk the full lifecycle over HTTP; bot tests drive the handlers with fake Discord objects and call every method of the bot's API client against the real API.

### Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

Revisions that have run anywhere are not edited; add a new one.

---

## Configuration

See [`.env.example`](.env.example) for every variable.

| Variable | Needed by | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | bot | Bot token |
| `BOT_SECRET` | bot, api | Shared secret; generate with `openssl rand -hex 32` |
| `API_BASE_URL` | bot | Where the bot reaches the API |
| `DATABASE_URL` | api | `postgresql+asyncpg://user:pass@host:port/db` |
| `REDIS_URL` | api, worker | |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | api | File storage; the API creates its two private buckets on startup |
| `ENVIRONMENT` | all | `production` hides the API docs and rejects the example secrets |
| `EXCHANGE_RATE_ACCESS_KEY` | api | Optional; adds an approximate USD figure to quotes |
| `SENTRY_DSN` | all | Optional |

The API and the bot refuse to start when a variable they need is missing.

---

## Deployment

GitHub Actions runs lint and tests on pull requests and on pushes to `main`. On `main`, when they pass, it builds one Docker image, pushes it to Docker Hub and triggers the Dokploy deployments. The image's command is overridden per service:

| Service | Command |
|---|---|
| API | `uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| Bot | `python -m bot.main` |
| Worker (optional) | `celery -A workers.celery_app worker` |

**Migrations are not run automatically.** Run `alembic upgrade head` against the production database before the new API takes traffic.

Required GitHub Actions secrets: `DOCKER_USERNAME`, `DOCKER_TOKEN`, `DOKPLOY_TOKEN`, `DOKPLOY_WEBHOOK_URL_API`, `DOKPLOY_WEBHOOK_URL_BOT`, `DOKPLOY_WEBHOOK_URL_WORKERS`.

### Bot permissions

The bot needs the **Server Members** privileged intent and, in each server, Manage Roles, Manage Channels, Send Messages, Embed Links and Attach Files. Its role must sit above the roles it assigns.

When it joins a server it creates its roles, channels and categories and records their IDs, so they can be renamed afterwards. On a server set up before staff channels were hidden from `@everyone`, run `/admin repair-permissions` once.
