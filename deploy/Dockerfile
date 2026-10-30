# VERITAS seller backend: API + in-process worker pool + the Antigravity agent package
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VERITAS_ENV=production \
    VERITAS_HOST=0.0.0.0 \
    VERITAS_PORT=8020 \
    VERITAS_DB_PATH=/data/veritas_jobs.db

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY agent ./agent
COPY backend ./backend

# Persistent job database lives on a mounted volume; run as an unprivileged user.
RUN useradd --create-home --uid 10001 veritas && mkdir -p /data && chown veritas /data
USER veritas
VOLUME ["/data"]
EXPOSE 8020

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8020/health').status==200 else 1)"

CMD ["python", "backend/run_server.py"]
