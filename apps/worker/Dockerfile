# Worker Service Dockerfile for Render
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for PostgreSQL and other requirements
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN groupadd -r hawanama && useradd -r -g hawanama hawanama
RUN chown -R hawanama:hawanama /app
USER hawanama

# Health check for scheduler (simple port/file check)
HEALTHCHECK --interval=60s --timeout=30s --start-period=10s --retries=3 \
  CMD python -c "import sys; sys.exit(0)" || exit 1

# Default command for APScheduler
CMD ["python", "main_scheduler.py"]