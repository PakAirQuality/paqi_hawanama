# Standalone APScheduler worker (NOT the production path; production ingestion
# runs on Cloud Run service hawanama-ingest via apps/api/Dockerfile).
# Build from the repository root:
#   docker build -f apps/worker/Dockerfile -t hawanama-worker .
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*
ENV GDAL_CONFIG=/usr/bin/gdal-config

# One dependency set: the API requirements are the canonical ones.
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Canonical ingestion code lives in the API package; the worker only adds shims.
COPY apps/api/ /app/api/
COPY apps/worker/*.py /app/worker/

RUN groupadd -r hawanama && useradd -r -g hawanama hawanama
RUN mkdir -p /app/worker/artifacts && chown -R hawanama:hawanama /app
USER hawanama
WORKDIR /app/worker

HEALTHCHECK --interval=60s --timeout=30s --start-period=10s --retries=3 \
  CMD python -c "import sys; sys.exit(0)" || exit 1

CMD ["python", "main_scheduler.py"]
