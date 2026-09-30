"""Gunicorn settings. Override with environment variables."""

import os

bind = f"{os.getenv('KYVON_HOST', '0.0.0.0')}:{os.getenv('PORT', '8080')}"

# One worker on purpose: SQLite is a single-file database, and the login-failure
# throttle lives in process memory. Threads give concurrency for slow model calls.
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))

# Model calls (especially web research) can be slow.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
# On SIGTERM (systemctl stop/restart) finish in-flight requests, then exit.
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
