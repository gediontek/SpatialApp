# Plan 13: Production Hardening

**Scope**: Load testing (50 concurrent users), OWASP top-10 security audit, cost optimization (caching, model tiering, token budgeting), deployment automation, monitoring dashboard. Verify with a 50-user load test.

**Estimated effort**: 2 days | ~300-400 lines of code + configuration

**Depends on**: Core quality from prior plans (app is stable, 438 tests passing)

**Current state**:
- **Prometheus metrics**: `services/metrics.py` — `MetricsCollector` with counters, gauges, histograms. Singleton at `metrics`. Exposed via `/api/metrics` (Prometheus text format). Tracks `auth_requests_total`, tool call counts, latencies.
- **Docker**: `Dockerfile` — single-stage `python:3.11-slim`, gunicorn with `gunicorn.conf.py` (gthread workers, 300s timeout). Health check on `/api/health`.
- **CI/CD**: `.github/workflows/ci.yml` — test + lint + docker build on main. No deploy step.
- **Rate limiter**: `services/rate_limiter.py` — token bucket for nominatim (1s), overpass (2s), valhalla (1s). Applied to external APIs, NOT to user requests.
- **Auth**: `blueprints/auth.py` — `require_api_token` decorator, per-user tokens via DB, shared token fallback. No CSRF protection.
- **Gunicorn**: `gunicorn.conf.py` — gthread workers, 4 threads, 300s timeout, preload disabled.
- **No response caching** for LLM results. No model tiering. No token budgeting. No user-facing rate limiting. No deployment automation beyond Docker.

---

## Milestone 1: Load Testing Infrastructure

**Goal**: Simulate 50 concurrent users. Identify bottleneck. Establish performance baselines.

### Epic 1.1: Load Test Script

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.1.1 | Create `tests/load/locustfile.py` using Locust framework. Define `SpatialAppUser` class with tasks: (1) `health_check` — GET `/api/health` (weight 1), (2) `geocode` — POST `/api/chat` with "Where is Central Park?" (weight 3), (3) `fetch_osm` — POST `/api/chat` with "Show parks in Manhattan" (weight 2), (4) `complex_query` — POST `/api/chat` with "Buffer the parks by 500m and find nearby restaurants" (weight 1). Set `wait_time = between(1, 3)`. | Locust script runs with `locust -f tests/load/locustfile.py --headless -u 50 -r 10 --run-time 2m`. | M |
| 1.1.2 | Add mock mode for load testing: env var `LOAD_TEST_MODE=1` makes `nl_gis/chat.py` skip actual Claude API calls and return canned responses. Prevents $100+ API bills during load tests. Insert check in `ChatSession._call_llm()` (or equivalent). | Load test runs without API key. Canned responses exercise full SSE pipeline. | M |
| 1.1.3 | Add `locust` to dev dependencies in `requirements.txt` or separate `requirements-dev.txt`. | `pip install locust` available in dev. | XS |
| 1.1.4 | Create `tests/load/run_load_test.sh`: starts app in background with `LOAD_TEST_MODE=1`, runs Locust for 2 minutes with 50 users, saves HTML report to `tests/load/report.html`, stops app. | One-command load test: `bash tests/load/run_load_test.sh`. | S |

### Epic 1.2: Performance Metrics Collection

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.2.1 | Add request-level metrics to `services/metrics.py`: `http_request_duration_seconds` histogram (labels: method, endpoint, status), `http_requests_in_flight` gauge, `active_sessions` gauge. Instrument in Flask `before_request`/`after_request` hooks in `app.py` `create_app()`. | `/api/metrics` shows request latency percentiles and in-flight count. | M |
| 1.2.2 | Add memory usage gauge: `process_memory_bytes`. Update periodically via `threading.Timer` (every 30s) using `psutil.Process().memory_info().rss` or `resource.getrusage()`. | Memory tracked in metrics. Visible spike during 50-user test indicates leak. | S |
| 1.2.3 | Add LLM-specific metrics: `llm_requests_total` (counter, labels: model, tool), `llm_token_usage` (counter, labels: direction=input|output), `llm_request_duration_seconds` (histogram). Instrument in `nl_gis/chat.py` where Claude API responses are processed. | Token usage and LLM latency visible in `/api/metrics`. | M |

### Epic 1.3: Bottleneck Analysis

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 1.3.1 | Run 50-user load test. Record: p50/p95/p99 response times, error rate, max concurrent connections, memory high-water mark. Document findings in test output. | Numeric baselines established. Bottleneck identified (expected: LLM latency or gunicorn worker exhaustion). | M |
| 1.3.2 | If gunicorn worker exhaustion identified: tune `gunicorn.conf.py` — increase `workers` (line 8) and `threads` (line 10). If SQLite contention: add connection pooling or WAL checkpoint tuning. If memory: identify leak via object counts. | Performance improves after tuning. p95 < 30s for simple queries under load. | S |

---

## Milestone 2: Security Audit (OWASP Top-10)

**Goal**: Systematic check of OWASP top-10. Fix every finding.

### Epic 2.1: Injection & XSS

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.1.1 | **Overpass QL injection**: Audit `nl_gis/handlers/navigation.py` where `location` and `osm_key`/`osm_value` are interpolated into Overpass queries. Ensure all values are sanitized: strip special characters (`[`, `]`, `(`, `)`, `;`, `"`). Add allowlist for `osm_key` values. | No Overpass injection possible via `fetch_osm` tool params. Test with payload `"; [out:csv]; //"`. | M |
| 2.1.2 | **SQL injection via attribute_join**: Audit `handle_attribute_join()` in `nl_gis/handlers/analysis.py`. Verify attribute names are validated against actual feature properties (not interpolated into SQL). Currently uses in-memory dict matching, not SQL — verify this is the case. | Confirmed no SQL path. Document in code comment. | S |
| 2.1.3 | **XSS via layer names**: Audit `LayerManager.refreshUI()` in `static/js/layers.js`. Current: uses `escapeHtml()` (line 317) and `escapeAttr()` (line 323). Verify these are applied consistently to ALL user-controlled strings rendered in HTML. Check popup content in `onEachFeature` (line 58). | All user-controlled strings escaped. Test with `<script>alert(1)</script>` as layer name. | S |
| 2.1.4 | **XSS in chat messages**: Audit `appendMessage()` in `static/js/chat.js`. Verify assistant messages are HTML-escaped before insertion into DOM. Check for `innerHTML` usage with unescaped data. | No raw HTML injection possible via chat responses. | S |

### Epic 2.2: Authentication & Session

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.2.1 | **CSRF on state-mutating endpoints**: Add CSRF token generation to session. Include `X-CSRF-Token` header in all POST/PUT/DELETE requests from frontend. Validate in `before_request` hook for non-GET requests. Exempt `/api/chat` (SSE) and `/api/register`. | State-mutating requests without valid CSRF token return 403. | M |
| 2.2.2 | **Auth bypass on dashboard**: Verify `/dashboard` route in `blueprints/dashboard.py` requires authentication. If open, add `@require_api_token` decorator. | Dashboard inaccessible without valid token (when token auth is configured). | S |
| 2.2.3 | **Session fixation**: Verify `sessionId` in `static/js/chat.js` (line 8) uses `crypto.randomUUID()` and is not predictable. Ensure server-side session IDs in `state.chat_sessions` cannot be enumerated. | Session IDs are cryptographically random. No session enumeration via API. | S |

### Epic 2.3: Security Headers

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.3.1 | Add security headers in `create_app()` `after_request` hook: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 0` (modern approach), `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy: default-src 'self'; script-src 'self' cdn.jsdelivr.net unpkg.com; style-src 'self' 'unsafe-inline' unpkg.com; img-src 'self' *.tile.openstreetmap.org data:`. | All security headers present in responses. CSP does not break map tiles or CDN scripts. | M |
| 2.3.2 | Add `Strict-Transport-Security` header when behind HTTPS (check `X-Forwarded-Proto`). | HSTS set in production. Not set in dev. | XS |

### Epic 2.4: Security Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 2.4.1 | Add `tests/test_security.py`: test Overpass injection, XSS in layer names, CSRF enforcement, auth bypass, security headers present. | 8+ security tests passing. | M |

---

## Milestone 3: Cost Optimization

**Goal**: Reduce LLM API costs via caching, model tiering, and token budgeting.

### Epic 3.1: Response Caching

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.1.1 | Create `services/llm_cache.py`. Key: hash of (system_prompt_hash, last_N_messages, tool_results). Value: full LLM response. TTL: 5 minutes (configurable via `LLM_CACHE_TTL` env var). Max entries: 500. Thread-safe with `threading.Lock`. Use pattern from `_spatial_cache` in `nl_gis/handlers/analysis.py` (line 41). | Cache hit returns identical response. Cache miss falls through to API. | M |
| 3.1.2 | Integrate cache in `nl_gis/chat.py` before Claude API call. Check cache first. On cache hit, emit SSE events from cached response (skip API). On cache miss, call API and store result. Add `llm_cache_hits_total` and `llm_cache_misses_total` counters to metrics. | Same query within 5 minutes returns cached result. Metrics show hit/miss ratio. | M |
| 3.1.3 | Add cache bypass: if user message contains "recalculate" or "fresh", skip cache. | Users can force fresh results. | XS |

### Epic 3.2: Model Tiering

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.2.1 | Add `services/model_router.py`. Classify query complexity: **simple** (geocode, show/hide layer, style changes — single-tool, no spatial reasoning) -> use `claude-3-5-haiku-latest`. **Complex** (multi-tool chains, spatial analysis, routing) -> use current model (`CLAUDE_MODEL` from `config.py`). Classification heuristic: if message matches patterns like "where is", "show me", "hide", "color the" -> simple. Default -> complex. | `ModelRouter.select_model("Where is Paris?")` returns haiku model. `ModelRouter.select_model("Buffer parks by 500m and find restaurants nearby")` returns full model. | M |
| 3.2.2 | Integrate `ModelRouter` in `nl_gis/chat.py`. Use selected model in API call. Add `MODEL_TIERING_ENABLED` env var (default False). Log model used per request. Add `llm_requests_total{model=...}` counter. | Haiku handles simple queries at ~10x lower cost. Complex queries still use full model. | S |
| 3.2.3 | Add `SIMPLE_MODEL` env var to `config.py` (default `claude-3-5-haiku-latest`). | Configurable without code changes. | XS |

### Epic 3.3: Token Budgeting

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 3.3.1 | Track per-session token usage in `nl_gis/chat.py`. Accumulate `input_tokens` and `output_tokens` from Claude API responses. Store on the session object. Expose via `/api/usage` endpoint (existing in `blueprints/chat.py`). | `/api/usage?session_id=X` returns `{"input_tokens": N, "output_tokens": M, "estimated_cost_usd": ...}`. | M |
| 3.3.2 | Add session cost warning: when session exceeds `SESSION_COST_WARN_USD` (env var, default $0.50), include a system note in the chat: "This session has used approximately $X.XX in API costs." Don't block, just inform. | Warning appears after threshold. Does not interrupt workflow. | S |
| 3.3.3 | Add per-user daily budget: `USER_DAILY_BUDGET_USD` (env var, default $5.00). Track in `services/database.py` via `daily_usage` table. When exceeded, return 429 with message. | User exceeding daily budget gets informative error. Resets at midnight UTC. | M |

---

## Milestone 4: Deployment Automation

**Goal**: One-command deploy to Railway/Fly.io. Docker image < 500MB. Auto-restart.

### Epic 4.1: Docker Optimization

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.1.1 | Convert `Dockerfile` to multi-stage build. Stage 1 (`builder`): install build deps (gcc, g++, libgdal-dev), pip install requirements. Stage 2 (`runtime`): copy only installed packages and app code. Use `python:3.11-slim` for both. Remove build tools from final image. | `docker build` produces image. `docker images spatialapp` shows < 500MB (currently ~800MB estimated). | M |
| 4.1.2 | Add `.dockerignore`: exclude `__pycache__`, `.git`, `tests/`, `docs/`, `*.md`, `venv/`, `.env`, `node_modules/`, `.pytest_cache/`. | Build context is smaller. No secrets in image. | XS |
| 4.1.3 | Pin all dependency versions in `requirements.txt` (use `pip freeze`). Ensure reproducible builds. | Identical builds from same commit. | S |

### Epic 4.2: Platform Deployment Config

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.2.1 | Create `fly.toml` for Fly.io deployment. Configure: app name, region (iad), vm size (shared-cpu-1x, 512MB), internal port 5000, health check on `/api/health`, auto-stop after 5 min idle, env vars from secrets. | `fly deploy` succeeds from project root. App accessible at `https://spatialapp.fly.dev`. | M |
| 4.2.2 | Create `railway.json` for Railway deployment. Configure: build command, start command (`gunicorn app:app -c gunicorn.conf.py`), health check, env vars. | Railway deployment works from GitHub push. | S |
| 4.2.3 | Create `deploy.sh` script: accepts platform arg (`fly` or `railway`). Sets env vars, runs Docker build, pushes to registry, deploys. Includes rollback command. | `bash deploy.sh fly` deploys to Fly.io. `bash deploy.sh fly --rollback` reverts. | M |
| 4.2.4 | Update `.github/workflows/ci.yml` to add deploy job: on push to `main`, after test+lint+docker pass, deploy to staging (Fly.io). Requires `FLY_API_TOKEN` secret. | CI/CD pipeline deploys automatically on main merge. | M |

### Epic 4.3: Health & Restart

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 4.3.1 | Enhance `/api/health` in `blueprints/auth.py` (line 111): add `uptime_seconds`, `version` (from git hash or `VERSION` file), `ready` boolean (true when all subsystems initialized). Add `/api/health/ready` for Kubernetes readiness probe. | Health check distinguishes liveness (running) from readiness (fully initialized). | S |
| 4.3.2 | Add graceful shutdown handler in `app.py`: on SIGTERM, flush metrics, close DB connections, log shutdown. | `docker stop` waits for in-flight requests (graceful_timeout=30s in gunicorn). | S |

---

## Milestone 5: Monitoring Dashboard

**Goal**: Built-in dashboard showing LLM accuracy, error rates, latency, sessions, cost.

### Epic 5.1: Dashboard Data API

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 5.1.1 | Extend `/api/dashboard` in `blueprints/dashboard.py` to return time-series data: aggregate metrics by minute for last hour, by hour for last 24h. Derive from `MetricsCollector` histogram/counter data. Include: request_count, error_count, p50/p95 latency, active_sessions, llm_cost_usd. | `/api/dashboard?range=1h` returns minute-by-minute metrics. | M |
| 5.1.2 | Add tool accuracy tracking: log each tool call result (success/error) in metrics. Compute tool success rate per tool name. Add `tool_success_total` and `tool_error_total` counters (labels: tool_name). | Dashboard shows per-tool success rates. | S |

### Epic 5.2: Dashboard UI

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 5.2.1 | Create `templates/dashboard.html` (or enhance existing). Use Chart.js (already planned in Plan 11) for: (1) Request latency line chart (p50, p95 over time), (2) Tool usage bar chart (calls per tool), (3) Error rate line chart, (4) Active sessions gauge, (5) Estimated cost counter. Auto-refresh every 30s via `setInterval`. | Dashboard loads at `/dashboard` with 5 charts. Data updates live. | L |
| 5.2.2 | Add auth requirement: dashboard only accessible with valid token. Use `@require_api_token` from `blueprints/auth.py`. | Unauthorized users cannot view metrics. | XS |

---

## Milestone 6: 50-User Load Test Validation

**Goal**: Run full load test. All metrics within budget.

### Epic 6.1: Validation Run

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| 6.1.1 | Deploy to staging (Fly.io or local Docker). Run `tests/load/run_load_test.sh` with 50 users for 5 minutes. Collect: p50 < 5s, p95 < 30s, p99 < 60s, error rate < 5%, memory < 1GB, no OOM kills. | All thresholds met. Locust report saved. | M |
| 6.1.2 | Run security regression: execute `tests/test_security.py` against deployed instance. All security headers present. No injection vectors. CSRF enforced. | All security tests pass against deployed app. | S |
| 6.1.3 | Cost projection: from token usage metrics during load test, extrapolate monthly cost for 50 daily active users, 10 queries each. Document in test output. | Cost estimate documented. Model tiering reduces cost by >50% vs baseline. | S |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Load test hits real Claude API | `LOAD_TEST_MODE=1` env var returns canned responses. Enforced in test script. |
| CSRF breaks existing frontend | Exempt SSE endpoints. Test with existing chat flow before and after. |
| CSP blocks map tiles or CDN | Whitelist known CDN domains. Test all existing functionality after CSP. |
| Model tiering misclassifies complex queries as simple | Default to complex model. Simple classification is conservative (false negatives OK, false positives not). Log misroutes. |
| Multi-stage Docker breaks spatial libs (GDAL) | Test GDAL import in runtime stage. Include `libgdal34` in runtime if needed. |
| Fly.io free tier insufficient for 50-user test | Use dedicated VM ($7/mo) for load test. Scale down after. |
| Token budget tracking adds latency | In-memory accumulation (no DB write per request). Flush to DB every 60s. |

## Output Artifacts

| Artifact | Path |
|----------|------|
| Load test script | `tests/load/locustfile.py` |
| Load test runner | `tests/load/run_load_test.sh` |
| LLM response cache | `services/llm_cache.py` |
| Model router | `services/model_router.py` |
| Security tests | `tests/test_security.py` |
| Optimized Dockerfile | `Dockerfile` (multi-stage) |
| Docker ignore | `.dockerignore` |
| Fly.io config | `fly.toml` |
| Railway config | `railway.json` |
| Deploy script | `deploy.sh` |
| Updated CI pipeline | `.github/workflows/ci.yml` |
| Updated gunicorn config | `gunicorn.conf.py` |
| Updated metrics | `services/metrics.py` |
| Dashboard template | `templates/dashboard.html` |
| Updated health check | `blueprints/auth.py` |
| Updated app factory | `app.py` (security headers, shutdown) |
