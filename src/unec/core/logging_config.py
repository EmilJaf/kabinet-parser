"""Application logging — file + stdout, with rotation.

Both the API and the ARQ worker call `setup_logging(service)` at startup.
- Stdout: keeps `docker compose logs <svc>` working as before.
- File `/app/logs/<service>.log`: persisted via the docker volume mount
  to `./logs/` on the host, so logs survive container recreation. The
  admin panel reads these files via `/v1/admin/logs`.

Rotation: 10 MB × 5 backups (50 MB cap per service). Older lines are
discarded automatically — we don't ship them to long-term storage.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "/app/logs"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(service: str) -> None:
    """Wire the root logger to a file + stdout. Idempotent.

    If the log directory can't be created (e.g. CI/dev runs API outside
    the docker container where /app doesn't exist), the file handler is
    silently skipped — stdout still works, the service still starts.
    """
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Drop whatever uvicorn/arq pre-installed so we don't duplicate every
    # message twice (or three times) into stdout.
    root.handlers.clear()
    root.addHandler(stream_handler)

    # File handler is best-effort — keeps the API alive even if /app/logs
    # isn't writable (CI runs uvicorn directly on the runner; admin /logs
    # endpoint just reports the file as unavailable in that case).
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(LOG_DIR, f"{service}.log"),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("file logging disabled (%s not writable): %s", LOG_DIR, exc)

    # Uvicorn's named loggers default to propagate=True since 0.30; make
    # sure we don't accidentally toggle that off elsewhere.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "arq", "arq.worker"):
        logging.getLogger(name).propagate = True
