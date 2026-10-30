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

## Independent Kubernetes deployment

This repository includes its own API, database, service and storage manifests. Start the dedicated Minikube profile, build only this service and deploy it:

```bash
minikube start -p couchquest --driver=docker --cpus=2 --memory=2800 --kubernetes-version=v1.35.0 --keep-context
minikube -p couchquest image build -t couchquest-session:1.0 .
python3 deployment/deploy.py --service session
```

The deployment script explicitly targets the couchquest context and preserves existing database credentials. Session creation requires the Catalog service, configured through CATALOG_URL; its unit tests replace that dependency with a test double. Both services can be released independently with `kubectl --context couchquest -n couchquest set image deployment/session session=YOUR_IMAGE_TAG`.
