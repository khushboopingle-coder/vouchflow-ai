# VouchFlow AI — Deployment Guide

## Live demo

- **App (dashboard):** https://vouchflow-ai-app.streamlit.app
- **API docs:** https://vouchflow-api.onrender.com/docs

The free servers sleep when idle, so the first load can take about a minute.

This guide explains how to deploy VouchFlow AI to production across **Neon PostgreSQL**, **Render** (FastAPI backend), **Streamlit Community Cloud** (Dashboard frontend), and **n8n** (Automated workflow orchestration).

---

## Architecture Overview

```
                                      +-------------------------------+
                                      |   Gmail / Webhook Ingestion   |
                                      +---------------+---------------+
                                                      |
                                                      v
                                      +---------------+---------------+
                                      |         n8n Automation        |
                                      | (Header Auth: X-API-Key: vf_) |
                                      +-------+---------------+-------+
                                              |               |
               POST /api/invoices/ingest      |               | Telegram Alerts
                                              v               v
+-----------------------------+       +-------+---------------+       +-------------------------------+
|  Streamlit Community Cloud  |       |     Render Web Service        |       Telegram Bot Chat       |
|    (Dashboard Frontend)     |       |      (FastAPI Backend)        |  (Discrepancies & Deep-links) |
+--------------+--------------+       +---------------+---------------+       +-------------------------------+
               |                                      |
               |                                      |
               +------------------+-------------------+
                                  |
                                  v
                   +--------------+---------------+
                   |       Neon PostgreSQL        |
                   | (users, workspaces, invoices)|
                   +------------------------------+
```

| Component | Host / Runtime | Key Config | Port / Protocol |
| :--- | :--- | :--- | :--- |
| **Database** | Neon PostgreSQL (Serverless) | `DATABASE_URL` with `?sslmode=require` | 5432 (SSL) |
| **API Backend** | Render Web Service (Python 3.12) | `render.yaml` or Docker | `$PORT` (8000) |
| **Dashboard** | Streamlit Community Cloud | `dashboard/app.py`, Python 3.12 | 8501 (HTTPS) |
| **Automation** | n8n (Docker / Cloud / Self-hosted) | Workflows in `n8n/` | 5678 (HTTP) |

---

## 1. Database: Neon PostgreSQL

VouchFlow uses PostgreSQL for durable multi-tenant data storage with workspace isolation.

### Step 1.1: Create a Neon Project
1. Log in to [Neon](https://console.neon.tech/).
2. Create a new project (e.g., `vouchflow-prod`).
3. Select your preferred region (e.g., AWS Oregon `us-west-2` or Frankfurt `eu-central-1`).
4. Copy the connection string. Ensure it uses `sslmode=require`, for example:
   ```text
   postgresql://user:password@ep-xyz-pooler.region.aws.neon.tech/neondb?sslmode=require
   ```

### Step 1.2: Run Database Migrations
Run Alembic migrations against your Neon database from your local machine or build pipeline:
```powershell
# Set DATABASE_URL in your terminal or .env
$env:DATABASE_URL="postgresql://user:password@ep-xyz-pooler.region.aws.neon.tech/neondb?sslmode=require"
python -m alembic upgrade head
```
All tables, multi-tenant workspace columns, indexes, and constraints will be applied automatically.

### Step 1.3: Seed Initial Demo Data (Optional)
To pre-populate the shared "sample" workspace with benchmark invoices, purchase orders, goods receipts, and master contracts:
```bash
python scripts/seed_db.py --demo-runs
```

---

## 2. Backend API: Render

The FastAPI backend runs with Uvicorn. Memory usage peaks at ~266 MB during investigation (safely within Render's 512 MB free tier).

### Option A: Deploy via Blueprint (`render.yaml`)
1. Fork or push the repository to GitHub.
2. In the Render Dashboard, click **New +** -> **Blueprint**.
3. Connect your repository. Render reads `render.yaml` automatically:
   - **Runtime**: Python 3.12.8
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`
4. When prompted, fill in the environment variables:
   - `DATABASE_URL`: Your Neon PostgreSQL connection URL.
   - `GEMINI_API_KEY`: Your Google AI Studio API key.
   - `DASHBOARD_URL`: Your public dashboard URL (e.g. `https://your-dashboard.streamlit.app`).
   - `VOUCHFLOW_SECRET_KEY`: Auto-generated or custom 32+ character random secret.

### Option B: Manual Web Service Setup
1. Click **New +** -> **Web Service**.
2. Connect your repo and select **Python** environment.
3. Configure settings:
   - **Region**: Same or close to your Neon database region.
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`
4. Add Environment Variables under **Environment**:
   - `PYTHON_VERSION`: `3.12.8`
   - `ENVIRONMENT`: `production`
   - `DATABASE_URL`: `postgresql://user:password@ep-xyz-pooler.region.aws.neon.tech/neondb?sslmode=require`
   - `VOUCHFLOW_SECRET_KEY`: `<minimum 32 random characters>`
   - `GEMINI_API_KEY`: `<your Gemini API key>`
   - `DASHBOARD_URL`: `https://your-dashboard.streamlit.app`
   - `INGEST_RATE_LIMIT_PER_MINUTE`: `20`
   - `ROUNDING_TOLERANCE_RS`: `1.00`
   - `EMBEDDING_PROVIDER`: `local`

---

## 3. Frontend Dashboard: Streamlit Community Cloud

Streamlit Community Cloud hosts the user-facing web dashboard.

### Step 3.1: Deploy App
1. Go to [share.streamlit.io](https://share.streamlit.io/).
2. Click **Create app** and select your GitHub repository.
3. Configuration:
   - **Main file path**: `dashboard/app.py`
   - **App URL**: Choose a custom subdomain (e.g., `vouchflow.streamlit.app`).
   - **Python Version**: `3.12`

### Step 3.2: Configure Secrets
In your app's dashboard on Streamlit Cloud, go to **App Settings** -> **Secrets**. Copy and populate the contents from `.streamlit/secrets.toml.example`:

```toml
DATABASE_URL = "postgresql://user:password@ep-xyz-pooler.region.aws.neon.tech/neondb?sslmode=require"
VOUCHFLOW_SECRET_KEY = "your-long-random-secret-key-at-least-32-chars"
GEMINI_API_KEY = "AIzaSy..."
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_MODEL_LIST = "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite"
DASHBOARD_URL = "https://your-app.streamlit.app"
ENVIRONMENT = "production"
DATA_DIR = "./data"
```

> **Note on Startup Check**:
> If any required production variable is missing (such as `DATABASE_URL` pointing to SQLite in production, or `VOUCHFLOW_SECRET_KEY` missing), the dashboard displays a clean red configuration alert naming the exact variable and halts execution gracefully.

---

## 4. Automation: n8n Integration

VouchFlow provides turnkey n8n workflows in the `n8n/` directory.

### Step 4.1: Deploy n8n
You can run n8n locally, on cloud hosting, or via Docker Compose:
```bash
docker compose up -d n8n
```
Open `http://localhost:5678` in your browser.

### Step 4.2: Set Up Credentials in n8n
1. In the VouchFlow dashboard, log in and open the **Settings** page.
2. Type a name, click **Create key**, and copy the key that appears (it starts with `vf_` and is shown **only once**).
3. In n8n, go to **Credentials** -> **Create credential** -> **Header Auth**.
4. Fill in the two fields and save it as `VouchFlow API key`:
   - **Name**: `X-API-Key`
   - **Value**: `<your vf_... key>`

### Step 4.3: Import Workflows
- **Webhook Workflow (`n8n/webhook_workflow.json`)**:
  Import this workflow for testing direct invoice ingestion without Gmail.
- **Email & Telegram Workflow (`n8n/invoice_workflow.json`)**:
  Triggers on new Gmail attachments, checks them against VouchFlow, and routes mismatch alerts to your Telegram chat.
  - Edit the **Settings** node of the workflow: `api_base_url` is the API address **without** a path (the workflow adds `/api/invoices/ingest` itself).
  - In Docker Compose use `http://api:8000`. With Render use `https://your-api.onrender.com`.
  - See `n8n/README.md` for the full beginner guide (Telegram bot, Gmail login, testing).

---

## 5. Docker Full-Stack Deployment

To run the entire stack locally or on a single VPS using Docker:

```bash
# 1. Copy and customize configuration
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env

# 2. Build and start containers
docker compose up -d --build

# 3. Check logs
docker compose logs -f
```

Containers:
- `vouchflow-api`: FastAPI backend on `http://localhost:8000`
- `vouchflow-dashboard`: Streamlit UI on `http://localhost:8501`
- `vouchflow-n8n`: n8n Workflow Automation on `http://localhost:5678` (internally communicates with `http://api:8000`)

---

## 6. Pre-Flight Production Checklist

Before going live with real accounting data:

- [ ] **Database Connection**: `DATABASE_URL` points to Neon PostgreSQL with `?sslmode=require`. No SQLite is used in production.
- [ ] **Alembic Version**: `alembic upgrade head` executed; database schema matches current models.
- [ ] **Secret Key**: `VOUCHFLOW_SECRET_KEY` is at least 32 random characters long and kept confidential.
- [ ] **Gemini API Key**: `GEMINI_API_KEY` is set in Render and Streamlit secrets.
- [ ] **Public Dashboard Link**: `DASHBOARD_URL` matches the public dashboard domain so links in Telegram/Slack alerts route directly to invoice investigations.
- [ ] **Ingest Rate Limit**: `INGEST_RATE_LIMIT_PER_MINUTE` is appropriately set (default 20).
- [ ] **Health Endpoint**: `GET /health` returns `{"status": "ok"}` with HTTP 200.
- [ ] **Startup Verification**: Startup checks pass without production errors.
- [ ] **Secret Scan**: Git repository history contains no leaked passwords, API keys, or connection strings (`git status`, secret scanner).


---

## 7. Good to know (free tiers)

- **Render free sleeps** after ~15 minutes without traffic; the first call afterwards takes about a minute to wake up.
  n8n's HTTP node waits up to 3 minutes, so this is fine.
- **First investigation after a restart** downloads a small embedding model (~80 MB) once; it can take a few extra seconds.
- **Memory:** the API peaked at about **266 MB** after a full investigation (measured), inside Render's 512 MB free limit.
  Keep a **single** server process (the default) - the rate-limit counters live in that process.
- **Neon** pauses an idle database and wakes it on the next call (a short delay). Use the *pooled* connection string.
- **Streamlit Cloud:** the Python version (3.12) can only be chosen when you create the app; to change it, delete and recreate the app.
  Secrets are edited under *Settings -> Secrets* and need an app reboot.
- **The same `DATABASE_URL`** goes to both Render and Streamlit Cloud: they share one database. The dashboard talks to the
  database directly; the Render API exists for automation (n8n).
- **Never** paste real keys into files in the repository. Use Render's *Environment* page and Streamlit's *Secrets*.
