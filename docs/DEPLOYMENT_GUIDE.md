# SpatialApp Deployment Guide

## Prerequisites

- **Python 3.11+**
- **System libraries** (for spatial operations):
  - GDAL (`libgdal-dev`)
  - Spatialindex (`libspatialindex-dev`)
  - C/C++ compiler (`gcc`, `g++`)
- **Optional**: Docker & Docker Compose for containerized deployment

---

## Quick Start (Development)

```bash
# Clone the repository
git clone <repo-url>
cd SpatialApp

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << 'EOF'
ANTHROPIC_KEY=<configure-in-env>
# Optional:
# CHAT_API_TOKEN=configure-shared-token
# CLAUDE_MODEL=claude-sonnet-4-20250514
# DATABASE_PATH=data/spatialapp.db
# PORT=5000
EOF

# Run the application
python3 app.py
```

The app starts on `http://localhost:5000`.

---

## Docker Deployment

### Using Docker Compose (recommended)

```bash
# Create .env with your API key
echo "ANTHROPIC_KEY=<configure-in-env>" > .env

# Build and start
docker-compose up -d

# View logs
docker-compose logs -f web

# Stop
docker-compose down
```

The `docker-compose.yml` maps port 5000 and persists data/cache in Docker volumes.

### Using Docker directly

```bash
# Build
docker build -t spatialapp .

# Run
docker run -d \
  --name spatialapp \
  -p 5000:5000 \
  -e ANTHROPIC_KEY=<configure-in-env> \
  -v spatialapp-data:/app/data \
  spatialapp
```

### Dockerfile details

The image is based on `python:3.11-slim` with:
- System deps: `gcc`, `g++`, `libgdal-dev`, `libspatialindex-dev`, `curl`
- Gunicorn installed for production serving
- Health check: `curl -f http://localhost:5000/api/health`
- Data directories created: `data/`, `labels/`, `cache/`

---

## Gunicorn Production Setup

For production without Docker, use Gunicorn directly:

```bash
source venv/bin/activate
pip install gunicorn

# Run with the included config
gunicorn app:app -c gunicorn.conf.py
```

### Gunicorn Configuration (`gunicorn.conf.py`)

| Setting | Value | Notes |
|---|---|---|
| `bind` | `0.0.0.0:$PORT` (default 5000) | Set `PORT` env var |
| `workers` | `cpu_count * 2 + 1` | Override with `WEB_CONCURRENCY` |
| `worker_class` | `gthread` | Threaded workers for SQLite compat |
| `threads` | `4` | Per-worker threads |
| `timeout` | `300` | Long timeout for LLM tool chains |
| `preload_app` | `False` | Required for thread-local SQLite |

### Running behind a reverse proxy (nginx)

```nginx
upstream spatialapp {
    server 127.0.0.1:5000;
}

server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://spatialapp;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE requires no buffering
    location /api/chat {
        proxy_pass http://spatialapp;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }

    # WebSocket upgrade
    location /socket.io/ {
        proxy_pass http://spatialapp;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## Environment Variables Reference

### Required

| Variable | Description | Example |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | (required) |

### Optional - LLM

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `gemini`, `openai` |
| `LLM_MODEL` | (provider default) | Override model name |
| `CLAUDE_MODEL` | (empty) | Legacy alias for `LLM_MODEL` (anthropic only) |
| `GEMINI_API_KEY` | (empty) | Google Gemini API key |
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `OPENAI_BASE_URL` | (empty) | Custom OpenAI-compatible endpoint |
| `MAX_TOOL_CALLS` | `10` | Max tool calls per message |
| `MAX_TOKENS_PER_SESSION` | `100000` | LLM cost budget per session |

### Optional - Server

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5000` | HTTP port |
| `SECRET_KEY` | `dev-secret-...` | Flask secret key (change in production!) |
| `FLASK_DEBUG` | `false` | Debug mode |
| `CHAT_API_TOKEN` | (empty) | Shared bearer token for API auth |
| `WEB_CONCURRENCY` | (auto) | Gunicorn worker count |
| `LOG_LEVEL` | `info` | Logging level |
| `LOG_FORMAT` | (text) | Set to `json` for structured logs |

### Optional - Storage

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `data/spatialapp.db` | SQLite database file path |
| `DATABASE_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `DATABASE_URL` | (empty) | PostgreSQL connection string |
| `UPLOAD_FOLDER` | `static/uploads` | File upload directory |
| `LABELS_FOLDER` | `labels` | Annotation labels directory |
| `LOG_FOLDER` | `logs` | Log files directory |

### Optional - Limits

| Variable | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE` | `52428800` (50MB) | Max file upload size |
| `MAX_FEATURES_PER_LAYER` | `5000` | Max features per layer |
| `MAX_LAYERS_IN_MEMORY` | `100` | Max layers in memory (LRU eviction) |
| `MAX_ANNOTATIONS_STARTUP` | `10000` | Max annotations loaded at startup |
| `SESSION_TTL_SECONDS` | `3600` | Chat session timeout |
| `OSM_REQUEST_TIMEOUT` | `30` | Overpass API timeout (seconds) |

---

## Health Check & Monitoring

### Health endpoint

```bash
# Basic (no auth)
curl http://localhost:5000/api/health
# {"status": "ok", "timestamp": "..."}

# Detailed (with auth)
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/health
# {"status": "ok", "database": "ok", "layers_in_memory": 5, ...}
```

### Prometheus metrics

```bash
curl http://localhost:5000/metrics
```

Exported metrics include:
- `http_requests_total` - Request count by method/endpoint/status
- `http_request_duration_seconds` - Request latency histogram
- `tool_calls_total` - Tool call count by tool name
- `active_sessions` - Current active chat sessions
- `layers_in_memory` - Current layer count

### Docker health check

The Dockerfile includes a built-in health check:
```
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1
```

---

## Running Tests

```bash
source venv/bin/activate

# Run all tests (excluding e2e)
python3 -m pytest tests/ -v --tb=short -k "not e2e"

# Run e2e tests (requires Playwright)
python3 -m playwright install chromium
python3 -m pytest tests/test_e2e.py -v

# Run with coverage
python3 -m pytest tests/ --cov=nl_gis --cov=blueprints --cov-report=term-missing
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Config warning: SECRET_KEY must be set" | Default secret key in non-debug mode | Set `SECRET_KEY` env var |
| Chat returns rule-based responses only | Missing or empty `ANTHROPIC_API_KEY` | Set API key in `.env` |
| `ImportError: libgdal` | Missing GDAL system library | Install `libgdal-dev` (apt) or `gdal` (brew) |
| Spatial operations fail with projection errors | Missing proj data | Install `proj-data` or set `PROJ_LIB` |
| "Database not available" | DB file path not writable | Check `DATABASE_PATH` permissions |
| SSE streaming timeout | Proxy buffering enabled | Disable proxy buffering for `/api/chat` |
| WebSocket connection refused | Flask-SocketIO not installed | `pip install flask-socketio` |
