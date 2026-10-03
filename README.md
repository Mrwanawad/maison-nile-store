# Brand Store

A bilingual (English / Arabic) online store for a local Egyptian brand: products with colors and sizes, a bag, checkout with cash on delivery or Paymob, and an admin panel for the owners.

Stack: FastAPI · Jinja2 + HTMX · Tailwind v4 + Preline · PostgreSQL (Supabase) · Paymob · Bosta · Telegram. Full design notes are in [docs/DESIGN.md](docs/DESIGN.md).

## Run it locally (Windows, macOS or Linux)

Requirements: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env              # every setting lives here, with comments
docker compose -f docker/docker-compose.yml up -d db   # Postgres 16 on localhost:5432
uv sync                           # Python dependencies
cd src/frontend && npm install && npm run build && cd ../..   # CSS + vendored JS (once, or after template changes)
uv run alembic upgrade head       # create tables
uv run python -m scripts.seed     # demo catalog (10 products)
uv run python -m scripts.create_admin owner "Shop Owner"   # prompts for a password
uv run uvicorn app.main:app --app-dir src/backend --reload
```

- Store: http://localhost:8000 (Arabic at http://localhost:8000/ar)
- Admin: http://localhost:8000/admin
- API docs (dev only): http://localhost:8000/api/docs

While editing templates, keep `npm run watch:css` (run in `src/frontend`) going in a second terminal.

**Docker only** (no local Python/Node needed): `cp .env.example .env`, then `docker compose -f docker/docker-compose.yml up`.
That starts Postgres, the app on :8000 (migrations run automatically) and the CSS watcher.
Then load demo data and an admin in another terminal:

```bash
docker compose -f docker/docker-compose.yml exec app python -m scripts.seed
docker compose -f docker/docker-compose.yml exec app python -m scripts.create_admin owner "Shop Owner"
```

## Tests and checks

```bash
uv run pytest            # needs the docker compose db (uses a separate store_test database)
uv run ruff check . && uv run ruff format --check .
uv run mypy src/backend/app
```

Install the git hooks once with `uv run pre-commit install`.

## Project layout

```
src/
  backend/       Python: FastAPI app, Alembic, CLI scripts
    app/
      controllers/  web/ (storefront), admin/, api/v1/, system.py (health, cron)
      services/     business rules: cart, orders, payments, shipping, fraud, notifications
      repositories/ SQL only
      integrations/ paymob, bosta, telegram, email (brevo/resend), storage (local/supabase), sms
      models/       SQLAlchemy tables
      schemas/      Pydantic input/output (shared by HTML and API)
      views/        Jinja templates (pages, partials, components, admin, emails)
      locales/      en.json, ar.json
      content/      en/ar Markdown pages (about, FAQ, size guide, policies)
      core/         config, db, i18n, security, errors, middleware, templates
    migrations/   Alembic
    scripts/      seed, create_admin, browser_check
  frontend/      CSS + JS assets: Tailwind source, htmx/Preline vendoring, npm config
    static/       css/input.css (source), js/app.js, img, fonts, vendor (build output gitignored)
    scripts/      vendor.mjs
tests/           unit + integration (real Postgres)
```

## Configuration

Everything that may change (brand name, logo, colors, WhatsApp number, shipping fees, COD limits, API keys, app version, rate limits) is in `.env`. See the comments in [.env.example](.env.example). Restart the app after changing it.

Integrations switch on only when their keys are present: with no keys at all the store runs in cash-on-delivery mode, and Telegram/email messages are written to the log instead of sent.

## Deploying (free tier)

1. **Supabase**: create a project (region Frankfurt); in *Storage* create a public bucket `products`. Copy the *transaction pooler* connection string (port 6543). It can be pasted as-is: `postgresql://` is converted to `postgresql+asyncpg://` and pooler mode switches on automatically. URL-encode special characters in the password.
2. **Render**: *New → Blueprint* from this repo (uses `render.yaml`). Set `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ADMIN_BOOTSTRAP_USERNAME`, `ADMIN_BOOTSTRAP_PASSWORD` (10+ characters), plus any brand/contact values. `BASE_URL` defaults to the service's `onrender.com` URL; set it only for a custom domain. Migrations run on every start.
3. On first start the container loads the demo catalog (`SEED_DEMO_DATA=true`, only when the catalog is empty) and creates the bootstrap admin if it doesn't exist (an existing admin is never changed). Add the second owner from a machine with the production `DATABASE_URL`: `ADMIN_PASSWORD='…' python -m scripts.create_admin <username> "<Name>"`. Set `SEED_DEMO_DATA=false` once real products are in.
4. **UptimeRobot**: HTTP monitor on `https://<your-app>/health` every 5-10 minutes (keeps Render awake and Supabase from pausing).
5. **GitHub secrets** for the scheduled jobs: `SITE_URL`, `INTERNAL_CRON_TOKEN` (same value as on Render), `BACKUP_DATABASE_URL` (Supabase *session pooler* connection string, `postgresql://postgres.<ref>:…@aws-0-<region>.pooler.supabase.com:5432/postgres`; the direct `db.<ref>.supabase.co` host is IPv6-only and GitHub runners can't reach it), `BACKUP_PASSPHRASE`.

### What the business needs to provide

| Item | Where it goes |
|---|---|
| Logo URL, brand color, name in Arabic, tagline | `BRAND_*` |
| WhatsApp number, Instagram/Facebook/TikTok links, support email/phone | contact section |
| Paymob account (KYC approved): secret key, public key, HMAC secret, API key, Apple Pay integration ID | `PAYMOB_*`; set the transaction callback to `https://<site>/webhooks/paymob` |
| Bosta API key (and pickup location id) | `BOSTA_*` |
| Telegram bot token + each owner's chat id | `TELEGRAM_*` |
| Brevo account with a verified sender email | `EMAIL_*` |
| Real product photos, size chart, return policy, about text | admin panel and `src/backend/app/content/` |
| Custom domain (needed for production Apple Pay and a professional email sender) | Cloudflare → Render |
