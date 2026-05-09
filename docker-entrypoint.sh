#!/bin/sh
# Entrypoint for the api container.
#
# In prod (RUN_MIGRATIONS_ON_START=true) we apply alembic migrations before
# launching uvicorn. Worker and dev never set this — schema changes there
# stay manual via `docker compose exec api alembic upgrade head`.
#
# Note: alembic uses an advisory PG lock, so multiple replicas calling
# upgrade head concurrently is safe — only one actually runs.
set -e

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    echo "[entrypoint] applying alembic migrations…"
    alembic upgrade head
    echo "[entrypoint] migrations done"
fi

exec "$@"
