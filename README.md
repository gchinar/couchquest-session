# CouchQuest session-service

Independent FastAPI microservice. Requires Python 3.12.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn app.main:app --port 8002
```

API documentation: http://localhost:8002/docs

DATABASE_URL defaults to a local SQLite file for development. For container deployment set it to a PostgreSQL SQLAlchemy URL using the psycopg driver. The service owns its own database. The Session service also reads CATALOG_URL, default http://localhost:8001.

```bash
docker build -t couchquest-session:1.0 .
```

The container requires DATABASE_URL for PostgreSQL; it runs as a non-root user and is not intended to write a SQLite file under /app. Deploy using the assignment package's Compose or Kubernetes manifests. Health routes: /health/live and /health/ready. No authentication is implemented; use only in a local demonstration environment.

## Solution and companion service

Full documentation and deployment files: https://github.com/gchinar/CouchQuest

Companion service: https://github.com/gchinar/couchquest-catalog
