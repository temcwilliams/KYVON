"""Development entry point: ``python app.py`` (serves on port 8080).

The application lives in the ``kyvon`` package. Production uses gunicorn
(``wsgi:app``). This file exists so the historical ``python app.py`` command and
service units keep working.
"""

from wsgi import app

if __name__ == "__main__":
    settings = app.extensions["kyvon"].settings
    app.run(host=settings.host, port=settings.port, debug=False)
