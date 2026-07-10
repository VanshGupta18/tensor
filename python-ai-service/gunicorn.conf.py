"""
Gunicorn configuration — shared by local dev and CF production.

Local:  .venv/bin/gunicorn -c gunicorn.conf.py app:app
CF:     web: gunicorn -c gunicorn.conf.py --bind 0.0.0.0:$PORT app:app
"""
import os
import sys

_IS_DARWIN = sys.platform == "darwin"

# Single worker: ML models (embedding + reranker) are singletons per process.
workers = 1

# gthread + PyTorch on macOS triggers MPS/fork crashes — use sync locally.
if _IS_DARWIN:
    worker_class = "sync"
    threads = 1
else:
    worker_class = "gthread"
    threads = 4

# preload_app shares the import graph via fork on Linux (CF). On macOS, fork +
# PyTorch/MPS/objc causes SIGABRT when workers respawn — disable there.
_default_preload = "false" if _IS_DARWIN else "true"
preload_app = os.environ.get("PRELOAD_APP", _default_preload).lower() == "true"

# macOS: avoid objc_initializeAfterForkError when Gunicorn respawns a worker.
if _IS_DARWIN:
    raw_env = [
        "OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES",
        "TOKENIZERS_PARALLELISM=false",
        "ML_DEVICE=cpu",
    ]

# Long timeout for PDF extraction (can take several minutes on large docs).
timeout = 660

# Default to port 8000 locally; CF overrides with --bind 0.0.0.0:$PORT.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-") if os.environ.get("LOG_REQUESTS") else None
errorlog = "-"
loglevel = "info"
