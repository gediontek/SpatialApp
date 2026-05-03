"""WebSocket event handlers for NL-to-GIS chat.

Optional upgrade alongside SSE streaming. Uses Flask-SocketIO for
bidirectional communication with per-session room isolation.

The existing /api/chat SSE endpoint is unchanged — this module adds
a parallel WebSocket transport that reuses the same ChatSession logic.
"""

import json
import logging
import time
import threading

from flask import request, g

import state
from config import Config

logger = logging.getLogger(__name__)

# Per-SID user tracking. Flask-SocketIO's server.save_session() does not
# work reliably with the test client, so we use a simple dict guarded by
# a lock instead.
_sid_user_map = {}
_sid_user_lock = threading.Lock()

# v2.1 Plan 09: Track which collab session each SID belongs to.
# Mapping: sid -> session_id. Cleared on disconnect / leave_collab.
_sid_to_collab: dict[str, str] = {}

# Audit M2 + N4: per-chat-session cooperative-cancel flags. When the
# Stop button on the frontend emits 'chat_abort', the handler sets the
# flag here; the in-flight _process loop checks it after each event and
# bails out. Read/write under chat_session_id; eventual stale entries
# are cleaned up by `_check_and_clear_chat_abort`.
_chat_abort_flags: dict[str, bool] = {}
_chat_abort_lock = threading.Lock()


def _request_chat_abort(session_id: str) -> None:
    with _chat_abort_lock:
        _chat_abort_flags[session_id] = True


def _check_and_clear_chat_abort(session_id: str) -> bool:
    """Return True if abort was requested. Always clears the flag."""
    with _chat_abort_lock:
        return _chat_abort_flags.pop(session_id, False)


def register_websocket_events(socketio):
    """Register all Socket.IO event handlers on the given socketio instance.

    Called from create_app() after SocketIO initialization.
    """
    from flask_socketio import emit, join_room, disconnect

    @socketio.on('connect')
    def handle_connect(auth=None):
        """Handle new WebSocket connection.

        Validates bearer token from query params if CHAT_API_TOKEN is set.
        Sets user_id in the per-SID map for downstream use.
        """
        import hmac

        token = request.args.get('token', '')
        user_id = 'anonymous'

        if token:
            # Per-user token lookup
            if state.db:
                user = state.db.get_user_by_token(token)
                if user:
                    user_id = user['user_id']
                    with _sid_user_lock:
                        _sid_user_map[request.sid] = user_id
                    logger.info("WebSocket connected: user=%s sid=%s", user_id, request.sid)
                    return

            # Shared token check
            if Config.CHAT_API_TOKEN and hmac.compare_digest(token, Config.CHAT_API_TOKEN):
                with _sid_user_lock:
                    _sid_user_map[request.sid] = user_id
                logger.info("WebSocket connected: shared token, sid=%s", request.sid)
                return

            # Token provided but invalid
            logger.warning("WebSocket connection rejected: invalid token, sid=%s", request.sid)
            disconnect()
            return

        elif Config.CHAT_API_TOKEN:
            # Token required but not provided
            logger.warning("WebSocket connection rejected: no token provided, sid=%s", request.sid)
            disconnect()
            return

        # No token required — open access
        with _sid_user_lock:
            _sid_user_map[request.sid] = user_id
        logger.info("WebSocket connected: open access, sid=%s", request.sid)

    @socketio.on('disconnect')
    def handle_disconnect():
        """Clean up per-SID state and log disconnection."""
        sid = request.sid
        # Capture user_id before we drop the mapping
        with _sid_user_lock:
            user_id = _sid_user_map.pop(sid, None)
            collab_id = _sid_to_collab.pop(sid, None)
        # v2.1 Plan 09: clean collab session membership
        if collab_id and user_id:
            _leave_collab_session(collab_id, user_id, sid, socketio)
        logger.info("WebSocket disconnected: sid=%s", sid)

    # ------------------------------------------------------------------
    # v2.1 Plan 09: Real-time collaboration events
    # ------------------------------------------------------------------

    @socketio.on('join_collab')
    def handle_join_collab(data):
        """Add this SID's user to a collab session and broadcast user_joined.

        Args: {"session_id": str, "user_name": str (optional)}
        """
        from blueprints.collab import assign_color
        from config import Config

        if not isinstance(data, dict) or 'session_id' not in data:
            emit('collab_error', {'message': 'session_id is required'})
            return
        session_id = data['session_id']
        if not isinstance(session_id, str) or not session_id.startswith('collab_'):
            emit('collab_error', {'message': 'invalid session_id'})
            return

        with _sid_user_lock:
            user_id = _sid_user_map.get(request.sid, 'anonymous')

        user_name = data.get('user_name')
        if not isinstance(user_name, str) or not user_name.strip():
            user_name = user_id
        user_name = user_name.strip()[:80]

        with state.collab_lock:
            record = state.collab_sessions.get(session_id)
            if record is None:
                emit('collab_error', {'message': 'session not found'})
                return
            users = record.setdefault('users', {})
            cap = int(Config.COLLAB_MAX_USERS_PER_SESSION)
            # If the user is rejoining, just update their SID + name
            if user_id in users:
                users[user_id]['sid'] = request.sid
                users[user_id]['name'] = user_name
                color = users[user_id].get('color') or assign_color(record)
                users[user_id]['color'] = color
            else:
                if len(users) >= cap:
                    emit('collab_error', {'message': 'session full'})
                    return
                color = assign_color(record)
                users[user_id] = {
                    'name': user_name,
                    'color': color,
                    'cursor': None,
                    'sid': request.sid,
                    'joined_at': time.time(),
                    'last_cursor_ts': 0.0,
                }
            record['last_active'] = time.time()

            # Snapshot for broadcast (after exiting lock)
            user_list = [
                {
                    'user_id': uid, 'name': u['name'], 'color': u['color'],
                    'joined_at': u['joined_at'],
                }
                for uid, u in users.items()
            ]
            history_snapshot = list(record.get('layer_history', []))
            chat_snapshot = list(record.get('chat_messages', []))

        with _sid_user_lock:
            _sid_to_collab[request.sid] = session_id
        join_room(session_id)

        # Tell the joiner about the current state
        emit('collab_state', {
            'session_id': session_id,
            'users': user_list,
            'layer_history': history_snapshot,
            'chat_history': chat_snapshot,
            'self_user_id': user_id,
            'color': color,
        })

        # Tell everyone (including the joiner) that this user joined
        socketio.emit(
            'user_joined',
            {
                'session_id': session_id,
                'user_id': user_id,
                'name': user_name,
                'color': color,
            },
            room=session_id,
            namespace='/',
        )
        logger.info("collab join: sid=%s session=%s user=%s", request.sid, session_id, user_id)

    @socketio.on('leave_collab')
    def handle_leave_collab(data):
        """Explicit leave (separate from disconnect)."""
        if not isinstance(data, dict):
            return
        session_id = data.get('session_id')
        with _sid_user_lock:
            user_id = _sid_user_map.get(request.sid, 'anonymous')
            _sid_to_collab.pop(request.sid, None)
        if session_id and user_id:
            _leave_collab_session(session_id, user_id, request.sid, socketio)

    @socketio.on('cursor_move')
    def handle_cursor_move(data):
        """Throttled cursor broadcast."""
        from config import Config

        if not isinstance(data, dict):
            return
        try:
            lat = float(data['lat'])
            lon = float(data['lon'])
        except (KeyError, TypeError, ValueError):
            return
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return

        with _sid_user_lock:
            user_id = _sid_user_map.get(request.sid, 'anonymous')
            session_id = _sid_to_collab.get(request.sid)
        if not session_id:
            return

        throttle_s = int(Config.COLLAB_CURSOR_THROTTLE_MS) / 1000.0
        now = time.time()

        with state.collab_lock:
            record = state.collab_sessions.get(session_id)
            if record is None:
                return
            users = record.get('users', {})
            user_entry = users.get(user_id)
            if user_entry is None:
                return
            last_ts = user_entry.get('last_cursor_ts', 0.0)
            if now - last_ts < throttle_s:
                return
            user_entry['last_cursor_ts'] = now
            user_entry['cursor'] = {'lat': lat, 'lon': lon}
            record['last_active'] = now
            color = user_entry.get('color')
            name = user_entry.get('name')

        socketio.emit(
            'cursor_update',
            {
                'session_id': session_id,
                'user_id': user_id,
                'name': name,
                'color': color,
                'lat': lat,
                'lon': lon,
            },
            room=session_id,
            namespace='/',
            include_self=False,
        )

    @socketio.on('layer_remove')
    def handle_layer_remove(data):
        """Broadcast a layer removal across the collab session.

        Audit N2: ownership-checked. A WebSocket client cannot wipe a
        layer they do not own. Without this check, the C4 isolation fix
        was bypassable through the collab WebSocket path.
        """
        from blueprints.collab import append_layer_history

        if not isinstance(data, dict):
            return
        layer_name = data.get('layer_name')
        if not isinstance(layer_name, str) or not layer_name:
            return
        with _sid_user_lock:
            user_id = _sid_user_map.get(request.sid, 'anonymous')
            session_id = _sid_to_collab.get(request.sid)
        if not session_id:
            return

        # Per-user isolation (audit N2 — bypass guard for C4).
        owner = state.layer_owners.get(layer_name)
        if owner is not None and owner != user_id:
            logger.warning(
                "WS layer_remove rejected: sid=%s user=%s tried to remove "
                "layer %r owned by %s", request.sid, user_id, layer_name, owner,
            )
            return

        with state.collab_lock:
            record = state.collab_sessions.get(session_id)
            if record is None:
                return
            append_layer_history(record, {
                'user': user_id,
                'action': 'remove',
                'layer_name': layer_name,
                'timestamp': time.time(),
            })
            record['last_active'] = time.time()

        # Also remove from layer_store + owners map so future tools
        # don't see a ghost layer.
        with state.layer_lock:
            state.layer_store.pop(layer_name, None)
            state.layer_owners.pop(layer_name, None)

        socketio.emit(
            'layer_removed',
            {'session_id': session_id, 'user_id': user_id, 'layer_name': layer_name},
            room=session_id,
            namespace='/',
        )

    @socketio.on('layer_style')
    def handle_layer_style(data):
        """Broadcast a layer-style change."""
        from blueprints.collab import append_layer_history

        if not isinstance(data, dict):
            return
        layer_name = data.get('layer_name')
        style = data.get('style')
        if not isinstance(layer_name, str) or not isinstance(style, dict):
            return

        with _sid_user_lock:
            user_id = _sid_user_map.get(request.sid, 'anonymous')
            session_id = _sid_to_collab.get(request.sid)
        if not session_id:
            return

        with state.collab_lock:
            record = state.collab_sessions.get(session_id)
            if record is None:
                return
            append_layer_history(record, {
                'user': user_id,
                'action': 'style',
                'layer_name': layer_name,
                'style': style,
                'timestamp': time.time(),
            })
            record['last_active'] = time.time()

        socketio.emit(
            'layer_styled',
            {
                'session_id': session_id, 'user_id': user_id,
                'layer_name': layer_name, 'style': style,
            },
            room=session_id,
            namespace='/',
        )

    @socketio.on('join_session')
    def handle_join_session(data):
        """Join a chat session room for isolated event delivery.

        Args:
            data: {"session_id": str}
        """
        if not isinstance(data, dict) or 'session_id' not in data:
            emit('error', {'type': 'error', 'text': 'session_id is required'})
            return

        session_id = data['session_id']
        if not isinstance(session_id, str) or not session_id.strip():
            emit('error', {'type': 'error', 'text': 'Invalid session_id'})
            return

        join_room(session_id)
        emit('session_joined', {'session_id': session_id})
        logger.debug("Client %s joined session room %s", request.sid, session_id)

    @socketio.on('chat_message')
    def handle_chat_message(data):
        """Process a chat message via WebSocket.

        Reuses the same ChatSession.process_message() as the SSE endpoint.
        Emits events to the session room as they are generated.

        Args:
            data: {"session_id": str, "message": str, "context": dict (optional)}
        """
        from flask import current_app

        if not isinstance(data, dict):
            emit('chat_event', {'type': 'error', 'text': 'Invalid message format'})
            return

        message = data.get('message', '').strip()
        if not message:
            emit('chat_event', {'type': 'error', 'text': 'No message provided'})
            return
        if len(message) > 10000:
            emit('chat_event', {'type': 'error', 'text': 'Message too long (max 10,000 characters)'})
            return

        session_id = data.get('session_id', 'default')
        map_context = data.get('context', {})

        # Retrieve user_id from per-SID map
        with _sid_user_lock:
            user_id = _sid_user_map.get(request.sid, 'anonymous')

        # Get or create chat session (reuse existing helper)
        from blueprints.chat import _get_chat_session, _persist_chat_session

        chat_session = _get_chat_session(session_id, user_id=user_id)
        if chat_session is None:
            emit('chat_event', {'type': 'error', 'text': 'Session belongs to another user'})
            return

        # Process in a background thread to avoid blocking the SocketIO server
        def _process():
            start_time = time.time()
            tool_count = 0
            had_error = False

            try:
                for event in chat_session.process_message(message, map_context):
                    event_type = event.get('type', 'message')

                    if event_type == 'tool_result':
                        tool_count += 1
                    if event_type == 'error':
                        had_error = True

                    # Store layer in server-side store (with lock).
                    # Audit N3: tag ownership in state.layer_owners so the
                    # C4 isolation filter on /api/layers actually returns
                    # this layer to its owner. Without the tag the layer
                    # defaults to 'anonymous' and is invisible to authed
                    # callers.
                    if event_type == 'layer_add':
                        layer_name = event.get('name')
                        geojson = event.get('geojson')
                        if layer_name and geojson:
                            if state.db:
                                try:
                                    state.db.save_layer(layer_name, geojson, event.get('style'), user_id=user_id)
                                except Exception as db_err:
                                    logger.warning("DB save failed (layer via WS): %s", db_err)
                            with state.layer_lock:
                                state.layer_store[layer_name] = geojson
                                state.layer_owners[layer_name] = user_id
                                _evict_layers_ws()

                    # Audit N4: cooperative cancellation. If the user
                    # clicked Stop on the frontend, the chat_abort handler
                    # set the flag; bail out of the loop and tell the room.
                    if _check_and_clear_chat_abort(session_id):
                        logger.info("WS chat aborted by user: session=%s", session_id)
                        socketio.emit(
                            'chat_event',
                            {'type': 'aborted', 'text': 'Chat aborted by user'},
                            room=session_id,
                            namespace='/',
                        )
                        break

                    # Emit event to session room
                    socketio.emit('chat_event', event, room=session_id, namespace='/')

                # Persist session after processing
                _persist_chat_session(session_id, chat_session, user_id=user_id)

                # Log query metrics
                if state.db:
                    try:
                        duration_ms = int((time.time() - start_time) * 1000)
                        state.db.log_query_metric(
                            user_id=user_id,
                            session_id=session_id,
                            message=message,
                            tool_calls=tool_count,
                            input_tokens=chat_session.usage.get("total_input_tokens", 0),
                            output_tokens=chat_session.usage.get("total_output_tokens", 0),
                            duration_ms=duration_ms,
                            error=had_error,
                        )
                    except Exception:
                        logger.debug("Failed to log query metrics (WS) for session %s", session_id, exc_info=True)

            except Exception as e:
                logger.error("WebSocket chat processing error: %s", e, exc_info=True)
                socketio.emit(
                    'chat_event',
                    {'type': 'error', 'text': 'An internal error occurred'},
                    room=session_id,
                    namespace='/',
                )

        # Use socketio.start_background_task for thread safety
        socketio.start_background_task(_process)

    @socketio.on('chat_abort')
    def handle_chat_abort(data):
        """Cooperative-cancel an in-flight chat for this session (audit M2 + N4).

        The frontend Stop button emits this event. The in-flight _process
        loop checks _chat_abort_flags after each event and bails out.
        Args: {"session_id": str}
        """
        if not isinstance(data, dict):
            return
        session_id = data.get('session_id')
        if not isinstance(session_id, str) or not session_id.strip():
            return
        _request_chat_abort(session_id)
        logger.info("chat_abort requested: sid=%s session=%s",
                    request.sid, session_id)
        emit('chat_event', {'type': 'abort_acknowledged',
                            'session_id': session_id})


def _evict_layers_ws():
    """Evict layers if needed. Call under layer_lock."""
    from blueprints.layers import _evict_layers_if_needed
    _evict_layers_if_needed()


def _leave_collab_session(session_id: str, user_id: str, sid: str, socketio):
    """Remove a user from a collab session and notify peers."""
    departed = False
    name = None
    remaining = 0
    with state.collab_lock:
        record = state.collab_sessions.get(session_id)
        if record is None:
            return
        users = record.get('users', {})
        # Only remove if this SID was the active one — handles multi-tab race
        existing = users.get(user_id)
        if existing and existing.get('sid') == sid:
            users.pop(user_id, None)
            departed = True
            name = existing.get('name')
        remaining = len(users)
        record['last_active'] = time.time()

    if departed:
        socketio.emit(
            'user_left',
            {
                'session_id': session_id,
                'user_id': user_id,
                'name': name,
                'remaining_users': remaining,
            },
            room=session_id,
            namespace='/',
        )
        logger.info("collab leave: sid=%s session=%s user=%s remaining=%s",
                    sid, session_id, user_id, remaining)
