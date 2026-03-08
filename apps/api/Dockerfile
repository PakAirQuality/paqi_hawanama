# API Service Dockerfile for Cloud Run
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for PostgreSQL, GDAL (for rio-tiler), and other requirements
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL environment variables for rasterio/rio-tiler
ENV GDAL_CONFIG=/usr/bin/gdal-config

# Copy requirements first to leverage layer caching
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API application code
COPY apps/api/ /app/

# Copy worker into the API package namespace expected by your imports
COPY apps/worker/tasks /app/app/tasks
COPY apps/worker/services /app/app/worker_services
COPY apps/worker/config /app/app/worker_config
COPY apps/worker/manifest_utils.py /app/app/manifest_utils.py

# Make sure these are Python packages
RUN touch /app/app/tasks/__init__.py \
         /app/app/worker_services/__init__.py \
         /app/app/worker_config/__init__.py

# Worker modules now have dual-path imports for compatibility

# Copy alembic configuration (migrations handled via SQLAlchemy)
COPY apps/api/alembic.ini /app/alembic.ini

# Copy Pakistan boundary data (geoBoundaries) for tile clipping and district interactions
COPY apps/api/data/pakistan_country.geojson /app/data/pakistan_country.geojson
COPY apps/api/data/pakistan_districts.geojson /app/data/pakistan_districts.geojson
COPY apps/api/data/pakistan_adm2_dissolved.geojson /app/data/pakistan_adm2_dissolved.geojson

# Create artifacts directory structure
RUN mkdir -p /app/artifacts/station_manifests /app/artifacts/city_manifests /app/artifacts/ingest_runs

# Copy and setup start script
COPY apps/api/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Create non-root user for security
RUN groupadd -r hawanama && useradd -r -g hawanama hawanama
RUN chown -R hawanama:hawanama /app
USER hawanama

# Expose port (Cloud Run will set PORT env var to 8080)
EXPOSE 8080

# Health check (optional for Cloud Run)
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8080}/api/v1/health || exit 1

# Start command - use start.sh script
CMD ["/app/start.sh"]