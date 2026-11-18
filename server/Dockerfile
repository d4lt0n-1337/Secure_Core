# ==============================================================
# SecureCore IDS — Backend Docker Image
# Python 3.11 + Flask + SocketIO + ML Models
#
# BUILD CONTEXT: project root (../) so we can copy models/
#   docker build -f server/Dockerfile -t securecore-backend .
# ==============================================================

FROM python:3.11-slim

# System dependencies for scientific packages and networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY server/requirements.txt .
RUN pip install --no-cache-dir setuptools && \
    pip install --no-cache-dir -r requirements.txt

# Copy server application code
COPY server/ .

# Copy ML models from project root
COPY models/ /app/models/

# Create required directories
RUN mkdir -p /app/data /app/logs /app/uploads /app/backups

# Set environment variables for production
ENV FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    HOST=0.0.0.0 \
    ML_MODELS_DIR=/app/models

EXPOSE 5000

# Copy and set entrypoint for DB initialization
COPY server/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -f http://localhost:5000/health || exit 1

# Entrypoint initializes DB schema + seeds, then execs CMD
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Run with gunicorn + gthread for WebSocket support
# Using 1 worker because SocketIO requires sticky sessions
# gthread worker matches the app's async_mode='threading'
CMD ["gunicorn", \
     "--worker-class", "gthread", \
     "--workers", "1", \
     "--threads", "16", \
     "--bind", "0.0.0.0:5000", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
