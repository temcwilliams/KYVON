#!/bin/sh
# Apply database migrations, then start the server.
set -e
flask --app wsgi kyvon db-upgrade
exec gunicorn -c gunicorn.conf.py wsgi:app
