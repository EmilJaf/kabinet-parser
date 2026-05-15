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

# Camoufox ships its own antidetect Firefox build. We use Playwright's
# install-deps to grab the Firefox OS libraries (libgtk, libdbus-glib,
# etc.) without downloading Playwright's stock Firefox, then `camoufox
# fetch` downloads the patched build. Image grows ~500 MB.
RUN python -m playwright install-deps firefox \
    && python -m camoufox fetch \
    && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "unec.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
