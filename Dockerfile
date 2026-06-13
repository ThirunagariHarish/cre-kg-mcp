FROM python:3.11-slim AS base

WORKDIR /app

# System deps: gcc for some pip builds, curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create runtime dirs (PVC will mount over shared/state in k8s)
RUN mkdir -p shared/state shared/cache/uw agents logs \
    && chmod -R 755 shared/

# Healthcheck hits the dashboard /api/health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8765/api/health || exit 1

EXPOSE 8765

# Default: start dashboard (run_all_analysts.py is a separate deployment)
CMD ["python", "-m", "uvicorn", "gateway.dashboard:app", \
     "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
