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
        with _sid_user_lock:
            _sid_user_map.pop(request.sid, None)
        logger.info("WebSocket disconnected: sid=%s", request.sid)

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

                    # Store layer in server-side store (with lock)
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
                                _evict_layers_ws()

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


def _evict_layers_ws():
    """Evict layers if needed. Call under layer_lock."""
    from blueprints.layers import _evict_layers_if_needed
    _evict_layers_if_needed()
