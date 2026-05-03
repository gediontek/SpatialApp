"""Chat blueprint: NL-to-GIS chat API, usage, and metrics."""

import json
import logging
import os
import threading

from flask import Blueprint, jsonify, request, g

from config import Config
import state
from blueprints.auth import require_api_token

chat_bp = Blueprint('chat', __name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _cleanup_expired_sessions():
    """Remove sessions not accessed within TTL. Acquires session_lock internally."""
    import time as _t
    with state.session_lock:
        now = _t.time()
        expired = [sid for sid, entry in state.chat_sessions.items()
                   if now - entry.get("last_access", 0) > state.SESSION_TTL_SECONDS]
        for sid in expired:
            entry = state.chat_sessions[sid]
            # Persist to DB before evicting from memory
            if state.db:
                try:
                    user_id = entry.get("user_id", "anonymous")
                    state.db.save_chat_session(sid, entry["session"].messages, user_id=user_id)
                except Exception:
                    logging.debug("Failed to persist expired session %s to DB", sid, exc_info=True)
            state.chat_sessions.pop(sid)
        if expired:
            logging.info(f"Evicted {len(expired)} expired chat sessions")


def _start_session_cleanup_timer():
    """Run session cleanup every 5 minutes in a background thread.

    Guarded: does not start in test mode or when DISABLE_CLEANUP_TIMER env var is set.
    """
    if os.environ.get("DISABLE_CLEANUP_TIMER") or os.environ.get("TESTING"):
        logging.debug("Session cleanup timer disabled (test/env guard)")
        return

    def _loop():
        while True:
            import time as _t
            _t.sleep(300)  # Every 5 minutes
            try:
                _cleanup_expired_sessions()
            except Exception as e:
                logging.error(f"Session cleanup failed: {e}", exc_info=True)

    t = threading.Thread(target=_loop, daemon=True, name="session-cleanup")
    t.start()


def _get_chat_session(session_id: str = "default", user_id: str = "anonymous"):
    """Get or create a chat session (thread-safe).

    Verifies the requesting user owns the session. Returns None if
    the session exists but belongs to a different user.
    Restores message history from database if available.
    """
    import time as _t
    from flask import current_app
    from nl_gis.chat import ChatSession
    with state.session_lock:

        if session_id in state.chat_sessions:
            entry = state.chat_sessions[session_id]
            # Verify session ownership
            owner = entry.get("user_id", "anonymous")
            if owner != user_id:
                return None  # Caller must handle as 403
            entry["last_access"] = _t.time()
            return entry["session"]

        session = ChatSession(layer_store=state.layer_store, layer_lock=state.layer_lock)
        # Restore message history from database, honoring stored ownership.
        # If the session exists in the DB but belongs to a different user,
        # return None so the caller responds 403 — never silently take over
        # ownership. (Audit C3.)
        if state.db:
            try:
                saved = state.db.get_chat_session_with_owner(session_id)
                if saved is not None:
                    owner_uid = saved.get("user_id")
                    if owner_uid and owner_uid != user_id:
                        return None  # Caller handles as 403
                    msgs = saved.get("messages") or []
                    if msgs:
                        session.messages = msgs
            except Exception as db_err:
                current_app.logger.warning(f"DB restore failed (session): {db_err}")
        state.chat_sessions[session_id] = {"session": session, "last_access": _t.time(), "user_id": user_id}
        return session


def _persist_chat_session(session_id: str, session, user_id: str = "anonymous"):
    """Save session to DB first, then update in-memory cache.

    DB is source of truth for chat sessions. If DB write fails,
    the exception propagates (caller's error handler catches it).
    The in-memory entry is already present from _get_chat_session,
    so we just ensure DB is written.
    """
    from flask import current_app
    if state.db:
        state.db.save_chat_session(session_id, session.messages, user_id=user_id)


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@chat_bp.route('/api/chat', methods=['POST'])
@require_api_token
def api_chat():
    """Process a natural language message and return SSE event stream."""
    from flask import current_app
    import time as _time

    data = request.get_json(silent=True)
    if not data or 'message' not in data:
        return jsonify(error='No message provided'), 400

    message = data['message'].strip()
    if not message:
        return jsonify(error='Empty message'), 400
    if len(message) > 10000:
        return jsonify(error='Message too long (max 10,000 characters)'), 400

    session_id = data.get('session_id', 'default')
    map_context = data.get('context', {})
    user_id = getattr(g, 'user_id', 'anonymous')

    plan_mode = data.get('plan_mode', False)

    session = _get_chat_session(session_id, user_id=user_id)
    if session is None:
        return jsonify(error='Session belongs to another user'), 403

    def generate():
        from services.metrics import metrics as _prom
        start_time = _time.time()
        tool_count = 0
        had_error = False
        tool_metrics = []
        try:
            for event in session.process_message(message, map_context, plan_mode=plan_mode):
                event_type = event.get('type', 'message')

                if event_type == 'tool_result':
                    tool_count += 1
                    tool_name = event.get('tool', 'unknown')
                    _prom.inc("tool_calls_total", {"tool": tool_name})
                if event_type == 'error':
                    had_error = True
                # Capture tool metrics from final message event
                if event_type == 'message' and event.get('done') and event.get('tool_metrics'):
                    tool_metrics = event['tool_metrics']

                # Store layer in server-side store (with lock)
                if event_type == 'layer_add':
                    layer_name = event.get('name')
                    geojson = event.get('geojson')
                    if layer_name and geojson:
                        # For chat-engine path: try DB first, but a failure
                        # is a warning (layer is still useful in-memory for
                        # the current session).
                        if state.db:
                            try:
                                state.db.save_layer(layer_name, geojson, event.get('style'), user_id=user_id)
                            except Exception as db_err:
                                current_app.logger.warning(f"DB save failed (layer): {db_err}")
                        with state.layer_lock:
                            state.layer_store[layer_name] = geojson
                            _evict_layers_if_needed()

                # Chunked delivery for large layers (500+ features)
                if event_type == 'layer_add':
                    features = geojson.get('features', []) if geojson else []
                    CHUNK_SIZE = 500
                    if len(features) > CHUNK_SIZE:
                        # Send layer_init event first (no features, just metadata)
                        init_event = {
                            "type": "layer_init",
                            "name": layer_name,
                            "total_features": len(features),
                            "chunks": (len(features) + CHUNK_SIZE - 1) // CHUNK_SIZE,
                            "style": event.get('style'),
                        }
                        yield f"event: layer_init\ndata: {json.dumps(init_event)}\n\n"

                        # Send features in chunks
                        for i in range(0, len(features), CHUNK_SIZE):
                            chunk = features[i:i + CHUNK_SIZE]
                            chunk_event = {
                                "type": "layer_chunk",
                                "name": layer_name,
                                "chunk_index": i // CHUNK_SIZE,
                                "geojson": {"type": "FeatureCollection", "features": chunk},
                            }
                            yield f"event: layer_chunk\ndata: {json.dumps(chunk_event)}\n\n"
                    else:
                        # Small layer — send as single event (existing behavior)
                        yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                else:
                    yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

            # Record request duration
            _prom.observe("chat_request_duration_seconds", _time.time() - start_time)

            # Persist chat session after stream completes
            _persist_chat_session(session_id, session, user_id=user_id)

            # Log query metrics
            if state.db:
                try:
                    duration_ms = int((_time.time() - start_time) * 1000)
                    state.db.log_query_metric(
                        user_id=user_id,
                        session_id=session_id,
                        message=message,
                        tool_calls=tool_count,
                        input_tokens=session.usage.get("total_input_tokens", 0),
                        output_tokens=session.usage.get("total_output_tokens", 0),
                        duration_ms=duration_ms,
                        error=had_error,
                        tool_details=tool_metrics,
                    )
                except Exception:
                    logging.debug("Failed to log query metrics for session %s", session_id, exc_info=True)
        except Exception as e:
            current_app.logger.error(f"SSE stream error: {e}", exc_info=True)
            error_event = {"type": "error", "text": "An internal error occurred"}
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

    return current_app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@chat_bp.route('/api/chat/execute-plan', methods=['POST'])
@require_api_token
def api_execute_plan():
    """Execute a previously generated plan step by step. Returns SSE event stream."""
    from flask import current_app
    import time as _time

    data = request.get_json(silent=True)
    if not data or 'plan_steps' not in data:
        return jsonify(error='No plan_steps provided'), 400

    plan_steps = data['plan_steps']
    if not isinstance(plan_steps, list) or len(plan_steps) == 0:
        return jsonify(error='plan_steps must be a non-empty array'), 400

    if len(plan_steps) > 20:
        return jsonify(error='Plan too large (max 20 steps)'), 400

    session_id = data.get('session_id', 'default')
    user_id = getattr(g, 'user_id', 'anonymous')

    session = _get_chat_session(session_id, user_id=user_id)
    if session is None:
        return jsonify(error='Session belongs to another user'), 403

    def generate():
        start_time = _time.time()
        tool_count = 0
        had_error = False
        tool_metrics = []
        try:
            for event in session.execute_plan(plan_steps):
                event_type = event.get('type', 'message')

                if event_type == 'tool_result':
                    tool_count += 1
                if event_type == 'error':
                    had_error = True
                if event_type == 'message' and event.get('done') and event.get('tool_metrics'):
                    tool_metrics = event['tool_metrics']

                # Store layer in server-side store (with lock)
                if event_type == 'layer_add':
                    layer_name = event.get('name')
                    geojson = event.get('geojson')
                    if layer_name and geojson:
                        if state.db:
                            try:
                                state.db.save_layer(layer_name, geojson, event.get('style'), user_id=user_id)
                            except Exception as db_err:
                                current_app.logger.warning(f"DB save failed (layer): {db_err}")
                        with state.layer_lock:
                            state.layer_store[layer_name] = geojson
                            _evict_layers_if_needed()

                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"

            # Persist chat session after execution
            _persist_chat_session(session_id, session, user_id=user_id)

            # Log query metrics
            if state.db:
                try:
                    duration_ms = int((_time.time() - start_time) * 1000)
                    state.db.log_query_metric(
                        user_id=user_id,
                        session_id=session_id,
                        message=f"[plan-execute] {len(plan_steps)} steps",
                        tool_calls=tool_count,
                        input_tokens=0,
                        output_tokens=0,
                        duration_ms=duration_ms,
                        error=had_error,
                        tool_details=tool_metrics,
                    )
                except Exception:
                    logging.debug("Failed to log query metrics for plan execution", exc_info=True)
        except Exception as e:
            current_app.logger.error(f"SSE stream error (plan execute): {e}", exc_info=True)
            error_event = {"type": "error", "text": "An internal error occurred"}
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

    return current_app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )


@chat_bp.route('/api/usage')
@require_api_token
def api_usage():
    """Get token usage stats for a chat session."""
    user_id = getattr(g, 'user_id', 'anonymous')
    session_id = request.args.get('session_id', 'default')
    with state.session_lock:
        entry = state.chat_sessions.get(session_id)
    if not entry:
        return jsonify(usage={"total_input_tokens": 0, "total_output_tokens": 0, "api_calls": 0})
    # Verify session ownership
    owner = entry.get("user_id", "anonymous")
    if owner != user_id:
        return jsonify(error='Unauthorized'), 403
    return jsonify(usage=entry["session"].usage)


@chat_bp.route('/api/metrics')
@require_api_token
def api_metrics():
    """Get aggregated query metrics.

    Returns total queries, tool calls, tokens, avg duration, error rate.
    Filters by current user if authenticated with per-user token.
    """
    if not state.db:
        return jsonify(error='Database not available'), 500

    user_id = getattr(g, 'user_id', 'anonymous')

    # If anonymous or shared token, show all metrics; otherwise per-user
    filter_user = user_id if user_id != 'anonymous' else None
    summary = state.db.get_metrics_summary(user_id=filter_user)
    summary['user_id'] = user_id
    return jsonify(metrics=summary)


def _evict_layers_if_needed():
    """Remove oldest layers when store exceeds limit. Call under layer_lock."""
    from blueprints.layers import _evict_layers_if_needed as _evict
    _evict()
