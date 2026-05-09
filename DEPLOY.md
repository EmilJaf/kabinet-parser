# Deploy runbook

Production stack: Caddy (TLS) → FastAPI (uvicorn) + ARQ worker → Postgres + Redis. All in one Docker Compose project on a single VPS.

## 0. Что нужно до начала

- [ ] **VPS** (Ubuntu 22.04+, 2 vCPU / 2 GB RAM хватит на старт). Hetzner CX22 / DO basic / любой.
- [ ] **Домен** с возможностью править DNS.
- [ ] **A-запись** `kabinet.example.com → <ip-сервера>`. Подождать пока резолвится: `dig +short kabinet.example.com`.
- [ ] **Порты 80/443/22** открыты на сервере.
- [ ] Установлен **Docker + compose-plugin** на сервере.

```bash
# на свежем Ubuntu
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER  # перелогиниться после
```

## 1. Подготовка сервера

```bash
ssh root@<ip>
adduser deploy && usermod -aG docker,sudo deploy
# скопировать SSH-ключ:
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
# отключить root по SSH (опционально)
```

## 2. Клонирование

```bash
ssh deploy@<ip>
git clone git@github.com:<user>/university_app.git
cd university_app
```

## 3. Конфиг и секреты

`.env` — несекретные параметры:

```ini
POSTGRES_DB=unec
POSTGRES_USER=unec
APP_DOMAIN=kabinet.example.com
ACME_EMAIL=you@example.com
CORS_ORIGINS=https://kabinet.example.com
```

Секреты — каждый файл строго **одно значение, без переноса строки**:

```bash
mkdir -p secrets

# JWT secret
openssl rand -base64 48 | tr -d '\n' > secrets/secret_key

# KEK (Fernet ключ; для ротации потом сюда добавится csv "<new>,<old>")
docker run --rm python:3.13-slim python -c \
  "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode(),end='')" \
  > secrets/fernet_keys

# Postgres password (читается и Postgres'ом, и API через DATABASE_URL)
openssl rand -base64 32 | tr -d '\n' > secrets/postgres_password

# Полный URL для API
PG_PW=$(cat secrets/postgres_password)
printf "postgresql+asyncpg://unec:%s@postgres:5432/unec" "$PG_PW" > secrets/database_url

chmod 600 secrets/*
```

## 4. Первый запуск

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Caddy сам выпустит Let's Encrypt сертификат за ~30 секунд.

Применить миграции:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic upgrade head
```

Проверить:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50 caddy api
curl -I https://kabinet.example.com/health
```

## 5. Smoke-тест

1. Открыть https://kabinet.example.com — должна загрузиться SPA с зелёным замком.
2. Зарегистрироваться, залогиниться, добавить UNEC-креды.
3. Дождаться синка расписания/оценок.
4. С телефона: «Установить приложение» (Android Chrome) или Share → Add to Home Screen (iOS Safari).

## 6. Обновления

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic upgrade head
```

## 7. Бэкапы Postgres

В репе лежит `scripts/backup_postgres.sh` — делает `pg_dump | gzip` → `~/backups/unec-YYYY-MM-DD.sql.gz` и ротация (по умолчанию хранит 30 дней).

Установка раз и навсегда:

```bash
mkdir -p ~/backups
# Запустить вручную для проверки
~/kabinet-parser/scripts/backup_postgres.sh

# Ежедневный cron в 03:00 (по таймзоне сервера = UTC; сервер сам в Asia/Baku
# не настроен на уровне OS, только Docker — так что 03:00 UTC = 07:00 Баку,
# выбираем удобное локальное время)
(crontab -l 2>/dev/null; echo "0 3 * * * /home/deploy/kabinet-parser/scripts/backup_postgres.sh >>/home/deploy/backups/cron.log 2>&1") | crontab -
crontab -l   # проверь что строка добавилась
```

Восстановление из бэкапа:

```bash
gunzip -c ~/backups/unec-2026-05-07.sql.gz | \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  psql -U unec -d unec
```

### Offsite-копия (опционально)

Локальные бэкапы защищают от data corruption и случайного DROP, но не от потери сервера. Чтобы класть копию вне сервера, прицепи Hetzner Storage Box (€3.50/мес, 1ТБ) или S3-совместимое хранилище — добавь rclone в конец `backup_postgres.sh`:

```bash
rclone sync ~/backups storagebox:kabinet-backups/
```

## 8. Ротация KEK (раз в N месяцев)

См. `secrets/README.md` — короткая последовательность из 4 шагов.
