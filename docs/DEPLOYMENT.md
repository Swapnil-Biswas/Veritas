# VERITAS Seller Backend — Deployment

The backend is one process: FastAPI plus an in-process worker pool, with a SQLite job database on persistent disk. The agent runs inside the same process, so any host with Python 3.11+ and outbound HTTPS can run the whole system.

## Configuration

Every variable is listed with placeholder values in [`../.env.example`](../.env.example). In production you must set:

- `VERITAS_ENV=production`. This disables `/docs` and requires the token.
- `HIRECREW_SELLER_TOKEN`: the token HireCrew issues after review.
- `VERITAS_DB_PATH`: a path on persistent storage.

## Option A — this machine + Tailscale Funnel (current)

This is how the owner's other HireCrew agents are exposed. Only the job routes are published; `/docs` and anything else stay local.

```bash
# 1. Run the backend (from the repo root)
pip install -r backend/requirements.txt
VERITAS_ENV=production HIRECREW_SELLER_TOKEN=<token> python backend/run_server.py   # listens on 127.0.0.1:8020

# 2. Publish only /jobs (and health) over HTTPS
tailscale funnel --bg --set-path=/veritas/jobs   http://127.0.0.1:8020/jobs
tailscale funnel --bg --set-path=/veritas/health http://127.0.0.1:8020/health
```

The seller endpoint is then `https://<machine>.<tailnet>.ts.net/veritas/jobs`.

Limits: the service is only up while the machine is on and the process is running. Use a process supervisor (Task Scheduler / NSSM on Windows, systemd on Linux) to restart it. Jobs survive restarts.

## Option B — container on any host

```bash
docker build -f deploy/Dockerfile -t veritas-seller .
docker run -d --name veritas --restart unless-stopped \
  -e HIRECREW_SELLER_TOKEN=<token> \
  -v veritas-data:/data \
  -p 127.0.0.1:8020:8020 \
  veritas-seller
```

Put a TLS-terminating proxy (Caddy, nginx, a platform router) in front of the container, and set `VERITAS_FORWARDED_ALLOW_IPS` to the proxy's address. The image runs as a non-root user, keeps the database on the `/data` volume, and has a built-in `HEALTHCHECK`.

## Operations

- **Health:** `GET /health` returns `200 {"status":"ok"}`, or `503` if the database or worker is down.
- **Logs:** stdout, redacted (see SECURITY.md). Each job logs `running (attempt n/m)`, then `delivered (k sources)` or `failed (CODE)`.
- **Restart safety:** queued jobs persist. A job that was running when the process died is re-claimed once its lease expires (`VERITAS_LEASE_SECONDS`) and runs again, up to `VERITAS_MAX_ATTEMPTS`.
- **Backups:** copy the SQLite file with `sqlite3 veritas_jobs.db ".backup backup.db"`, which is safe while the server is running.
- **Scaling:** one process per database file. For multiple hosts, replace `store.py` with a Postgres implementation (see ARCHITECTURE.md).
