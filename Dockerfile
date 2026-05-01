# v2.1 Plan 13 M4.1: multi-stage build for smaller runtime image.
# Stage 1 (builder) installs dev / build deps; stage 2 (runtime) ships
# only the resolved Python packages and the app code.

# ---------- Stage 1: builder -------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Build deps for the Python wheels (rasterio / shapely / geopandas link to gdal)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libgdal-dev libspatialindex-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into an isolated prefix so we can copy the whole tree to the
# runtime stage without bringing along build deps.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt gunicorn

# ---------- Stage 2: runtime -------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime needs the GDAL + spatialindex shared libs (no -dev versions).
# curl is kept only for the docker HEALTHCHECK below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgdal32 libspatialindex6 curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app \
 && useradd -r -g app -d /app -s /sbin/nologin app

# Pull installed python packages from the builder
COPY --from=builder /install /usr/local

# Application code
COPY --chown=app:app . .

# Data + cache + label dirs (must be writable by the app user)
RUN mkdir -p data labels cache logs && chown -R app:app data labels cache logs

ENV PORT=5000 \
    DATABASE_PATH=/app/data/spatial.db \
    LOG_FORMAT=json \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

CMD ["gunicorn", "app:app", "-c", "gunicorn.conf.py"]
