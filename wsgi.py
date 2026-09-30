"""WSGI entry point: ``gunicorn wsgi:app``."""

from kyvon import create_app

app = create_app()
