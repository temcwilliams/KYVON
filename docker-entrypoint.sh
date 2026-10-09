#!/bin/sh
# Apply database migrations, then start the server.
set -e
# Hosted deployments migrate once in a separate step (KYVON_SKIP_MIGRATE=1), not in every container.
if [ "${KYVON_SKIP_MIGRATE:-0}" != "1" ]; then
    flask --app wsgi kyvon db-upgrade
fi
flask --app wsgi kyvon doctor --quiet
exec gunicorn -c gunicorn.conf.py wsgi:app
