# SpatialApp Architecture

**As of:** 2026-04-17 · post-v2.0 · 7 blueprints · 5 handlers · 9 services · 64 tools
**Navigation:** [Status](STATUS.md) · [Capability Map](CAPABILITY_MAP.md) · [Shipped → `docs/v1/`](../docs/v1/) · [Active → `docs/v2/`](../docs/v2/)

---

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Browser Client                        │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐            │
│  │ Leaflet  │  │ Chat UI  │  │ Layer      │            │
│  │ Map      │  │ (SSE/WS) │  │ Manager    │            │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘            │
│       │              │              │                    │
│  ┌────┴──────────────┴──────────────┴──────┐            │
│  │            static/js/                    │            │
│  │  main.js · chat.js · layers.js          │            │
│  └──────────────────┬──────────────────────┘            │
└─────────────────────┼───────────────────────────────────┘
                      │ REST + SSE + Socket.IO
┌─────────────────────┼───────────────────────────────────┐
│              Flask Application                           │
│                      │                                   │
│  app.py ─── create_app() factory                        │
│       │                                                  │
│  ┌────┴────────────────────────────────────┐            │
│  │           Blueprints                     │            │
│  │  ┌─────────┐  ┌──────────┐  ┌────────┐ │            │
│  │  │ auth    │  │ chat     │  │ layers │ │            │
│  │  └─────────┘  └────┬─────┘  └────────┘ │            │
│  │  ┌─────────┐  ┌────┼─────┐  ┌────────┐ │            │
│  │  │ annot.  │  │ osm│     │  │ dashbd │ │            │
│  │  └─────────┘  └────┼─────┘  └────────┘ │            │
│  │  ┌─────────────────┼─────────────────┐  │            │
│  │  │   websocket.py  │                 │  │            │
│  │  └─────────────────┼─────────────────┘  │            │
│  └────────────────────┼────────────────────┘            │
│                       │                                  │
│  state.py ←── shared mutable state (locks, stores)      │
│                       │                                  │
│  ┌────────────────────┼────────────────────┐            │
│  │        nl_gis Module                     │            │
│  │  chat.py ──── ChatSession                │            │
│  │       │         │                        │            │
│  │       │    tool dispatch loop            │            │
│  │       │         │                        │            │
│  │  tools.py   handlers/                    │            │
│  │  (schemas)  ├── navigation.py            │            │
│  │             ├── analysis.py              │            │
│  │             ├── layers.py                │            │
│  │             ├── annotations.py           │            │
│  │             └── routing.py               │            │
│  │                  │                       │            │
│  │  geo_utils.py ←──┘ spatial operations    │            │
│  └──────────────────────────────────────────┘            │
│                       │                                  │
│  ┌────────────────────┼────────────────────┐            │
│  │        Services Layer                    │            │
│  │  database.py ──── SQLite + WAL           │            │
│  │  db_interface.py ─ DatabaseInterface ABC │            │
│  │  postgres_db.py ── PostGIS stub          │            │
│  │  valhalla_client.py ── routing API       │            │
│  │  cache.py ──────── file cache + limits   │            │
│  │  rate_limiter.py ── token bucket         │            │
│  │  logging_config.py ── JSON formatter     │            │
│  │  code_executor.py ── sandboxed Python    │            │
│  │  metrics.py ─────── Prometheus /metrics  │            │
│  └──────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────┘
              │                │               │
    ┌─────────┴──┐    ┌───────┴────┐   ┌──────┴──────┐
    │ Nominatim  │    │  Overpass  │   │  Valhalla   │
    │ (geocode)  │    │  (OSM)     │   │  (routing)  │
    └────────────┘    └────────────┘   └─────────────┘
              │
    ┌─────────┴──┐
    │ Claude API │
    │ (LLM)      │
    └────────────┘
```

## Data Flow

### Request Lifecycle

```
1. HTTP POST /api/chat
   │ body: {message, session_id, map_context}
   │
2. Blueprint handler extracts params, gets/creates ChatSession
   │
3. ChatSession.process_message(message, map_context)
   │ → Builds system prompt (static + dynamic context)
   │ → Appends user message to history
   │
4. While loop: Claude API call
   │ → If stop_reason="end_turn": yield text response, done
   │ → If stop_reason="tool_use":
   │     for each tool_use block:
   │       dispatch_tool(name, params, layer_store)
   │         → route to handler function
   │         → handler may call external APIs
   │         → handler returns result dict
   │       yield SSE events (tool_start, tool_result, layer_add, etc.)
   │       append tool_result to messages
   │     loop → next Claude API call
   │
5. SSE events stream to frontend:
   │ → tool_start: show "Running geocode..."
   │ → tool_result: update "geocode ✓"
   │ → layer_add: add GeoJSON to Leaflet map
   │ → map_command: pan/zoom/fit
   │ → message: show assistant text response
```

### State Management

```
state.py (module-level, shared across threads)
  ├── geo_coco_annotations: list     ← annotation_lock
  ├── layer_store: OrderedDict       ← layer_lock
  ├── chat_sessions: dict            ← session_lock
  ├── db: Database instance          ← thread-local connections
  └── socketio: SocketIO instance    ← thread-safe by design

Write order (DB-first):
  1. Write to database
  2. Update in-memory state
  3. If DB fails → operation fails (no silent data loss)

Exception: chat-produced layers use in-memory-first
  (DB failure = warning, layer still useful for current session)
```

### Thread Safety Model

```
Per-session lock:
  ChatSession._lock prevents concurrent process_message on same session

Global locks:
  annotation_lock — protects geo_coco_annotations reads/writes
  layer_lock — protects layer_store reads/writes (via _get_layer_snapshot)
  session_lock — protects chat_sessions dict (implicit via blueprint handlers)

Pattern: snapshot reads
  _get_layer_snapshot(layer_store, name) → copies features under lock
  Handlers work on snapshots, never mutate layer_store directly without lock
```

## Key Design Decisions

### Why Flask + SQLite (not Django + PostgreSQL)
- Single-file deployment simplicity
- No external DB server required
- SQLite WAL mode handles moderate concurrency
- PostGIS migration path ready when scaling requires it

### Why Claude tool_use (not text-to-SQL)
- Security: no SQL injection possible
- Accuracy: 86% tool selection accuracy
- Extensibility: adding a tool = schema + handler
- Safety: each tool has input validation

### Why SSE + WebSocket (not just one)
- SSE: simple, works everywhere, sufficient for chat streaming
- WebSocket: better reconnection, bidirectional (abort, progress)
- Both use same ChatSession.process_message() — no logic duplication

### Why In-Memory + DB (not pure DB)
- In-memory: sub-millisecond reads for hot path (spatial queries, tool dispatch)
- DB: durability, cross-restart persistence, multi-user isolation
- Trade-off: chat-produced layers are session-scoped (acceptable data loss)

### Why Blueprints (not microservices)
- Same-process communication (no IPC overhead)
- Shared state via state.py (no message bus needed)
- SQLite requires single-process (microservices would need PostgreSQL)
- Blueprints provide logical separation without operational complexity
