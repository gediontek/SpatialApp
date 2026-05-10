# Pre-deploy dry-run — 2026-05-09

**Tested commit:** `64a9f02`
**Tested by:** autonomous /auto-solve cycle (Cycle 16)
**Goal:** Boot the app exactly the way prod will (gunicorn + realistic env, no FLASK_DEBUG, no LLM key) and verify every observable contract before deploy.

## What was tested

**Server cmd (matches `Procfile` and Dockerfile `CMD`):**
```bash
PORT=5099 \
SECRET_KEY="$(openssl rand -hex 32)" \
GEMINI_API_KEY="" \
FLASK_DEBUG=false \
LOG_LEVEL=info \
DATABASE_PATH=/tmp/spatial-predeploy.db \
.venv/bin/gunicorn app:app -c gunicorn.conf.py
```

**Worker config** (from `gunicorn.conf.py`): `gthread`, 4 threads/worker, `cpu_count()*2+1 = 21` workers locally, `preload_app=False` (correct for thread-local SQLite), 300s timeout, 30s graceful, JSON access+error log to stdout.

## Probes

| Probe | Expected | Got | Verdict |
|---|---|---|---|
| Gunicorn boots | 0 workers fail; control socket up | 21 workers booted in 1.5s, control socket at `~/.gunicorn/gunicorn.ctl` | ✅ |
| `GET /api/health` | 200 with full subsystem dict | 200 — `database: ok (3 annotations)`, `disk: ok (171GB free)`, `layers: 0/100`, `sessions: 0`, `llm: not_configured`, `ready: false` | ✅ |
| `GET /api/health/ready` | 503 when `LLM_PROVIDER` key absent | 503 — `{ready: false, checks: {database: true, llm: false}}` | ✅ |
| `GET /metrics` | Prometheus text format with HTTP counters | 200 — `http_requests_total{method,status}`, `active_layers`, `active_sessions` | ✅ |
| `GET /.well-known/security.txt` | RFC 9116 fields | 200 — Contact + Expires + Preferred-Languages + Canonical | ✅ |
| Response headers on `/` | CSP w/ nonce, X-CTO, X-FO, Referrer-Policy | All present; CSP includes per-request nonce + correct CDN allowlist (cdnjs, cdn.jsdelivr.net, code.jquery.com, unpkg.com); img-src allows raster basemap origins | ✅ |
| DB init from empty file | Schema created lazily on first connect | Worked — first `/api/health` triggered `database: ok` | ✅ |

## Findings

| ID | Severity | Finding | Where | Fix path |
|---|---|---|---|---|
| F1 | Medium | `SECURITY_CONTACT` is the placeholder `security@example.com` | Default in `config.py`; surfaced in `/.well-known/security.txt` response | Set `SECURITY_CONTACT=security@<your-domain>` in deploy env. One env var; no code change. |
| F2 | Low | No `Strict-Transport-Security` (HSTS) header | App response | Only matters under HTTPS termination; add either at the TLS terminator (recommended — avoids HSTS-on-HTTP foot-gun) OR via `talisman` / a custom `after_request` once HTTPS is committed. |
| F3 | Low | `WEB_CONCURRENCY` not pinned in deploy env | `gunicorn.conf.py:8` falls back to `cpu_count()*2+1`; locally produced 21 workers | Set `WEB_CONCURRENCY` in `.env` / k8s manifest / fly.toml etc. based on memory budget (each worker holds an in-memory `layer_store` cap of 100 + DB connections). Suggest start with 4. |
| F4 | Low | `gthread` worker class falls back from WebSocket to long-polling | `gunicorn.conf.py:9` (intentional — eventlet/gevent fight with thread-local SQLite) | Document that WebSocket transport degrades to long-polling under gunicorn. Already correct — Socket.IO clients handle this transparently. |
| F5 | Low | No explicit migration step before workers boot | `Dockerfile:57` jumps straight to gunicorn | Add a `RUN python -c "from services.database import init; init()"` to Dockerfile before `CMD`, OR run a one-off `flask db init` job in the k8s manifest. Avoids 21-worker TOCTOU on first-connect schema creation. SQLite `CREATE TABLE IF NOT EXISTS` mitigates, so this is hardening, not a fix. |
| F6 | Info | Docker build unverified locally | No `docker` CLI on test host | CI workflow `.github/workflows/ci.yml:74` runs `docker build` + curl health-check on every PR. Coverage is in CI, not on this host. |

## Verdict

**Deploy-ready modulo F1.** Every other finding is "tighten before scaling" — none of them block a single-instance deploy with a real `SECURITY_CONTACT` in the env file. The gunicorn boot itself is clean: no warnings, no missing config, no dependency errors, all health/metrics endpoints behave correctly, the CSP / security headers / security.txt all serve as designed.

## Pre-deploy checklist (for the operator)

1. ☐ `SECRET_KEY` — generated value (e.g. `openssl rand -hex 32`); MUST NOT use the dev default (`Config.validate` raises in non-DEBUG mode if it's still default — verified).
2. ☐ `SECURITY_CONTACT` — real inbox you actually monitor.
3. ☐ `WEB_CONCURRENCY` — pinned (suggest 4 to start; tune via memory budget).
4. ☐ `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) — without one, `/api/health/ready` returns 503 (load balancer correctly drains).
5. ☐ `CHAT_API_TOKEN` — required for production (without it, `/api/chat` is open).
6. ☐ `DATABASE_PATH` — persistent volume (Docker `app-data` volume per `docker-compose.yml`).
7. ☐ HTTPS terminator in front (nginx / cloud LB) and configure HSTS there.
8. ☐ First request after deploy: `curl https://<host>/api/health/ready` MUST return 200; if 503, investigate before routing traffic.
