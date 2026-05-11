# NP Create backend image — built with locked deps from requirements.txt.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# OS deps that psycopg's binary wheel doesn't ship (curl for healthcheck).
RUN apt-get update \
 && apt-get install --yes --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so layer caches are stable when only source changes.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Project source.
COPY pyproject.toml ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tools_manifest.json ./
RUN pip install --no-deps -e .

# Non-root runtime user.
RUN useradd --create-home --shell /bin/bash npcreate \
 && chown -R npcreate:npcreate /app
USER npcreate

EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8088/healthz || exit 1

CMD ["python", "-m", "npcreate_backend"]
