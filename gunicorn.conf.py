import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Worker processes
workers = int(os.environ.get('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))
worker_class = 'gthread'  # Threaded workers for SQLite compatibility
threads = 4

# Timeouts
timeout = 300  # Long timeout for LLM tool chains
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info')

# Security
limit_request_line = 8190
limit_request_fields = 100

# Preload for memory efficiency (but note: SQLite connections are per-thread)
preload_app = False  # False because of thread-local SQLite connections


# Server hooks
def post_fork(server, worker):
    """Reset state after fork to avoid sharing file descriptors."""
    pass
