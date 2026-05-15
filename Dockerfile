FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
RUN pip install -e .

# Install patchright's CDP-fingerprint-patched Chromium plus the OS libs
# it needs. patchright ships its own Chromium build that hides the
# DevTools-Protocol runtime CF uses to detect automated browsers — stock
# Playwright Chromium gets stuck in an infinite challenge loop on
# kabinet.unec.edu.az. Image grows ~450 MB.
RUN python -m patchright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "unec.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
