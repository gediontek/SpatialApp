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
MAX_LAYERS_IN_MEMORY = Config.MAX_LAYERS_IN_MEMORY

# Chat sessions --------------------------------------------------------
chat_sessions = {}
session_lock = threading.Lock()
SESSION_TTL_SECONDS = Config.SESSION_TTL_SECONDS

# Database (set by create_app) -----------------------------------------
db = None

# SocketIO (set by create_app when flask-socketio is available) --------
socketio = None
