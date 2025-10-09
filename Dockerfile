# Root Dockerfile for API Service (Render deployment)
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for PostgreSQL and other requirements
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    libgeos-dev \
    libproj-dev \
    libgdal-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy API requirements and install Python dependencies
COPY apps/api/requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy API application code
COPY apps/api/ .

# Copy and make startup script executable (before switching users)
COPY apps/api/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Create non-root user for security
RUN groupadd -r hawanama && useradd -r -g hawanama hawanama
RUN chown -R hawanama:hawanama /app
USER hawanama

# Expose port (Render will set PORT env var)
EXPOSE 8000

# Health check - use fixed port for health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Start command - use startup script
CMD ["/app/start.sh"]