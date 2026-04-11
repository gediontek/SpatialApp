# Plan 9: Real-Time Collaboration

**Objective**: Add real-time multi-user collaboration to SpatialApp so that 2+ users can share a map session, see each other's cursors and layer operations, and chat collaboratively through the NL-GIS interface -- all with <1s propagation latency.

**Scope**: ~350 lines of Python (WebSocket events + session model), ~100 lines JS (presence UI + sync), ~80 lines tests. 2 focused days.

**Key files touched**:
- `blueprints/websocket.py` -- extend with collaboration events (presence, cursor, layer sync)
- `blueprints/chat.py` -- modify `_get_chat_session()` to support shared sessions
- `services/database.py` -- add `collab_sessions` table, session persistence
- `state.py` -- add `collab_sessions` dict for in-memory collaboration state
- `static/js/chat.js` -- add collaboration UI: join URL, shared chat rendering
- `static/js/collaboration.js` -- **new**: presence indicators, cursor sync, session management
- `static/js/layers.js` -- add `onLayerChange` callback for broadcasting layer mutations
- `nl_gis/chat.py` -- modify `ChatSession` to emit user-attributed messages
- `config.py` -- add `COLLAB_MAX_USERS_PER_SESSION`, `COLLAB_CURSOR_THROTTLE_MS`
- `tests/test_collaboration.py` -- **new**: multi-client WebSocket tests

**Prerequisite**: None (independent track). WebSocket transport already exists in `blueprints/websocket.py` with `register_websocket_events(socketio)`, room-based isolation via `join_room(session_id)`, and `chat_event` emission to session rooms.

---

## Milestone 1: Shared Map Sessions

### Epic 1.1: Collaboration Session Model

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Add `COLLAB_MAX_USERS_PER_SESSION` (default 10) and `COLLAB_CURSOR_THROTTLE_MS` (default 100) to `config.py` `Config` class. Add `COLLAB_SESSION_TTL_SECONDS` (default 86400 = 24h). | Config values accessible via `Config.COLLAB_MAX_USERS_PER_SESSION`. Configurable via env vars. | XS |
| T1.1.2 | Add `collab_sessions` dict and `collab_lock` to `state.py`. Structure: `collab_sessions = {}` mapping `session_id -> {"owner": str, "users": {user_id: {"name": str, "color": str, "cursor": {lat, lon}, "joined_at": float}}, "created_at": float, "layer_history": []}`. | `state.collab_sessions` exists at import time. `state.collab_lock` is a `threading.Lock()`. | XS |
| T1.1.3 | Add `collab_sessions` table to `services/database.py`. Schema: `id TEXT PRIMARY KEY, owner_user_id TEXT, created_at TEXT, last_active TEXT, session_state TEXT (JSON)`. Add `save_collab_session(session_id, state_dict)` and `get_collab_session(session_id)` methods to the `Database` class, following the pattern of `save_chat_session()`/`get_chat_session()`. Add migration in `_run_migrations()`. | `db.save_collab_session("sess_abc", {...})` persists. `db.get_collab_session("sess_abc")` retrieves. Table created on startup via migration. | M |
| T1.1.4 | Add a `POST /api/collab/create` route in a new `blueprints/collab.py` blueprint. Accepts `{"session_name": str (optional)}`. Generates a unique session ID (`collab_` + UUID), stores in `state.collab_sessions` with the requesting user as owner, persists to DB, returns `{"session_id": str, "join_url": str}`. The `join_url` is the app URL with `?collab=SESSION_ID` query param. Register blueprint in `app.py`. | `POST /api/collab/create` returns `{"session_id": "collab_xxx", "join_url": "http://localhost:5000/?collab=collab_xxx"}`. Session appears in `state.collab_sessions`. | M |
| T1.1.5 | Add a `GET /api/collab/<session_id>/info` route in `blueprints/collab.py`. Returns session metadata: owner, user count, created_at, list of connected user names/colors. | `GET /api/collab/collab_xxx/info` returns `{"owner": "user1", "users": [...], "created_at": "..."}`. Returns 404 for unknown sessions. | S |

### Epic 1.2: Join and Leave via WebSocket

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Add a `join_collab` WebSocket event handler in `blueprints/websocket.py` inside `register_websocket_events()`. Params: `{"session_id": str, "user_name": str (optional)}`. Validates: session exists, user count < `COLLAB_MAX_USERS_PER_SESSION`. Assigns the user a unique color from a predefined 10-color palette. Calls `join_room(session_id)`. Adds user to `state.collab_sessions[session_id]["users"]`. Emits `user_joined` to the room with user info. | Client emitting `join_collab({"session_id": "collab_xxx"})` triggers `user_joined` event to all room members. User appears in session's user list. Full session = rejected with error event. | M |
| T1.2.2 | Modify the existing `handle_disconnect()` in `websocket.py` to detect if the disconnecting SID was in a collab session. Remove user from `state.collab_sessions[session_id]["users"]`. Emit `user_left` to the room. If no users remain and session is >1h old, clean up. | When a connected collab user disconnects, other users receive `user_left` event with the departed user's info. | S |
| T1.2.3 | Add a `_sid_to_collab` dict in `websocket.py` (alongside existing `_sid_user_map`) to track which collab session each SID belongs to. Update on `join_collab`, clear on disconnect. Protected by `_sid_user_lock`. | Mapping is maintained accurately through join/disconnect cycles. | S |

### Epic 1.3: Layer Synchronization

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.3.1 | Modify the `_process()` function inside `handle_chat_message()` in `websocket.py` to check if the session is a collab session. If so, when emitting `layer_add` events, also store the layer operation in `state.collab_sessions[session_id]["layer_history"]` as `{"user": user_id, "action": "add", "layer_name": name, "timestamp": time.time()}`. | Layer additions in collab sessions are tracked in history. All room members receive the `layer_add` event (already handled by `socketio.emit(..., room=session_id)`). | M |
| T1.3.2 | Add a `layer_remove` WebSocket event handler. When a user removes a layer in a collab session, emit `layer_removed` to all room members so their `LayerManager` removes it. Also remove from `state.layer_store` under `state.layer_lock`. | User A removes layer -> User B's map removes the same layer within 1s. | S |
| T1.3.3 | Add a `layer_style` WebSocket event handler. When a user styles a layer, emit `layer_styled` with `{"layer_name": str, "style": dict}` to all room members. | User A styles a layer red -> User B sees it turn red within 1s. | S |

---

## Milestone 2: User Presence

### Epic 2.1: Cursor Tracking

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Add a `cursor_move` WebSocket event handler in `websocket.py`. Params: `{"lat": float, "lon": float}`. Throttle: ignore events that arrive within `Config.COLLAB_CURSOR_THROTTLE_MS` of the previous event from the same SID. Broadcast `cursor_update` to other users in the room (exclude sender). Payload: `{"user_id": str, "user_name": str, "color": str, "lat": float, "lon": float}`. | Client emitting `cursor_move` every 50ms results in throttled broadcasts at ~100ms intervals. Other clients receive `cursor_update` with correct user attribution. | M |
| T2.1.2 | Create `static/js/collaboration.js` with a `CollabManager` module. On initialization, receives the Leaflet map instance. Exposes: `joinSession(sessionId)`, `leaveSession()`, `updateCursor(lat, lon)`. Binds `map.on('mousemove')` to throttled `cursor_move` emission. Renders received cursors as colored circle markers with user name labels. Removes stale cursors after 10s without update. | Moving the mouse on the map sends throttled cursor events. Other users' cursors appear as colored dots with name labels. Stale cursors disappear. | M |
| T2.1.3 | Add user presence list UI in the sidebar. `CollabManager` maintains a `users` dict updated by `user_joined`/`user_left` events. Renders a `#collabUsers` div showing colored dots + user names. Updates dynamically. | Sidebar shows "2 users online" with colored indicators and names. Updates when users join/leave. | S |

### Epic 2.2: Viewport Sync (Optional Follow Mode)

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | Add a `viewport_change` WebSocket event emitted when any user pans/zooms. Payload: `{"center": {lat, lon}, "zoom": int, "user_id": str}`. Add a "Follow" toggle button per user in the presence list. When following User A, the local map syncs to User A's viewport events. | Clicking "Follow" on User A causes the local map to mirror User A's pan/zoom. Clicking again stops following. | M |

---

## Milestone 3: Shared Chat History

### Epic 3.1: User-Attributed Chat Messages

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Modify `ChatSession.process_message()` in `nl_gis/chat.py` to accept an optional `user_id` parameter. Include `user_id` in emitted message events: `{"type": "message", "text": "...", "user_id": "user1", "user_name": "Alice"}`. The existing SSE path passes `user_id` from `g.user_id`; the WebSocket path passes it from `_sid_user_map`. | Message events in collab sessions include `user_id` and `user_name` fields. Non-collab sessions include `user_id` = "anonymous" (backward compatible). | S |
| T3.1.2 | Modify `_get_chat_session()` in `blueprints/chat.py` to allow shared access when the session_id starts with `"collab_"`. For collab sessions, skip the user ownership check (line `if owner != user_id: return None`). Instead, verify the user is in `state.collab_sessions[session_id]["users"]`. | Multiple users can access the same `ChatSession` for collab sessions. Non-collab sessions retain strict ownership. | M |
| T3.1.3 | Update `static/js/chat.js` to render user attribution on received chat messages. In the `handleChatEvent()` function (or equivalent), check for `user_id`/`user_name` in message events. Display the user's name and color before their messages. Self-messages show "You", others show the user name with their assigned color. | Chat panel shows "Alice: Show parks in Chicago" with Alice's color indicator. Own messages show as "You: ...". | S |

### Epic 3.2: Replay on Join

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.2.1 | When a user joins a collab session via `join_collab`, emit the current chat history as a batch `chat_history` event. Read messages from `ChatSession.messages` (filtering to role="user" and role="assistant"). Send as `{"type": "chat_history", "messages": [...]}`. | New user joining sees the full conversation history. History includes user attribution. | M |
| T3.2.2 | On the frontend in `collaboration.js`, handle `chat_history` by rendering all messages in the chat panel using the existing `appendMessage()` or equivalent function. Mark them as historical (grayed timestamp). | Late-joining user sees prior messages with correct attribution and styling. | S |

---

## Milestone 4: Session Persistence and Export

### Epic 4.1: Persist and Resume

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Add auto-save logic in `blueprints/websocket.py`: after each `chat_message` processing completes, call `db.save_collab_session(session_id, state)` where state includes chat messages and layer_history. Debounce: save at most once per 30 seconds. | Collab session state is persisted to SQLite. Restart the server -> session is recoverable. | M |
| T4.1.2 | Add `GET /api/collab/<session_id>/resume` route. Loads session from DB, restores `state.collab_sessions` entry, returns session info. The frontend calls this on page load when `?collab=SESSION_ID` is in the URL. | Navigating to `/?collab=collab_xxx` after server restart loads the session with its layer history and chat messages. | M |

### Epic 4.2: Export as Reproducible Workflow

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | Add `GET /api/collab/<session_id>/export` route. Extracts the sequence of NL commands from the chat history (messages with role="user"). Returns a JSON document: `{"workflow": [{"step": 1, "user": "Alice", "command": "Show parks in Chicago", "timestamp": "..."}, ...], "session_id": str, "created_at": str}`. | Export returns ordered list of all NL commands that produced the current map state. Commands are attributed to users. | M |
| T4.2.2 | Add a `POST /api/collab/replay` route that accepts a workflow JSON and replays it by calling `ChatSession.process_message()` for each step sequentially. Returns SSE stream of all events. This allows reproducing a session's map state from the exported workflow. | Importing a workflow and replaying it recreates the same layers and map state as the original session. | M |

---

## Milestone 5: Testing

### Epic 5.1: Multi-Client WebSocket Tests

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Create `tests/test_collaboration.py`. Use `flask_socketio.SocketIOTestClient` (already in the project via `flask-socketio>=5.3.0`). Test: (1) create collab session via REST, (2) two clients join via `join_collab`, (3) both receive `user_joined` events, (4) one client sends `cursor_move`, other receives `cursor_update`, (5) one client disconnects, other receives `user_left`. | 5 test cases passing. Two `SocketIOTestClient` instances interact correctly within the same session. | L |
| T5.1.2 | Test layer synchronization: Client A sends a chat message that produces a layer -> Client B receives `layer_add` event. Client A emits `layer_remove` -> Client B receives `layer_removed`. Verify `state.collab_sessions` tracks the layer history. | Layer sync tests pass. History contains correct entries. | M |
| T5.1.3 | Test shared chat history: Client A sends a message -> Client B sees it attributed to A. Client C joins late -> receives `chat_history` with prior messages. | Chat attribution and history replay tests pass. | M |
| T5.1.4 | Test concurrency: Two clients send chat messages simultaneously. Verify no race conditions on `state.collab_sessions` or `state.layer_store`. Verify both messages are processed (possibly sequentially due to `ChatSession` not being thread-safe -- document this as a known limitation). | Concurrent messages do not crash. Both are processed. If serialized, document why. | M |
| T5.1.5 | Test latency: Measure time from `cursor_move` emission to `cursor_update` receipt. Assert < 100ms in test environment (loopback). Document expected production latency. | Latency measurement logged. Assert under 100ms in test (loopback). | S |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| `ChatSession` is not thread-safe for concurrent writes | Race condition: two users' messages interleave in the LLM context | Serialize chat messages per session using a per-session `threading.Lock()`. Add `_chat_lock` to the collab session state. Document in SYSTEM_PROMPT that responses may queue. |
| Cursor broadcast floods the WebSocket | High bandwidth, client lag | Throttle to `COLLAB_CURSOR_THROTTLE_MS` (100ms). Use `include_self=False` on broadcast. Client-side: skip cursor rendering if delta < 2px. |
| Session state grows unbounded | Memory exhaustion with long-lived sessions | Cap `layer_history` at 1000 entries (FIFO). Persist to DB periodically. Evict in-memory collab sessions after `COLLAB_SESSION_TTL_SECONDS`. |
| User impersonation in collab sessions | Security: user pretends to be another user | User identity comes from `_sid_user_map` (server-set at connect time), not from client-supplied data. Never trust client-supplied `user_id`. |
| WebSocket disconnection / reconnection | User loses presence, misses events | On reconnect, re-emit `join_collab`. Server sends `chat_history` catch-up. Frontend detects disconnect and shows "Reconnecting..." indicator. |

## Output Artifacts

- `blueprints/collab.py` -- **new**: 4 REST routes (create, info, resume, export) (~80 lines)
- `blueprints/websocket.py` -- extended: 5 new event handlers (join_collab, cursor_move, layer_remove, layer_style, viewport_change) (~120 lines)
- `blueprints/chat.py` -- modified: shared session access for collab (~15 lines changed)
- `services/database.py` -- `collab_sessions` table + 2 methods (~40 lines)
- `state.py` -- `collab_sessions`, `collab_lock` (~5 lines)
- `static/js/collaboration.js` -- **new**: `CollabManager` module (~100 lines)
- `static/js/chat.js` -- user attribution rendering (~20 lines changed)
- `static/js/layers.js` -- layer change callback (~10 lines)
- `nl_gis/chat.py` -- user_id in message events (~10 lines changed)
- `config.py` -- 3 collab config vars (~5 lines)
- `tests/test_collaboration.py` -- **new**: 10+ test cases (~150 lines)
