# CHECKPOINT — Brand Store (Egyptian e-commerce MVP)

> Hand-off file for a fresh session. Read this first, then `docs/DESIGN.md` (section 15 overrides older sections; the last bullet, "Visual identity v3", overrides all earlier visual specs) and `README.md`.
> Last updated: 2026-10-03. Branch `main`, all work committed (latest feature commit `3190a5b`), working tree clean. Remote: private GitHub repo **https://github.com/Mrwanawad/maison-nile-store** (`origin`, `main` tracks `origin/main`).

---

## 0. Changes made in the latest sessions (2026-10-03)

**Session B: "Cairo pop" frontend redesign (commit `3190a5b`).** The user found the v2 design "basic and AI-looking" and asked for ready-made components, animation and a full polish. They chose: direction **Bold street / Cairo pop**, motion **rich but tasteful**, palette/fonts **free to change**.
- **Identity:** Lalezar (Cairo cinema-poster display, Latin + Arabic, one weight) + Readex Pro (body). Tokens in `src/frontend/static/css/input.css`: chalk `#F6F6F1`, ink `#10133A`, cobalt accent `#1E3FE0` / `#1530B8` (default in `config.py`, `.env.example` and local `.env`), mango `#FFC21A`, hibiscus `#E5306B` (new `hibiscus` token). 2px ink borders, hard offset shadows (`--shadow-pop`), sticker badges (`.badge-sale/.badge-new/.badge-soldout`), `.btn-pop` (mango CTA, one per screen), `.panel-pop`, `.marquee`, `.card`/`.card-media`. Alexandria removed.
- **Components (Preline, vendored per plugin):** overlay (cart drawer, mobile menu, size-guide modal), accordion (product details / delivery), collapse (mobile filters). `app.js` re-inits all three after HTMX swaps.
- **Motion:** Motion One (`motion` npm, vendored to `static/vendor/motion.js`, ~47 KB gz) driven by new `static/js/fx.js`: hero load sequence (`[data-hero]`, `[data-hero-part]`), scroll reveals (`[data-reveal]`, `[data-reveal-stagger]`), header hide-on-scroll (`[data-header]`), cart badge pop + bag wiggle, drawer item cascade, toast entrance. New blocking `static/js/boot.js` adds `.js` before paint; `.fx-off` shows everything if Motion is missing (2.5 s) or reduced motion is on. CSS marquees. Cross-document View Transitions: card photo and product gallery share `view-transition-name: p-<slug>`.
- **Pages:** new `components/announcement.html` (mango ticker); new header/menu/drawer/footer (giant wordmark); home (bilingual poster hero, tilted photo, spinning "New drop / وصل حديثًا" sticker, category marquee, three sticker promise cards, story); listing (mango header + category chips, sticky filter bar); product (accordion, size-guide modal via `hx-select=".prose-store"`); cart, checkout (numbered 1-2-3 steps), order, track, 404, content, error restyled. Email colors updated.
- **New locale keys (EN + AR):** `bar.delivery_short`, `bar.cod`, `bar.exchange`, `bar.made`, `home.sticker`, `home.shop_by`, `home.promise.title`, `filters.toggle`, `product.info`. The rewrite dropped blank lines between key groups in both JSON files (cosmetic).
- **Bugs found and fixed:** the add-form `htmx:configRequest` guard blocked bubbled requests from links inside the form (size guide stuck on the loader); it now checks `e.detail.elt === form`. Marquees rendered empty and the SVG sticker text vanished in RTL; both containers are now `dir="ltr"` (Arabic still shapes; RTL pages scroll the other way).
- **Checks:** 72 pytest pass, ruff + mypy clean, 16/16 Playwright browser checks pass (EN + AR), no JS console errors. Desktop + 390px screenshots reviewed for home, shop, product, drawer, size guide, checkout, menu, filters, 404, AR home, admin login.

**Session A: repo restructure (commits `6437b0d`, `2f64891`, `156b9c4`, `3836bf3`, `baea3aa`).**
- **`src/backend/`**: `app/`, `migrations/`, `scripts/`. pytest `pythonpath`, ruff `src`, mypy `mypy_path`, alembic paths updated; hatchling build so `app` and `scripts` import after `uv sync`.
- **`src/frontend/`**: Tailwind source, `static/`, `package.json`, `scripts/vendor.mjs`. Tailwind `@source` scans `../../../backend/app/views`. `src/frontend/node_modules` is the install location.
- **`docker/`**: `Dockerfile`, `docker-compose.yml`, `Dockerfile.dockerignore`. Compose runs from repo root with `-f docker/docker-compose.yml`. `render.yaml` and CI point to `docker/Dockerfile`.
- **`docs/`**: `DESIGN.md`, `CHECKPOINT.md`. `README.md` stays at root.

---

## 1. Where we are (one paragraph)

The MVP is **built, tested and committed locally**. A bilingual (EN/AR) store for one local brand: products with color × size variants, cart, checkout with cash on delivery or Paymob (Apple Pay), admin panel, Bosta courier, Telegram alerts, customer emails, a JSON API, CI and deployment config. **72 automated tests pass (80% coverage)**, 16 real-browser checks pass, Lighthouse mobile scores are Performance 90–97 / Accessibility 100. **Not deployed yet.** That's the next milestone, and it needs the user's accounts. The user was about to run and test it manually on their machine.

---

## 2. About the user and how to work with them

- Builds this for a client (two business owners who will both be admins). Wants a live MVP first, then pricing talks with the client.
- Windows 10, PowerShell + Git Bash, Docker Desktop, Python 3.12, uv, Node 24.
- **Hard rule: every changeable value lives in `.env`** (brand, logo, WhatsApp, keys, fees, limits, version...).
- Likes: being asked questions up front, then autonomy ("go cook"). Ships fast, MVP mindset.
- Answers to the original scoping questions are in Claude memory (`client-answers-v1`). Summary in section 9 below.

---

## 3. Stack (fixed by the user)

FastAPI + Uvicorn (1 worker) · Jinja2 server-rendered HTML · HTMX 2 · Tailwind CSS v4 (built at build time) + Preline (**overlay, accordion, collapse** plugins) + Motion One (animations) · SQLAlchemy 2 async + asyncpg · Alembic · PostgreSQL 16 locally / Supabase in prod · Pydantic v2 · httpx · slowapi · Pillow · bcrypt · Sentry SDK (optional) · pytest · ruff · mypy --strict.
Hosting plan: Render free web service (Docker) + Supabase free + UptimeRobot + GitHub Actions.

---

## 4. Architecture (modular monolith, MVC + services)

```
src/backend/app/
  main.py          app factory: middleware order, static mounts (CachedStatic), routers, Sentry, config checks
  core/            config.py (Settings from .env), db.py, i18n.py (LocaleMiddleware, t(), url()),
                   security.py (CSRF, order tokens, bcrypt), errors.py (AppError + handlers),
                   middleware.py (request id, access log, CSP/security headers), rate_limit.py, templates.py (Jinja globals), logging.py (JSON)
  controllers/     web/ (shop, cart, checkout, orders, payments, pages), admin/ (auth, orders, catalog), api/v1/routes.py, system.py (health, cleanup), deps.py
  services/        catalog, cart, order, payment, shipping, fraud, notification, shipment, product_admin, admin_auth, nav_cache
  repositories/    catalog_repo.py, order_repo.py  (SQL only)
  integrations/    paymob.py, bosta.py, telegram.py, email/ (brevo|resend), storage/ (local|supabase), sms/ (interface only)
  models/          catalog.py, order.py, admin.py, base.py
  schemas/         checkout.py (CheckoutData shared by HTML + API), api.py
  utils/           money.py (piasters), phone.py (EG mobile normalize), governorates.py (27), images.py (WebP), text.py
  views/           base.html, components/, pages/, partials/, admin/, emails/
  locales/         en.json, ar.json (admin.* keys English only)
  content/         en|ar/*.md: about, shipping-returns, size-guide, faq, contact, privacy, terms (PLACEHOLDER text)
  (src/frontend/static/)  css/input.css (tokens + @font-face + components), js/boot.js (pre-paint .js flag), js/app.js (toasts, drawer, picker, checkout),
                   js/fx.js (Motion One animations); build output: css/app.css, vendor/ (htmx, preline-*, motion), fonts/ (lalezar-*, readex-*) (gitignored)
src/backend/migrations/  Alembic, single initial migration a2cf68da34bd (+ enables RLS on all tables)
src/backend/scripts/ seed.py, create_admin.py, browser_check.py (Playwright)
src/frontend/scripts/vendor.mjs  copies htmx, Preline overlay/accordion/collapse, Motion and fonts into src/frontend/static
tests/             unit/test_utils.py; integration/ test_orders, test_http, test_admin_catalog, test_integrations, test_storefront
.github/workflows/ ci.yml, backup.yml (nightly encrypted pg_dump), cleanup.yml (every 30 min)
docker/Dockerfile  stages: assets (node) → base → dev (compose) / runtime (prod, runs alembic then uvicorn)
docker/docker-compose.yml db (postgres:16), app (dev target, reload), css (tailwind watcher)
render.yaml        Render blueprint (free plan, Frankfurt)
```

Rule: controllers → services → repositories/integrations. Routers never touch SQL.

---

## 5. Data model (key points)

- Money = **integer piasters** everywhere (1 EGP = 100).
- `categories`, `sizes` (global scale with `size_group`: apparel/waist/...), `products` (bilingual, `compare_at_piasters` for sales, no stock column), `product_colors` (per product, hex), `product_variants` (product × color × size, SKU, **stock**, optional price override, `UNIQUE NULLS NOT DISTINCT`), `product_images` (optional `color_id` → gallery switches per color).
- `customers` (latest details per phone), `orders` (copy of shipping details `ship_*`, locale, totals, Paymob fields, `payment_attempts`, Bosta tracking, `stock_restored`, `cancel_reason`), `order_items` (copied names/labels/SKU/price), `order_events` (audit trail with actor), `payment_transactions` (unique Paymob txn id = idempotency), `admin_users`, `phone_blocklist`.
- Enums: order_status (pending/confirmed/shipped/delivered/cancelled), payment_method (cod/paymob), payment_status (unpaid/paid/failed/refunded/partially_refunded).
- Order numbers start at 1001.

---

## 6. Features — DONE ✅

**Storefront**
- EN at `/`, AR at `/ar/...` (RTL, logical CSS). Visual identity "Cairo pop" (DESIGN.md last bullet): Lalezar + Readex Pro, cobalt / mango / hibiscus on chalk, Preline overlay+accordion+collapse, Motion One animations (fx.js), View Transitions.
- Home (bilingual poster hero + sticker, category marquee, featured grid, sticker promise cards, story), shop listing with search / category / size / in-stock filters and sort (HTMX, URL updates), category pages, product page (swatches, size buttons, sold-out marked, "Only N left", sale %, gallery per color, size-guide modal, info accordion, WhatsApp prefilled), related products.
- Cart in signed session cookie (`{variant_id: qty}` only). HTMX slide-out drawer + full cart page, toasts, badge. Quantity capped by stock and `MAX_QTY_PER_LINE`. Cart fixes itself when stock drops or a product is hidden.
- Checkout: inline bilingual validation, Egyptian phone normalization (Arabic digits, +20), governorate select with live fee, details remembered in localStorage, honeypot, double-submit guard.
- Order page via signed link `/order/{id}?t=...`, progress steps, payment-pending polling, retry payment, Bosta tracking link. Track page (order number + phone).
- Content pages from Markdown with `.env` values substituted. Branded 404 and 500 pages (500 is localized and shows a reference id).
- Works without JS for the core flow, except the mobile hamburger menu (mobile filters and accordions fall back to open via `<noscript>` styles).

**Orders & money**
- `order_service.place_order`: one transaction, `SELECT … FOR UPDATE` on variants in id order, prices from DB, stock decremented. Tested: concurrent buyers of the last unit → exactly one succeeds.
- COD protection (`.env`): max COD order total, max open COD orders per phone, admin phone blocklist, honeypot, rate limits. SMS OTP is an interface only (`OTP_PROVIDER=none`).
- Shipping per governorate from `.env` (Alexandria 50, others 100 EGP).
- Status transitions (admin): pending↔confirmed→shipped→delivered; cancel from pending/confirmed/shipped restores stock exactly once.

**Paymob** (built from official docs; never run against a real account)
- Intention API (`POST /v1/intention/`, `Authorization: Token <secret>`), Unified Checkout redirect, `special_reference = <order_id>~<attempt>`.
- Webhook `POST /webhooks/paymob`: HMAC-SHA512 over the documented 20 fields (unit-tested against the docs example), amount/currency check, idempotent, failed attempt keeps the order pending for retry.
- Return page `/payments/paymob/return` does **not** trust query params; asks the inquiry API if `PAYMOB_API_KEY` is set.
- Cleanup `POST /internal/cleanup` (Bearer `INTERNAL_CRON_TOKEN`): reconciles with Paymob, then cancels unpaid orders older than `UNPAID_ORDER_TIMEOUT_MIN` and restores stock. A late payment re-reserves stock or is flagged "needs refund".
- Refunds from admin (`/api/acceptance/void_refund/refund`).

**Admin** (`/admin`, English UI, `admin_users` table, bcrypt, session login, rate-limited)
- Dashboard (today / 7 days, status counts, low stock), orders list (search/filter, HTMX), order detail (status change, notes, history, refund, "Create Bosta shipment", "Check with Paymob").
- Products: create/edit bilingual, colors, sizes → auto-generated variant grid (stock, price override, SKU, offered). Retired empty combos are deleted; ones with stock are hidden. Photo upload → WebP 1280px + 480px thumbnail. Reorder, link to color, delete.
- Categories (menu updates instantly via `nav_cache`), sizes, COD blocklist.
- Admin form errors (including 502 third-party failures) show as a flash message on the same page.

**Integrations**
- Telegram (new order, payment result, low stock) to every chat id. Brevo (default) / Resend customer confirmation email (EN/AR templates). Bosta create delivery. Supabase Storage. All run in background tasks and never break checkout. With no keys they only log.

**Cross-cutting**
- CSRF (session token, form field or `X-CSRF-Token`; HTMX sends it via `hx-headers`). CSP (no inline JS; htmx eval disabled), nosniff, DENY frames, HSTS in prod, httponly + samesite=lax cookie (secure in prod).
- JSON logs with request id. Optional Sentry. gzip. Static files are cached as immutable with **content-hash** URLs.
- JSON API `/api/v1`: products, product detail, categories, shipping rates, create order, get order (token). Docs at `/api/docs` outside production.
- Production refuses to start with default `SECRET_KEY` / `INTERNAL_CRON_TOKEN` or a non-https `BASE_URL`.

**Quality**
- 72 pytest tests on real Postgres (database `store_test`, created automatically); fake HTTP transport for third parties.
- `src/backend/scripts/browser_check.py`: 16 Playwright checks (EN + AR, 390px; opens the mobile filter panel before picking a size).
- ruff + mypy --strict clean. Pre-commit config present (not installed yet: `uv run pre-commit install`).
- Lighthouse mobile (before the v3 redesign): Performance 90–97, Accessibility 100, Best practices 100. **Not re-measured after v3** (Motion + 2 Preline plugins + Lalezar added; re-run before deploy).

---

## 7. DUE / not done ⏳

1. **Deploy (milestone 8).** GitHub repo exists (private, `Mrwanawad/maison-nile-store`). Still needs from the user: Supabase project (pooler URL + service key + public bucket `products`), Render account (Blueprint from `render.yaml`), UptimeRobot on `/health`, and GitHub secrets `SITE_URL`, `INTERNAL_CRON_TOKEN`, `BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE`. Then create both admins with `src/backend/scripts/create_admin.py` in the Render shell. Steps are in README → "Deploying".
2. **Client inputs:** logo, accent color, Arabic brand name/tagline, WhatsApp/social/support contacts, Paymob (KYC + secret/public/HMAC/API keys + Apple Pay integration id; callback URL `https://<site>/webhooks/paymob`), Bosta API key (+ pickup location id), Telegram bot token + owner chat ids, Brevo verified sender, real photos, size chart, return/privacy/terms text, custom domain.
3. **Verify against live accounts:** Paymob (Apple Pay can't be tested in Paymob test mode and likely needs a custom domain); Bosta payload (city names/fields may need adjusting; city = governorate English name).
4. User's **manual local testing** (instructions were given; README has them). Await their feedback.
5. Deferred by the user to future versions: Meta Pixel / CAPI, GA4, sitemap / OG / structured data / product feeds, SMS OTP provider, Bosta status webhook, customer accounts, discounts/coupons.
6. Re-run Lighthouse after the v3 redesign; check contrast of white text on hibiscus and of mango/ink pairs; real campaign photos will matter a lot for the poster hero.
7. Nice-to-have, not started: mobile menu without JS, admin UI in Arabic, image `srcset` for pasted external image links (only Unsplash and our own uploads get srcset), shrinking the 565 MB Docker image.

---

## 8. Problems hit & how they were solved (and what's still open)

**Solved**
- SQLAlchemy async "MissingGreenlet" after `rollback()` expired ORM objects. This caused real bugs (duplicate webhook, Paymob outage on checkout/retry, cleanup job). Fixes: capture ids before rollback; `start_checkout` now **commits** the failed attempt instead of rolling back; `populate_existing` on locked/reloaded queries; cleanup works by ids.
- The friendly 500 page crashed because the last-resort handler runs **outside** SessionMiddleware → `has_session()` guards. Its locale and request id are restored from the scope.
- Paymob down → crash. Product delete leaked thumbnails. Saved governorate didn't refresh the fee (JS ran before htmx init → DOMContentLoaded). Stale CSS/JS after deploy (now content-hash). Admin 502 errors showed a generic page. Variant grid filled with retired rows. All fixed and tested.
- Header nav overflowed at 768px → desktop nav moved to the `lg` breakpoint. RTL discount badge "19%-" → `dir="ltr"`. Mobile card name/price cramped → stacked.
- Lighthouse 63–84 → 90–97: Google Fonts were render-blocking → self-hosted fonts; gzip; immutable caching; responsive srcset.
- Seed photo IDs were mis-mapped (a logo tee showed) → verified with a contact sheet, remapped, logo images avoided.
- Tailwind v4: can't `@apply` component classes → use `class="btn btn-primary"`; `peer-checked:` needs utilities, not component classes.
- HTMX filter syntax (`load[this.value]`) needs eval, which CSP blocks → removed; `allowEval:false`.
- Paymob redirect params can't be trusted → inquiry API reconciliation instead.
- v3 redesign: a form-level `htmx:configRequest` listener also catches events bubbling from child elements with `hx-*` → always check `e.detail.elt`.
- v3 redesign: CSS marquees and SVG `textPath` break in RTL documents → give those containers `dir="ltr"`.
- Tailwind v4: `@apply` of a custom component class (e.g. `.sticker`) fails → group selectors share one `@apply` instead.

**Environment quirks (Windows)**
- Docker Desktop is not running after a reboot → start it (`"C:\Program Files\Docker\Docker\Docker Desktop.exe"`), then `docker compose -f docker/docker-compose.yml up -d db`. Tests fail with `ConnectionRefusedError` otherwise.
- `uvicorn --reload` hung once after a change → restart, or run without `--reload`.
- Git Bash heredocs sometimes mangle content/backslashes (long Python heredocs with Jinja and quotes fail with `unexpected EOF`) → write files with the Write tool or a Python script file instead. Use `MSYS_NO_PATHCONV=1` when passing `/paths` as args to Python.
- The Chrome extension window can't be resized (maximized) → use headless Playwright for viewport screenshots (`uv run --with playwright ...`; chromium already installed).
- CRLF warnings on commit are harmless (`.gitattributes` normalizes to LF).

**Open / risks**
- Paymob and Bosta untested against real accounts (see section 7).
- Placeholder content: brand "Maison Nile", policies, size chart, Unsplash photos (the biker jacket photo shows a small "ZARA" label).
- `orders.paymob_client_secret` is stored but never read (harmless; could be dropped in a future migration).
- Dev admin `owner` exists in the local DB with a dev-only password; the user was told to reset it with `create_admin`.

---

## 9. Client decisions (from scoping, 2026-10-02)

One brand; placeholders for brand; EN+AR ~75/25 with modern Arabic fonts; 30–40 products, ~100 req/day, Instagram ads later; size/color variants; categories/search/filters; sale prices; multiple images; admin product CRUD; 2 owner-admins; admin cancel restores stock; all governorates (Alexandria 50, others 100, configurable); no free-shipping threshold; COD protection without manual call-confirm; Bosta; no split payment; Telegram alerts; customer email via free tier; Paymob not yet set up (build everything, client sets up later); **Apple Pay** first; refunds from admin; MVC + services modular monolith; JSON API yes; live MVP on free tier first; pixels/SEO later; static pages decided by Claude; WhatsApp/Instagram placeholders; Windows + Docker; stack fixed.

---

## 10. Commands cheat-sheet (PowerShell, project root)

```powershell
docker compose -f docker/docker-compose.yml up -d db   # database (Docker Desktop must be running)
uv sync; cd src/frontend; npm ci; npm run build; cd ../..   # deps + CSS/fonts/vendored JS
uv run alembic upgrade head
uv run python -m scripts.seed           # demo catalog (no-op if not empty; --reset to reload)
uv run python -m scripts.create_admin owner "Name"
uv run uvicorn app.main:app --app-dir src/backend --reload   # http://localhost:8000  /ar  /admin  /api/docs
cd src/frontend; npm run watch:css; cd ../..   # while editing templates
uv run pytest                           # 72 tests
uv run ruff check . ; uv run ruff format --check . ; uv run mypy src/backend/app
uv run --with playwright python -m scripts.browser_check   # needs app running
docker compose -f docker/docker-compose.yml up        # Docker-only path (db + app + css watcher)
```

Local DB state at hand-off: 10 demo products, 0 orders, 1 admin (`owner`).

## 11. Commit log

```
3190a5b feat: "Cairo pop" storefront redesign with Preline components and Motion animations
baea3aa docs: move DESIGN and CHECKPOINT into docs/ and fix paths
3836bf3 refactor: move Docker config into docker/
156b9c4 docs: update paths for src/backend and src/frontend split
2f64891 refactor: split frontend assets into src/frontend
6437b0d refactor: move backend code into src/backend
262c02e docs: add CHECKPOINT.md hand-off for new sessions
a462c73 chore: add browser end-to-end check script
ebbc76d fix: restore delivery fee after saved checkout details; content-hash static URLs
2466c5f fix: audit fixes from expanded test suite
29af8e4 feat: tests, CI/deploy config, performance and responsive fixes
d090985 feat: bilingual storefront, checkout, admin and integrations MVP
```

## 12. Suggested next steps for the new session

1. Ask the user for feedback on the v3 "Cairo pop" design and their manual test; fix what they report.
2. Check the first GitHub Actions CI run on `origin/main` and fix anything red; add the repo secrets listed in section 7.1.
3. Get the deployment accounts (section 7.1) and deploy; verify `/health`, the storefront and admin on the live URL; set up UptimeRobot and the GitHub secrets.
4. Once client keys arrive: test Paymob in test mode end to end (card first, then Apple Pay on a custom domain), test a Bosta staging shipment, test Telegram and Brevo.
5. Replace placeholder content and photos; then hand over to the client.
