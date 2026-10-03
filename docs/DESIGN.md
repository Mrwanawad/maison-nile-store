# DESIGN.md: Local Brand E-commerce Store (MVP)

> Single source of truth for the build. **Section 15 records the v1 decisions (2026-10-02) and overrides earlier sections where they differ.** Follow it in order. If something here conflicts with official third-party docs (Paymob, Supabase, Render, Preline), **the official docs win**: verify, never guess an API.

---

## 1. Overview

A minimal, fast online store for a local Egyptian brand.

**Customer journey:** browse products → product page → add to cart → checkout → pay with **Paymob** (Apple Pay / cards / wallets) **or Cash on Delivery** → order confirmation.

### Goals
- Ship a working MVP fast, on **$0 infrastructure**.
- Clean, warm, brand-like UI that does **not** look AI-generated or template-made.
- Correct money handling: server-side prices, atomic stock, verified payments.

### Non-goals (v1)
- Customer accounts / login (guest checkout only)
- Discounts, coupons, reviews, wishlists, multi-currency
- Email/SMS/WhatsApp notifications
- Full admin product CRUD (products are managed in the Supabase dashboard for v1)

---

## 2. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | Type hints everywhere |
| Web framework | FastAPI + Uvicorn | Single process, 1 worker |
| Templating | Jinja2 (server-rendered HTML) | SEO-friendly, no SPA |
| Interactivity | HTMX 2.x | Cart updates, partial swaps, no page reloads |
| UI components | **Preline UI** (Tailwind v4) | Framework-agnostic HTML components + small JS plugins (offcanvas, dropdown, carousel) |
| CSS | Tailwind CSS v4 | Compiled at **build time** (Node only in the Docker build stage; runtime is pure Python) |
| Validation | Pydantic v2 + pydantic-settings | Request schemas + env config |
| DB | Supabase Postgres | SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic | Plus raw SQL for the `place_order` function |
| Images | Supabase Storage (public bucket) | Pre-compressed WebP, ≤ 200 KB each |
| Payments | Paymob Intention API + Unified Checkout (hosted) | Apple Pay, cards, wallets; COD handled in-app |
| HTTP client | httpx (async) | Paymob calls |
| Sessions | Starlette `SessionMiddleware` (signed cookie) | Holds cart + admin session |
| Hosting (MVP) | Render free Web Service (Docker) | Kept warm by UptimeRobot |
| Backups | GitHub Actions nightly `pg_dump` | Supabase free has no backups |
| Lint/format/test | ruff, mypy, pytest + pytest-asyncio | |

---

## 3. Architecture

```
Browser (HTML + HTMX + Preline JS)
        │  HTTPS
        ▼
FastAPI on Render (Docker)
  ├── routers/      → pages, HTMX partials, checkout, webhooks, admin
  ├── services/     → cart, orders, payments (business logic)
  ├── repositories/ → SQL access only
  │
  ├──► Supabase Postgres  (orders, products, customers)
  ├──► Supabase Storage   (product images, public URLs)
  └──► Paymob API         (create intention → redirect to hosted checkout)
            │
            └── POST /webhooks/paymob  (HMAC-verified) ──► update order
```

**Layering rule:** routers → services → repositories. Routers never touch SQL. Repositories hold no business logic. Services are unit-testable without HTTP.

---

## 4. Project Structure

```
.
├── src/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── main.py                 # app factory, middleware, static mount, Preline/HTMX wiring
│   ├── config.py               # pydantic-settings Settings
│   ├── db.py                   # async engine + session dependency
│   ├── models/                 # SQLAlchemy ORM models
│   ├── schemas/                # Pydantic request/response schemas
│   ├── repositories/           # products_repo.py, orders_repo.py, customers_repo.py
│   ├── services/               # cart_service.py, order_service.py, paymob_service.py
│   ├── routers/                # shop.py, cart.py, checkout.py, webhooks.py, admin.py, health.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── components/         # product_card.html, cart_drawer.html, price.html, badge.html, ...
│   │   ├── pages/              # home.html, product.html, cart.html, checkout.html, order.html, 404.html
│   │   └── admin/
│   └── static/
│       ├── css/input.css       # Tailwind entry + design tokens
│       ├── css/app.css         # build output (gitignored)
│       ├── js/app.js           # HTMX ↔ Preline re-init, tiny helpers
│       └── img/
│   ├── migrations/             # Alembic
│   │   └── scripts/seed.py
│   └── frontend/
│       ├── package.json        # tailwindcss, @tailwindcss/cli, preline (build-only)
│       └── scripts/vendor.mjs
├── sql/place_order.sql         # Postgres function
├── tests/
├── docker/Dockerfile           # multi-stage: node (css build) → python (runtime)
├── pyproject.toml
├── .env.example
└── DESIGN.md
```

---

## 5. Data Model

All money is stored as **integer piasters** (1 EGP = 100 piasters). Never use floats for money.

```sql
create type order_status   as enum ('pending','confirmed','shipped','delivered','cancelled');
create type payment_method as enum ('cod','paymob');
create type payment_status as enum ('unpaid','paid','failed','refunded');

create table products (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  slug            text not null unique,
  description     text not null default '',
  price_piasters  integer not null check (price_piasters > 0),
  image_url       text not null,
  stock           integer not null default 0 check (stock >= 0),
  is_active       boolean not null default true,
  sort_order      integer not null default 0,
  created_at      timestamptz not null default now()
);

create table customers (
  id          uuid primary key default gen_random_uuid(),
  full_name   text not null,
  phone       text not null unique,      -- Egyptian mobile, normalized 01XXXXXXXXX
  email       text,
  address     text not null,
  city        text not null,
  created_at  timestamptz not null default now()
);

create table orders (
  id                  uuid primary key default gen_random_uuid(),
  order_number        bigint generated always as identity unique,  -- human-friendly #1001...
  customer_id         uuid not null references customers(id),
  status              order_status   not null default 'pending',
  payment_method      payment_method not null,
  payment_status      payment_status not null default 'unpaid',
  subtotal_piasters   integer not null,
  shipping_piasters   integer not null,
  total_piasters      integer not null,
  paymob_intention_id text,
  paymob_txn_id       text unique,          -- idempotency for webhooks
  notes               text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table order_items (
  id                   uuid primary key default gen_random_uuid(),
  order_id             uuid not null references orders(id) on delete cascade,
  product_id           uuid not null references products(id),
  product_name         text not null,       -- snapshot at purchase time
  quantity             integer not null check (quantity > 0),
  unit_price_piasters  integer not null
);

create index on orders (created_at desc);
create index on orders (status);
```

### `place_order` (Postgres function, atomic)
- Input: customer fields, payment method, items `[{product_id, quantity}]`, shipping fee.
- Locks product rows (`SELECT ... FOR UPDATE`), checks `is_active` and stock, **reads prices from DB**, decrements stock, upserts customer by phone, inserts order + items, returns `order_id`, `order_number`, `total_piasters`.
- Raises a clear error on insufficient stock (map to a friendly UI message).

### Row Level Security
- Enable RLS on all tables. No anon policies are needed: the app connects with a server-side DB role. Never expose DB credentials or the service-role key to the browser.

---

## 6. Core Flows

### 6.1 Cart
- Cart lives in the signed session cookie: `{product_id: quantity}` only. **Never** store prices client-side.
- Cart rendering always re-reads products from DB.
- HTMX endpoints return partials: cart drawer, cart count badge (`hx-swap-oob`).
- Max quantity per line = min(stock, 10).

### 6.2 Checkout
1. Form: full name, phone (Egyptian mobile regex `^01[0125][0-9]{8}$`), optional email, city (select), address, notes, payment method.
2. Server validates (Pydantic), calls `place_order`.
3. **COD:** order `pending/unpaid` → clear cart → redirect `/order/{id}?t={token}`.
4. **Paymob:** create intention with amount = DB `total_piasters`, attach `special_reference = order_id` → store intention id → redirect to Paymob Unified Checkout.

### 6.3 Payment confirmation (two paths, idempotent)
- **Webhook** `POST /webhooks/paymob` (processed callback): verify HMAC per Paymob docs → match order → if `success`: `payment_status=paid`, `status=confirmed`; if failed: `payment_status=failed`, `status=cancelled`, **restore stock**. Ignore duplicates via `paymob_txn_id`.
- **Redirect** `GET /payments/paymob/return`: verify HMAC on query params, apply the same idempotent update, then show the order page.
- Either path alone must be sufficient (covers cold-start misses).

### 6.4 Abandoned online orders
- `POST /internal/cleanup` (bearer token from env), called by a GitHub Actions cron every 30 min: cancel `paymob` orders still `unpaid` after 45 min and restore stock.

### 6.5 Order page
- `/order/{id}?t={token}`: token = HMAC of order id with `SECRET_KEY`, so order pages aren't guessable.

---

## 7. Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Home: hero + product grid |
| GET | `/p/{slug}` | Product page |
| GET | `/cart` | Full cart page (fallback for no-JS) |
| POST | `/cart/items` | Add item (HTMX → drawer + badge) |
| PATCH | `/cart/items/{product_id}` | Change qty (HTMX) |
| DELETE | `/cart/items/{product_id}` | Remove (HTMX) |
| GET | `/checkout` | Checkout form |
| POST | `/checkout` | Place order |
| GET | `/payments/paymob/return` | Paymob redirect target |
| POST | `/webhooks/paymob` | Paymob processed callback |
| GET | `/order/{id}` | Confirmation (token-protected) |
| GET | `/health` | `SELECT 1`, returns 200 (UptimeRobot) |
| POST | `/internal/cleanup` | Abandoned-order cleanup (token) |
| GET/POST | `/admin/login`, `/admin/logout` | Single admin, credentials from env (bcrypt hash) |
| GET | `/admin/orders` | List + filter by status |
| POST | `/admin/orders/{id}/status` | Update status (HTMX) |

---

## 8. UI & Design System

### 8.1 Direction
**"Warm boutique, not tech startup."** It should feel like a small, confident fashion/lifestyle brand: editorial typography, generous whitespace, real product photography doing the heavy lifting, restrained color. Think independent shop, not SaaS dashboard.

### 8.2 Hard bans (things that make it look AI-generated)
- ❌ **No purple, violet, indigo, or purple→blue gradients. Anywhere.**
- ❌ No black + neon / dark-mode-by-default "hacker" look.
- ❌ No Inter, Roboto, Arial, or system-ui as the visible brand font.
- ❌ No glassmorphism, glowing borders, or blurry gradient blobs.
- ❌ No emoji in UI copy. No "✨ Discover amazing products ✨" style text.
- ❌ No identical rounded-2xl cards with heavy drop shadows everywhere.
- ❌ No generic stock hero illustrations or 3D blobs.
- ❌ No centered-everything layouts. Use editorial alignment (left-aligned text, asymmetric hero).

### 8.3 Typography (Google Fonts)
| Role | Font | Usage |
|---|---|---|
| Display / headings | **Fraunces** (variable, opsz) | H1–H3, hero, prices on product page. Weight 400–600, slight negative tracking on large sizes |
| Body / UI | **Manrope** | Body, buttons, forms, nav. Weight 400/500/600 |
| Arabic (fallback / future RTL) | **IBM Plex Sans Arabic** | Any Arabic text; add to the font stack now |

- Base size 16px, line-height 1.6 body / 1.1 headings.
- Uppercase + letter-spacing `0.08em` only for tiny labels (e.g. "NEW", category tags).
- Prices: tabular numerals (`font-variant-numeric: tabular-nums`). Format: `1,250 EGP`.

### 8.4 Color tokens
Placeholder palette. **Replace accent with the brand's logo color when available** (must not be purple).

```css
@theme {
  --color-bone:       #F6F3EE; /* page background (warm off-white) */
  --color-paper:      #FFFFFF; /* cards, drawers */
  --color-ink:        #1C1B19; /* primary text, primary buttons */
  --color-ink-soft:   #5C5A55; /* secondary text */
  --color-line:       #E4DFD6; /* borders, dividers */
  --color-accent:     #B4532A; /* terracotta: links, sale badges, focus */
  --color-accent-ink: #8E3F1E; /* accent hover */
  --color-olive:      #4A5A3F; /* success / "in stock" */
  --color-danger:     #B42318; /* errors, out of stock */
}
```

- Primary button: `bg-ink text-bone`, hover slightly lighter. Secondary: outline `border-ink`.
- Accent is used **sparingly** (≤ 5% of the screen).
- Contrast: all text meets WCAG AA.

### 8.5 Shape, spacing, motion
- Radius: `4px` inputs/buttons, `0`–`6px` images. **Not** pill-everything.
- Borders over shadows: 1px `--color-line`. Shadow only on the open cart drawer.
- Spacing scale: Tailwind default; sections `py-16 md:py-24`.
- Motion: 150–200ms ease-out on hover/opacity only. Image hover: subtle `scale-[1.02]`. Respect `prefers-reduced-motion`.

### 8.6 Components (Preline UI base, restyled with tokens above)
Use Preline markup and JS plugins, then override visuals with the design tokens. Do not ship Preline's default blue.

| Component | Preline plugin / pattern | Notes |
|---|---|---|
| Header | Navbar (sticky) | Logo left, minimal nav, cart icon + count badge right. Collapses to offcanvas on mobile |
| Cart drawer | **Offcanvas** (right) | Opens on add-to-cart; HTMX-swapped content; subtotal + "Checkout" CTA |
| Product card | Custom (template) | 4:5 image, name (Manrope 500), price (tabular), "Sold out" overlay when stock = 0. No card shadow |
| Product gallery | **Carousel** | Swipe on mobile, thumbnails on desktop |
| Quantity stepper | Input number pattern | − / + buttons, HTMX on change |
| Forms | Preline inputs | Labels above inputs, inline error text in `--color-danger` |
| Payment method | Radio cards | "Pay online (Apple Pay, cards, wallets)" / "Cash on delivery" |
| Toast | Preline toast/alert | "Added to cart", errors. Auto-dismiss 3s |
| Admin table | Table pattern | Plain, dense, status select per row |

**Icons:** Lucide (outline, 1.5px stroke), inline SVG.

### 8.7 HTMX ↔ Preline wiring (required)
Preline plugins must be re-initialized after HTMX swaps new DOM in:

```js
document.addEventListener("htmx:afterSwap", () => {
  window.HSStaticMethods?.autoInit();
});
```

### 8.8 Page specs
- **Home:** asymmetric hero (large Fraunces headline left, one real product/lifestyle photo right), short brand line, then product grid (2 cols mobile / 3 tablet / 4 desktop). Footer: contact, Instagram, shipping/returns links.
- **Product:** gallery left, details right (sticky on desktop): name, price, stock state, quantity, "Add to cart" (full-width on mobile), description, shipping note.
- **Cart:** line items with thumbnail, stepper, remove; summary with subtotal, shipping, total.
- **Checkout:** single column on mobile, two columns on desktop (form left, order summary right). One primary CTA: "Place order" / "Continue to payment".
- **Order confirmation:** order number large, items, total, payment state, "we'll call you to confirm" for COD.
- **404 / errors:** on-brand, short copy, link home.

### 8.9 Quality bar
- Mobile-first; test at 360px, 768px, 1280px.
- Lighthouse mobile: Performance ≥ 90, Accessibility ≥ 95.
- Images: `loading="lazy"`, explicit `width`/`height`, WebP, `srcset` where available.
- Every interactive element keyboard-reachable with a visible focus ring (`--color-accent`).
- Works without JS for core flow (forms post normally; HTMX enhances).

---

## 9. Security

- Prices, totals, and stock are computed **server-side only**.
- Paymob: verify HMAC on webhook and redirect; amount/currency must match the stored order; process each transaction once.
- Secrets only in env vars; `.env` gitignored; never logged.
- CSRF: double-submit token on all POST/PATCH/DELETE forms (HTMX sends it via `hx-headers`). Webhook route is exempt but HMAC-verified.
- Session cookie: `httponly`, `secure`, `samesite=lax`.
- Rate limit `POST /checkout` and `/admin/login` (simple in-memory limiter is fine for 1 worker).
- Admin password stored as bcrypt hash in env.
- Security headers: CSP (allow self + Google Fonts + Supabase storage + Paymob), `X-Content-Type-Options`, `Referrer-Policy`.

---

## 10. Configuration (`.env.example`)

```
APP_ENV=development
SECRET_KEY=change-me
BASE_URL=http://localhost:8000

DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/postgres
SUPABASE_STORAGE_PUBLIC_URL=https://<project>.supabase.co/storage/v1/object/public/products

PAYMOB_SECRET_KEY=
PAYMOB_PUBLIC_KEY=
PAYMOB_HMAC_SECRET=
PAYMOB_INTEGRATION_IDS=        # comma-separated (card, apple pay, wallet)

SHIPPING_FEE_PIASTERS=6000
FREE_SHIPPING_THRESHOLD_PIASTERS=0   # 0 = disabled

ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=
INTERNAL_CRON_TOKEN=
```

Use Supabase's **connection pooler** URL (transaction mode) and disable asyncpg prepared statement caching (`statement_cache_size=0`) for compatibility with the pooler.

---

## 11. Deployment

### MVP ($0)
- **Render free Web Service** from `docker/Dockerfile`:
  - Stage 1 (node:lts-slim): `npm ci && npx @tailwindcss/cli -i src/frontend/static/css/input.css -o src/frontend/static/css/app.css --minify`; copy Preline JS from `node_modules`.
  - Stage 2 (python:3.12-slim): install deps, copy src/backend + built assets, run `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers`.
- **UptimeRobot:** ping `/health` every 10 min. Keeps Render awake **and** keeps Supabase from pausing.
- **GitHub Actions:**
  - `backup.yml`: nightly `pg_dump` → encrypted artifact (retain 14 days).
  - `cleanup.yml`: every 30 min → `POST /internal/cleanup`.
- Paymob in **test mode** until the merchant's KYC is approved. COD works from day one.

### Launch upgrade (client pays)
- Always-on instance: Render Starter or Railway (~$5–7/mo). No code changes; same image.
- Custom domain on Cloudflare (~$10/yr), proxied for caching + DDoS. **Required for Apple Pay domain verification.**
- Later: Supabase Pro ($25/mo) for daily backups and no pausing.

---

## 12. Testing

- **Unit:** cart math, piaster formatting, phone validation, HMAC verification (known Paymob test vectors from docs), order token signing.
- **Integration (pytest + test DB):** `place_order` happy path, insufficient stock, concurrent orders on the last unit (no oversell), webhook idempotency, failed payment restores stock.
- **Manual QA checklist:** add/remove/update cart, COD order end-to-end, Paymob test card success + failure, mobile Safari layout, keyboard navigation.

---

## 13. Build Plan (in order)

1. Scaffold project, config, Dockerfile, Tailwind + Preline build, base template with fonts and tokens.
2. DB schema via Alembic + `place_order` SQL function + seed script (6–8 sample products).
3. Shop pages: home grid, product page.
4. Cart (session + HTMX drawer + badge).
5. Checkout + COD flow + order confirmation page.
6. Paymob intention, redirect, webhook, return handler, cleanup endpoint.
7. Admin: login, orders list, status updates.
8. Security pass (CSRF, headers, rate limits), tests.
9. Deploy to Render, UptimeRobot, GitHub Actions backups/cleanup.
10. Design QA against section 8 (bans, typography, contrast, Lighthouse).

---

## 14. Open Questions (ask the client)

- Brand name, logo, and primary brand color (replaces `--color-accent`).
- Language: English only, Arabic only, or both (RTL)?
- Shipping: flat fee or per-city? Which cities are served?
- Product variants needed (sizes/colors)? *(Not in v1 schema; adding them later means a `product_variants` table.)*
- Return/exchange policy text and contact channels (WhatsApp, Instagram).

---

## 15. v1 decisions (2026-10-02, override the sections above)

### Scope added to v1
- **Bilingual EN/AR.** English at `/`, Arabic at `/ar/...` (RTL). UI text in `src/backend/app/locales/{en,ar}.json`; product/category/color/size names stored in both languages. Arabic fonts: Alexandria (headings) + IBM Plex Sans Arabic (body). Admin is English only.
- **Variants.** Global `sizes` table (grouped: apparel, waist, ...), per-product `product_colors`, and `product_variants` = product × color × size with its own SKU, stock and optional price override (`UNIQUE NULLS NOT DISTINCT`). `product_images.color_id` ties photos to a color. Products have no stock column.
- **Categories, search, filters** (category, size, in stock, sort) and compare-at sale prices.
- **Admin product management** (create/edit, colors, sizes, variant stock grid, photo upload → WebP), categories, sizes, COD phone blocklist, order notes, audit trail (`order_events`). Admins live in `admin_users` (bcrypt), created with `scripts/create_admin.py`.
- **Orders keep a copy of the shipping details** (`ship_*` columns); `customers` holds the latest details per phone.
- **Shipping** per governorate from `.env`: `SHIPPING_DEFAULT_FEE_EGP=100`, `SHIPPING_FEE_OVERRIDES=alexandria:50`. 27 governorates in `src/backend/app/utils/governorates.py`.
- **COD protection** (`.env`): max COD order total, max open COD orders per phone, phone blocklist, honeypot, rate limits. SMS OTP is an interface only (`OTP_PROVIDER=none`).
- **Notifications** (background tasks, never block checkout): Telegram to the owners; customer confirmation email via Brevo (or Resend once a domain exists).
- **Bosta**: "Create shipment" in admin; tracking number stored and shown to the customer.
- **Refunds** from admin via Paymob's refund API.
- **JSON API** `/api/v1` (products, categories, shipping rates, create/get order) sharing the same services.

### Implementation choices that differ from earlier sections
- `place_order` is implemented in Python (`order_service.place_order`) as one transaction that locks variant rows with `SELECT ... FOR UPDATE` in id order, reads prices from the locked rows and decrements stock. No SQL function. Concurrency is covered by tests.
- Paymob: one order may have several payment attempts (`special_reference = <order_id>~<attempt>`), every transaction is stored in `payment_transactions` (unique Paymob id = idempotency). A failed attempt keeps the order pending so the customer can retry; the cleanup job cancels it after `UNPAID_ORDER_TIMEOUT_MIN`. The return redirect is not trusted: if the webhook has not arrived, the app asks Paymob's inquiry API (needs `PAYMOB_API_KEY`). A payment arriving after cancellation re-reserves stock or is flagged for refund.
- CSRF uses a synchronizer token stored in the signed session (form field or `X-CSRF-Token` header).
- Only Preline's overlay plugin is shipped (cart drawer, mobile menu); the gallery is CSS scroll-snap.
- Architecture folders: `controllers/` (C), `views/` (V), `models/` (M) plus `services/`, `repositories/`, `integrations/`, `schemas/`, `utils/`, `core/`.

### Deferred (future versions)
Meta Pixel / Conversions API, GA4, sitemap / Open Graph / structured data / product feeds, SMS OTP provider, Bosta status webhooks, customer accounts, discounts.
