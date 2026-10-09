FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    KYVON_ENV=production \
    KYVON_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user; /app/data holds the database and must be a volume.
RUN useradd --system --create-home kyvon \
    && mkdir -p /app/data \
    && chown -R kyvon /app
USER kyvon
VOLUME /app/data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health/ready' % os.environ.get('PORT','8080'), timeout=3)"

ENTRYPOINT ["./docker-entrypoint.sh"]
