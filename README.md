# Kabinet

A faster, friendlier wrapper around UNEC's student cabinet
(`kabinet.unec.edu.az`). Pulls schedule, grades, exam results and teaching
materials into a single mobile-first PWA, with push notifications for
upcoming lessons and new marks.

> Pet project, not affiliated with UNEC. Use at your own risk.

## What it does

- **Today** — live countdown to the next class, recent marks list with
  lesson time, current attendance & grade snapshot.
- **Schedule** — week view, period filters, multi-week parities.
- **Journal** — per-subject marks, attendance %, current pre-exam score.
- **Exams** — past results with question-level breakdown (incl. scanned
  written-answer images), upcoming exams.
- **Materials** — browse & download lecture / presentation / test files
  per subject + teacher; cached so repeat opens are instant.
- **Push** (web + standalone PWA): 10-min-before-class reminder, morning
  brief, new-mark and exam-result notifications.
- **Admin panel** — user list, manual sync triggers, persistent log
  viewer, test-push.

## Stack

- **Backend** — Python 3.13, FastAPI, SQLAlchemy 2 async, Postgres 16,
  Redis 7, ARQ workers, httpx + selectolax for scraping, Argon2,
  envelope-encrypted secrets (`MultiFernet`), JWT in HttpOnly cookies,
  slowapi rate limiting, `pywebpush` for VAPID.
- **Frontend** — Vue 3, Vite 6, Tailwind CSS 4, Pinia, vue-router,
  ofetch, vite-plugin-pwa with a custom Workbox service worker.
- **Infra** — Docker Compose, Caddy with auto-TLS, GitHub Actions CI +
  SSH-based auto-deploy, healthchecks, alembic migrations on container
  start in prod, daily Postgres dump rotation.

## Quick start (dev)

Requires Docker + Docker Compose v2.

```bash
git clone <this repo>
cd <repo>
cp .env.example .env
# generate dev secrets:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" >> .env
# put it as FERNET_KEY=
python -c "import secrets; print(secrets.token_urlsafe(48))"
# put it as SECRET_KEY=
docker compose up -d --build
docker compose exec api alembic upgrade head
```

API on `http://localhost:8000`, frontend served separately:

```bash
cd frontend
npm install
npm run dev   # http://localhost:5174
```

## Production deployment

See [`DEPLOY.md`](./DEPLOY.md). Short version: a single VPS running the
Compose stack behind Caddy. CI auto-deploys on `main` when tests pass.

## Architecture notes

- Per-user **envelope encryption**: a user's UNEC password is encrypted
  with a per-user DEK; the DEK is itself encrypted with the app KEK
  (rotatable via `unec rotate-kek`). Compromising one tier alone
  reveals nothing.
- All mutating endpoints require **HttpOnly auth cookies** with
  `SameSite=Lax`; refresh-token cookie is path-scoped to `/v1/auth`.
- **PWA install** behaves natively: install prompt on Android, manual
  iOS shortcut, full offline cache for read-only views via Workbox.
- **Push** uses the Web Push API + VAPID; iOS requires standalone PWA
  install (Apple's restriction).
- All UNEC-side requests go through a **session manager** with a small
  Redis-backed PHPSESSID cache and a per-user redis lock to prevent
  thundering-herd re-logins.

## Contributing

Issues and PRs welcome. The CI runs pytest + a Vue type-check + the
production frontend build on every PR; deploy fires only after a green
push to `main`.

## License

MIT — see [LICENSE](./LICENSE).
