# =============================================================================
# SOLVEREIGN V3.3b - Python Backend Dockerfile
# =============================================================================
# Supports both Legacy API (src.main:app) and Enterprise API (api.main:app)
# Default: Enterprise API (api.main:app)
#
# To run Legacy API instead:
#   docker run -e API_MODULE=src.main:app solvereign-api
# =============================================================================

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# Legacy API (backwards compatibility)
COPY src/ ./src/

# Enterprise API (V3.3b)
COPY api/ ./api/

# Core business logic (used by both APIs)
COPY v3/ ./v3/

# Business packs (portal, notify, routing, roster)
COPY packs/ ./packs/

# Database schemas
COPY db/ ./db/

# Configuration
COPY pyproject.toml .

# Set Python path
ENV PYTHONPATH=/app

# API module selection (default: Enterprise API)
ENV API_MODULE=api.main:app

# Create non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Expose port
EXPOSE 8000

# Health check (Enterprise API uses /health, Legacy uses /api/v1/healthz)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with uvicorn (uses API_MODULE env var)
CMD python -m uvicorn ${API_MODULE} --host 0.0.0.0 --port 8000
