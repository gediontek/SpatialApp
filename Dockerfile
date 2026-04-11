FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for spatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libspatialindex-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p data labels cache

# Environment defaults
ENV PORT=5000
ENV DATABASE_PATH=/app/data/spatial.db
ENV LOG_FORMAT=json
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

CMD ["gunicorn", "app:app", "-c", "gunicorn.conf.py"]
