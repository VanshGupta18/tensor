# TenderFlow — Runbook (SAP BTP / BAS)

Runbook for **Business Application Studio (BAS)** local development and **Cloud Foundry (BTP)** deployment.

---

## Architecture

```mermaid
flowchart LR
  Browser -->|dev:5173 / prod:same origin| UI[React UI]
  UI -->|/api or same origin| CAP[CAP Node tender-cap-srv :4004]
  CAP -->|PYTHON_AI_URL| PY[Python AI tender-python-ai :8002]
  CAP --> PG[(PostgreSQL + pgvector)]
  PY --> PG
  PY --> AICore[SAP AI Core]
```

| Component | Local | Cloud Foundry |
|-----------|-------|---------------|
| React UI | Vite `:5173` | Served from CAP `app/` |
| CAP backend | `cds watch` `:4004` | `tender-cap-srv` |
| Python AI | Gunicorn `:8002` | `tender-python-ai` (2 GB RAM) |
| Database | Docker Postgres `:5433` | `tender-postgres` (managed) |

---

## 0. Prerequisites

### BTP subaccount entitlements

Enable in **Entitlements → Configure Entitlements**:

- **Cloud Foundry** (org + space)
- **PostgreSQL, Hyperscaler Option** — plan `trial` (needs `vector` extension — configured in `mta.yaml`)
- **XSUAA** — plan `application`
- **SAP AI Core** — deployment URL + OAuth client for inference

### BAS dev space

Create a **Full-Stack Cloud Application** dev space (or CAP dev space) with:

- Node.js 20+
- Python 3.11
- `@sap/cds-dk`, MBT (`mbt`), CF CLI

Log in to Cloud Foundry from BAS terminal:

```bash
cf login -a <api-endpoint>   # e.g. https://api.cf.us10.hana.ondemand.com
cf target -o <org> -s <space>
```

---

## 1. Clone and install

```bash
git clone <repo-url> tensor
cd tensor
```

### Root scripts

```bash
# From repo root — three processes in separate terminals (see §3)
npm run backend   # CAP on :4004
npm run frontend  # Vite on :5173
npm run ai        # Python on :8002
```

---

## 2. Environment configuration

### 2.1 PostgreSQL (local)

Start pgvector Postgres:

```bash
docker compose up -d
```

Defaults (`docker-compose.yml`):

- Host: `localhost:5433`
- DB: `tenderflow` / user: `tenderflow` / password: `tenderflow`

Deploy CAP schema:

```bash
cd cap-backend
npm ci
npx cds deploy --to postgres
```

### 2.2 Python AI service

Create `python-ai-service/.env` (never commit secrets):

```bash
# SAP AI Core OAuth
TOKEN_URL=https://<subaccount>.authentication.<region>.hana.ondemand.com/oauth/token
CLIENT_ID=<ai-core-service-key-client-id>
CLIENT_SECRET=<ai-core-service-key-secret>

# Inference deployment (from AI Core → Deployments)
MODEL_BASE_URL=https://api.ai.prod.<region>.aws.ml.hana.ondemand.com/v2/inference/deployments/<deployment-id>
MODEL_ENDPOINT=/invoke

# Local Postgres (matches docker-compose)
POSTGRES_URL=postgresql://tenderflow:tenderflow@localhost:5433/tenderflow
```

Install Python deps with **uv**:

```bash
cd python-ai-service
uv sync
```

Verify:

```bash
.venv/bin/python -c "from app import app; print('ok')"
curl -s http://localhost:8002/health
# → {"status":"ok","extractionGroupCount":7}
```

### 2.3 CAP backend

Local DB is already in `cap-backend/package.json` under `cds.requires.[development]`.

Python URL (optional override):

```bash
export PYTHON_AI_URL=http://localhost:8002
```

Dev auth uses **mocked** users (`admin`/`admin`, `alice`/`alice`).

---

## 3. Local run (BAS — 4 terminals)

Use **one terminal per long-running process**.

**Terminal 1 — Postgres**

```bash
cd tensor
docker compose up
```

**Terminal 2 — Python AI**

```bash
cd tensor
npm run ai
# → gunicorn on http://localhost:8002
```

**Terminal 3 — CAP**

```bash
cd tensor
npm run backend
# → cds watch on http://localhost:4004
```

**Terminal 4 — React**

```bash
cd tensor
npm run frontend
# → Vite on http://localhost:5173
```

Open: **http://localhost:5173**

Vite proxies:

- `/api/*` → CAP `:4004`
- `/upload` → CAP `:4004` (10 min timeout for large PDFs)

---

## 4. Smoke test (local)

| Check | Command / action |
|-------|------------------|
| Python health | `curl http://localhost:8002/health` |
| CAP OData | `curl -u admin:admin http://localhost:4004/odata/v4/tender/$metadata` |
| Login | UI → `admin` / `admin` |
| Upload | Upload a PDF tender → wait for extraction (large docs: several minutes) |
| PDF synopsis | Generate PDF from tender detail |
| Analytics | Upload timeline should show `7/7` extraction groups |

---

## 5. Deploy to Cloud Foundry (BTP)

### 5.1 Build MTA archive

From repo root:

```bash
npm ci --prefix react-frontend
npm ci --prefix cap-backend
mbt build -p=cf
```

Output: `mta_archives/tender-platform_1.0.0.mtar`

The build (`mta.yaml`):

1. Builds React → `cap-backend/app/`
2. Runs `cds build --production`
3. Copies `app/` into `cap-backend/gen/srv/app`
4. Packages 3 modules: `tender-python-ai`, `tender-cap-srv`, `tender-db-deployer`

### 5.2 Deploy

```bash
cf deploy mta_archives/tender-platform_1.0.0.mtar
```

Creates/binds:

- `tender-postgres` (PostgreSQL + `vector` extension)
- `tender-xsuaa` (from `xs-security.json`)
- `tender-python-ai` → URL wired to CAP via `PYTHON_AI_URL`

### 5.3 Run database deployer

One-shot schema task:

```bash
cf run-task tender-db-deployer -k 4G -m 512M --name deploy-schema --command "npm start"
cf logs tender-db-deployer --recent
```

### 5.4 Set AI Core env on Python app

`.env` is **not** deployed (ignored in `mta.yaml`). Set manually:

```bash
cf set-env tender-python-ai TOKEN_URL      "<value>"
cf set-env tender-python-ai CLIENT_ID      "<value>"
cf set-env tender-python-ai CLIENT_SECRET  "<value>"
cf set-env tender-python-ai MODEL_BASE_URL "<value>"
cf set-env tender-python-ai MODEL_ENDPOINT "/invoke"
cf restage tender-python-ai
```

Postgres URL is auto-resolved from `VCAP_SERVICES` in Python (`ingestion.py`).

### 5.5 XSUAA roles (production auth)

Assign in **BTP Cockpit → Security → Role Collections**:

| Role collection | Purpose |
|-----------------|---------|
| `TenderFlow Admin` | Full access |
| `TenderFlow Reviewer` | Read/review |

**Important:** `cap-backend/package.json` still uses `auth.kind: "mocked"` for dev. For real BTP auth, add a production profile before deploy:

```json
"[production]": {
  "requires": {
    "auth": { "kind": "xsuaa" }
  }
}
```

Then rebuild and redeploy MTA. Update the React client to use XSUAA tokens instead of hardcoded Basic auth (`react-frontend/src/api/client.js`).

### 5.6 Verify CF deployment

```bash
cf apps
# tender-cap-srv, tender-python-ai should be "started"

cf app tender-cap-srv
# note the route URL

curl https://<tender-python-ai-route>/health
curl https://<tender-cap-srv-route>/odata/v4/tender/$metadata
```

Open CAP route in browser — React UI is served from the same origin (no `/api` prefix in production).

---

## 6. Service sizing (CF)

From `mta.yaml`:

| App | Memory | Disk |
|-----|--------|------|
| `tender-python-ai` | 2048M | 3G |
| `tender-cap-srv` | 512M | 512M |
| `tender-db-deployer` | 256M | 256M |

Python uses a single Gunicorn worker (FastEmbed model). Large PDF extraction can run 10+ minutes — upload timeout is 30 min on CAP → Python.

---

## 7. Re-extract / cache invalidation

Extraction results are cached at `python-ai-service/uploads/cache/<sha256>.json`.

Cache is invalidated when `EXTRACTION_PIPELINE_VERSION` changes (currently **5**).

After pipeline changes:

1. Restart Python service
2. Re-upload the tender (or delete tender — triggers full purge via `/purge_document`)

On CF, cache lives on the app filesystem (ephemeral). Restaging clears it.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `404` on upload | Python not running or wrong port | Start `npm run ai`; CAP expects `:8002` |
| `ECONNREFUSED` Python | `PYTHON_AI_URL` mismatch | Set env or use default `http://localhost:8002` |
| `502` on upload (dev) | Vite proxy timeout | Wait longer; proxy timeout is 10 min |
| DB connection error | Postgres down | `docker compose ps`; port `5433` |
| `cds deploy` fails | Schema not applied | `npx cds deploy --to postgres` in `cap-backend` |
| AI auth error | Bad AI Core creds | Check `TOKEN_URL`, client, deployment URL |
| CF Python OOM | Memory too low | Confirm 2G on `tender-python-ai` |
| pgvector error on CF | Extension missing | Confirm `postgresql-db` trial with `vector` in `mta.yaml` |
| Analytics `7/6` | Stale frontend | Hard refresh; CAP syncs from Python `/health` |

**Logs**

```bash
# Local — CAP + Python logs in their terminals

# CF
cf logs tender-cap-srv --recent
cf logs tender-python-ai --recent
```

---

## 9. Quick reference — ports & paths

| Path | Handler |
|------|---------|
| `/odata/v4/tender/*` | CAP OData |
| `POST /upload` | PDF upload → AI extraction |
| `POST /api/stream-chat` | Chat (SSE) |
| `GET /api/analytics/live` | Live extraction analytics |
| `POST /process_file` | Python — called by CAP only |
| `GET /health` | Python health |

---

## 10. Minimal daily dev checklist

```bash
# 1. Postgres
docker compose up -d

# 2. Three services (3 terminals)
npm run ai
npm run backend
npm run frontend

# 3. Open
# http://localhost:5173  (login: admin / admin)
```

For CF-only testing without local stack, deploy MTA once, set AI env vars, assign XSUAA roles, then use the `tender-cap-srv` route directly.
