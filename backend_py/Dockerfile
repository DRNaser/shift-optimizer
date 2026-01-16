# =============================================================================
# SOLVEREIGN V4.5 - Python Backend Dockerfile
# =============================================================================
# Runtime: FastAPI kernel (api.main:app) + Domain Packs
# NOTE: Legacy src/ removed in V4.5. v3/ retained for solver compatibility.
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
# NOTE: src/ REMOVED in V4.5 (legacy package deleted)

# FastAPI kernel
COPY api/ ./api/

# Core solver logic (will move to packs/roster/engine in V4.6)
COPY v3/ ./v3/

# Business packs (portal, notify, routing, roster)
COPY packs/ ./packs/

# Database schemas
COPY db/ ./db/

# Configuration
COPY pyproject.toml .

# Set Python path
ENV PYTHONPATH=/app

# API module (FastAPI kernel)
ENV API_MODULE=api.main:app

# Create non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run with uvicorn
CMD python -m uvicorn ${API_MODULE} --host 0.0.0.0 --port 8000
