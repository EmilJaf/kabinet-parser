#!/usr/bin/env bash
# Daily Postgres backup for the kabinet-parser stack.
#
# Designed to run from cron on the host:
#   0 3 * * * /home/deploy/kabinet-parser/scripts/backup_postgres.sh >>/home/deploy/backups/cron.log 2>&1
#
# Behaviour:
#   - pg_dump from the running postgres container into ~/backups/unec-YYYY-MM-DD.sql.gz
#   - 30-day rotation: anything older is deleted
#   - Exits non-zero on dump failure so cron emails / alerting can fire
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
TS="$(date +%F)"
OUT="$BACKUP_DIR/unec-$TS.sql.gz"

cd "$PROJECT_DIR"

echo "[$(date -Iseconds)] dumping → $OUT"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
    pg_dump -U "${POSTGRES_USER:-unec}" -d "${POSTGRES_DB:-unec}" \
    | gzip > "$OUT"

# Sanity: a successful dump is at least a few KB even with no rows.
if [[ ! -s "$OUT" ]]; then
    echo "[$(date -Iseconds)] ERROR: dump file is empty, removing"
    rm -f "$OUT"
    exit 1
fi

SIZE="$(du -h "$OUT" | cut -f1)"
echo "[$(date -Iseconds)] OK ($SIZE)"

# Rotate
PURGED="$(find "$BACKUP_DIR" -name 'unec-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -print -delete | wc -l)"
if (( PURGED > 0 )); then
    echo "[$(date -Iseconds)] purged $PURGED file(s) older than ${RETENTION_DAYS}d"
fi
