"""Shared application state for SpatialApp.

All mutable global state lives here so blueprints can import it
without creating circular dependencies with app.py.

Initialized at module-import time (locks, empty containers).
The ``db`` reference is set by ``create_app()`` after database init.
"""

import threading
from collections import OrderedDict

from config import Config

# Annotations ----------------------------------------------------------
geo_coco_annotations = []
annotation_lock = threading.Lock()

# Layers ---------------------------------------------------------------
layer_store = OrderedDict()
layer_lock = threading.Lock()
# Parallel ownership map: layer_name -> user_id. Populated alongside
# layer_store on save/restore. Readers MUST filter via this map to
# enforce per-user isolation (audit C4, path B). "anonymous" entries
# are visible to anonymous callers only.
layer_owners: dict = {}
MAX_LAYERS_IN_MEMORY = Config.MAX_LAYERS_IN_MEMORY

# Chat sessions --------------------------------------------------------
chat_sessions = {}
session_lock = threading.Lock()
SESSION_TTL_SECONDS = Config.SESSION_TTL_SECONDS

# Database (set by create_app) -----------------------------------------
db = None

# SocketIO (set by create_app when flask-socketio is available) --------
socketio = None

# Real-time collaboration (v2.1 Plan 09) -------------------------------
# Schema:
#   collab_sessions[session_id] = {
#     "owner": str, "name": str | None,
#     "users": {user_id: {"name": str, "color": str, "cursor": {lat, lon} | None,
#                          "joined_at": float, "sid": str | None,
#                          "last_cursor_ts": float}},
#     "created_at": float,
#     "last_active": float,
#     "layer_history": [{"user": str, "action": "add"|"remove"|"style",
#                         "layer_name": str, "timestamp": float, ...}],
#     "chat_messages": [{"user_id": str, "user_name": str,
#                          "role": str, "text": str, "timestamp": float}],
#   }
collab_sessions = {}
collab_lock = threading.Lock()
