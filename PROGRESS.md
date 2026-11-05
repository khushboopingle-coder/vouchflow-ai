# VouchFlow AI — Progress

## Live demo

- **App (dashboard):** https://vouchflow-ai-app.streamlit.app
- **API docs:** https://vouchflow-api.onrender.com/docs

The free servers sleep when idle, so the first load can take about a minute.

Follows `VOUCHFLOW_MASTER_PLAN.md` (Phases 2–7). One commit per phase.
**Continue from:** nothing left to build. Phases 2 to 7 are done and committed; the Phase 6 and Phase 7 commits still need `git push origin main`.


## Phase 1 — PostgreSQL (Neon) ✅ (commit `f22fdf6`)
- `DATABASE_URL` in `.env` → Neon; missing → local SQLite. psycopg v3, Alembic migrations.
- Tests are forced to local SQLite (`tests/conftest.py`).

## Phase 2 — Login and private workspaces ✅
**What was built**
- **Accounts:** sign up / log in with email + password on the dashboard (cream/chrome/brown
  login page, "Log in" and "Create account" tabs), **Log out** button. Passwords are stored
  only as **bcrypt** hashes (`backend/auth/passwords.py`). Wrong email and wrong password give
  the same answer ("Wrong email or password").
- **Workspaces:** every user gets one private workspace on signup. `workspace_id` on suppliers,
  contracts, purchase orders, GRNs, invoices, decisions (approvals) and audit logs. Line items,
  extractions, checks and investigation reports belong to the workspace of their parent invoice.
- **Every query is filtered by workspace:** all service functions require `workspace_id`
  (`workspace_service.require_invoice` → 404 for another workspace's invoice). The dashboard
  only calls services with the logged-in workspace. The API needs `Authorization: Bearer <token>`
  (from `POST /auth/login`, signed with `VOUCHFLOW_SECRET_KEY`, 12 h) → 401 otherwise.
- **Migration `0002`:** users + workspaces tables, workspace columns, workspace "sample" holding
  ALL existing data; PO and GRN numbers are now unique **per workspace**. Applied to the local
  SQLite file and to **Neon** (50 invoices + 6 reports now in "sample").
- **Sample data:** signup copies the sample data into the new workspace (checkbox, on by default),
  so new users never see an empty app. Sidebar → **Workspace tools → Load sample data** copies it
  again (asks for confirmation when the workspace already has data). Copying is atomic (all or
  nothing) and keeps every link (supplier → PO → GRN → invoice → line items → reports).
- **Sidebar** shows the logged-in email and workspace name.
- Matcher: duplicate check and PO-number lookup only look inside the invoice's own workspace
  (otherwise a user's copy of the sample would look like duplicates of the original).
- Agent audit rows are stamped with the investigated invoice's workspace.
- Seeder (`scripts/seed_db.py`) only touches the "sample" workspace, never users' workspaces.

**Decisions I made (reasonable defaults, change if you like)**
- Suppliers also got a `workspace_id` (not in the plan's list) — needed so a user's copied
  invoices point at their own suppliers.
- The dashboard no longer calls the FastAPI backend; it calls the same service functions
  directly with the logged-in workspace (one code path, easy to prove isolation). The API stays
  for scripts/automation and needs a login token.
- Logged in "during the session" = while the browser tab is open; reloading the page asks you
  to log in again (Streamlit session state).
- While logged out, every address (`/`, `/investigation`, `/approvals`, `/evals`) shows the
  login screen; after login the page you asked for opens.
- `workspace_id` columns allow NULL at database level so old/test rows keep working; the app
  always fills them.
- Copying sample data copies extractions, checks and investigation reports, but **not**
  decisions: a person must always decide again.

**Tests that prove it** (`tests/test_workspaces.py`, 31 tests)
- User A cannot read, check, investigate or approve user B's invoices — through the service
  layer (what the dashboard uses) and through every API route (404). Lists, queues, history and
  audit logs never mix workspaces.
- Edited token → 401; validly signed token for someone else's workspace → 401; no token → 401.
- Wrong password fails; passwords are bcrypt hashes; duplicate email / bad email / short
  password refused.
- The dashboard for an empty account shows none of A's 120 invoices.
- Clearing / deleting a workspace works with foreign keys enforced (like PostgreSQL).
- Logged-out visitors only see the login screen on every page (`tests/test_navigation.py`).

**How to test it yourself**
```
python -m pytest -q
python -m alembic upgrade head
streamlit run dashboard/app.py
```
Then: Create account (any email, password ≥ 8 characters) → you see 120 sample invoices and your
email + workspace in the sidebar → Log out → log in with a wrong password (error) → log in
correctly. A second account (untick "Start with sample data") sees an empty workspace.

API: `python -m uvicorn backend.main:app --reload`, then in http://127.0.0.1:8000/docs use
`POST /auth/signup` or `POST /auth/login`, click **Authorize**, paste the `access_token`.

---

## Phase 3 — Bring your own data, and fair AI limits ✅
**What was built**
- **My data page** (sidebar menu): tabs for Invoices (PDF/PNG/JPG, several at once), Purchase
  orders (CSV), Goods received (CSV), Contract prices (CSV), Contract documents (TXT/PDF).
  Each CSV tab has a **Download template** button. All files go into the user's own workspace.
- **Clear errors:** wrong type, empty file, fake file (content does not match the extension),
  too large (>10 MB), missing CSV columns, bad dates/numbers/quantities, unknown PO in a GRN,
  duplicate PO/GRN numbers. CSV imports are all-or-nothing and list every problem with its
  row number (first 25 shown). PO/GRN numbers may repeat across different workspaces.
- **Files** live in git-ignored `data/workspaces/<id>/` (invoices and contracts). The contract
  search index is kept in memory and rebuilt on first use (no locked files on Windows).
- **Contract search per workspace:** each workspace gets its own Chroma index. A user's uploaded
  contracts are searchable only by them; the sample contracts are included only while the
  workspace holds the sample data; an empty workspace finds nothing. The shared "sample"
  index and the evals are unchanged. The Investigation Agent searches the invoice's own workspace.
- **Demo vs Live:** the banner and the sidebar badge say "Demo data" only while the workspace
  holds the sample copy and nothing else. Any upload, or an empty workspace, shows
  "Live workspace" (no banner).
- **AI limits:** the explanation is the template (`llm_used=False`) by default. On the
  Investigation page a checkbox "Use AI explanation (Gemini) - N of 5 left today" (disabled when
  there is no key or no quota left). Only explanations Gemini really wrote are counted in the
  new `ai_usage` table; a Gemini failure or the limit silently gives the template.
  API: `POST /invoices/{id}/investigate?use_ai=true`.
- **Workspace tools** (sidebar): Load sample data (empty workspace) / **Reset to sample data**
  (tick to confirm) and **Delete my workspace** (type DELETE; removes data, files, index and
  the login account, then logs out).
- Migration `0003` (workspace flags, `ai_usage`); applied to local SQLite and Neon.

**Decisions I made**
- Reading an uploaded invoice with Gemini ("Read with AI") also counts against the 5 daily AI
  actions, because it is a real Gemini call; without a key it is simply unavailable.
- Contract prices uploaded as CSV feed the price check; contract documents (TXT/PDF) feed the
  contract search - two separate things, as in the sample data.
- Scanned (image-only) PDFs cannot be used as contract documents - they have no text to search.
- Evals and the shared sample index keep using the original code path on purpose.

**Tests:** `tests/test_uploads.py`, `tests/test_contract_search_workspaces.py`,
`tests/test_ai_limits.py` (Gemini is faked; never really called).

**How to test it yourself**
```
python -m pytest -q
streamlit run dashboard/app.py
```
Create an account (untick "Start with sample data") -> badge says "Live workspace" -> **My data**:
download the three CSV templates and upload them -> upload a PDF invoice -> upload a contract
.txt with a supplier name -> Investigation page shows the AI checkbox. A second account never sees
these. Sidebar -> Workspace tools -> Reset to sample data / Delete my workspace.

## Phase 4 - Ingest API for automation ✅
**What was built**
- **Settings page** (sidebar menu): create an API key with a name, see it **once**, list keys
  (name, first characters, created, last used, active/revoked), **Revoke**. Up to 10 active keys per workspace.
- **Keys are safe:** format `vf_<random>`; only the **SHA-256 hash** is stored (never the key); the key identifies
  exactly ONE workspace, so n8n can only reach that workspace's data. Header: `X-API-Key`.
- **`POST /api/invoices/ingest`** (file upload): saves the file into the key's workspace -> reads it with Gemini
  (if the server has a key) -> fills the invoice row (number, dates, totals, line items, supplier/PO if they exist
  in that workspace) -> 3-way match -> Investigation Agent (template explanation, no AI quota) -> JSON:
  `invoice_id, invoice_number, supplier_name, grand_total, status, mistakes, difference_amount,
  recommended_action, extraction_ok, dashboard_link, human_approval_required (always true), message, text`.
  `text` is a ready-to-send alert message (for the Telegram step in n8n).
- **`GET /api/invoices/{id}/summary`**: the same short summary for an invoice already in the workspace (404 for
  another workspace's invoice).
- **Rate limit:** 20 calls per minute per key (`INGEST_RATE_LIMIT_PER_MINUTE`), answer 429 + `Retry-After`.
- **401** for a missing, wrong, revoked or malformed key. A login token does not work on `/api/...` and an
  API key does not work on the dashboard routes.
- **Never auto-approves:** ingest creates no decision; every answer says a person must approve in the dashboard.
- Dashboard links look like `<DASHBOARD_URL>/investigation?invoice=<id>`; the Investigation page opens that invoice.
- Migration `0004` (`api_keys`) applied to local SQLite and Neon.
- `init_db()` now runs the Alembic migrations for a SQLite file that Alembic already manages (so a new migration
  never clashes with tables created by hand); a brand-new SQLite file still uses `create_all`.

**Decisions I made**
- Ingest uses the **template** explanation always: an automation must not spend anyone's Gemini quota on explanations.
  Reading the invoice (extraction) does use Gemini if the server has a key; it is limited only by the per-key rate limit.
  (A daily cap per workspace would be a sensible next step.)
- Without a Gemini key on the server the invoice is still saved, matched and investigated, but lands in
  `needs_review` with `extraction_ok: false` - honest instead of guessing.
- A vendor name found by extraction is only linked to a supplier that already exists in the workspace (no junk
  suppliers are created from misread names).
- The rate-limit counters are in memory (one server process). Fine for the free tier; use Redis if you scale out.
- `DASHBOARD_URL` (default `http://localhost:8501`) must be set to the public dashboard address for useful links.

**Tests:** `tests/test_ingest_api.py` (20 tests; Gemini faked): hash-only storage, 401s, revoked keys, no cross-workspace
access (keys and summaries), token/key not interchangeable, JSON shape, never approves, 400 for bad files, 429,
Settings page create-once/revoke.

**How to test it yourself**
```
python -m uvicorn backend.main:app --reload
streamlit run dashboard/app.py
```
Dashboard -> Settings -> create a key and copy it. Then (PowerShell):
```
curl.exe -X POST "http://127.0.0.1:8000/api/invoices/ingest" -H "X-API-Key: PASTE_KEY_HERE" -F "file=@data/invoices/INV_001.pdf"
```
Wrong key -> 401. Open the returned `dashboard_link` after logging in. Interactive docs: http://127.0.0.1:8000/docs.

## Phase 5 - n8n automation ✅ (files and guide; see "not machine-tested" below)
**What was built (folder `n8n/`)**
- `invoice_workflow.json` - **Gmail Trigger** (new email with attachment) -> **Settings** (API address + Telegram chat id)
  -> **Split attachments** (only PDF/images, one item each) -> **VouchFlow ingest** (HTTP POST to `/api/invoices/ingest`,
  `X-API-Key` from an n8n *Header Auth* credential) -> **IF** status is `mismatch_detected` or `needs_review`
  -> **Telegram: problem found** (supplier, amount, problems, recommended action, dashboard link), otherwise
  **Telegram: verified** (short message). If the API refuses the file (401 wrong key, 429 too many calls,
  400 bad file) a third **Telegram: ingest failed** message says why.
- `webhook_workflow.json` - the simpler one: **Webhook** (POST, multipart file) -> ingest -> **Respond to Webhook** with
  the VouchFlow JSON (or a 502 error JSON). No Gmail, no Telegram; only the API-key credential is needed.
- `n8n/README.md` - beginner guide: start VouchFlow, create an API key, install/start n8n (`npx n8n`, localhost:5678),
  import the webhook workflow, create the Header Auth credential, test with `curl.exe`, then the Telegram bot
  (BotFather, chat id) and Gmail credentials, activating, troubleshooting table, safety notes.
- `data/samples/sample_invoice_clean.pdf` and `sample_invoice_price_mismatch.pdf` (fake; made by
  `python scripts/make_sample_invoices.py`). They match the CSV templates on the My data page (Acme Office Supplies,
  PO-1001), so the whole demo works from an empty workspace.
- **No secrets in the workflow files:** the key and the bot token are n8n *credentials* referenced by name only
  (a test scans for key/token patterns and credential ids). Workflows are exported inactive.

**Tests:** `tests/test_n8n_workflows.py` (10: valid JSON, unique node ids/names, every connection points at a real node,
correct flow, key via credential, no secrets), `tests/test_sample_invoices.py` (3: the PDFs contain the expected numbers;
the full demo story runs offline with the reader faked: clean invoice -> `verified`, other -> `price_mismatch`).

**Not machine-tested (please do this once):** I could not import the JSON into a real n8n here (it needs downloading n8n
with `npx`, which was not allowed in this environment), and I cannot log in to Gmail/Telegram for you. So the files are
checked for structure and secrets only. If n8n shows a small warning on import (node version, missing credential), pick
your credential in the node and save. Test the **webhook workflow first**; it needs the fewest pieces.

**Decisions I made**
- The two settings you may need to edit (API address, Telegram chat id) sit in one **Settings** node, not in code.
- The Code node reads attachments from the trigger node by name, so each PDF/image becomes its own item.
- Verified invoices also send a Telegram message (short), as the plan asked, and still say a person must approve.

**How to test it yourself:** follow `n8n/README.md` Part 1-3 (about 10 minutes, no Gmail needed).

## Phase 6 - Deployment preparation ✅
**What was built (all code and config; nothing is deployed for you)**
- `Dockerfile` (python 3.12-slim, runs as a normal user), `.dockerignore` (keeps `.env`, secrets, databases and uploads out),
  `docker-compose.yml`: **api** (8000), **dashboard** (8501), **n8n** (5678), health checks, the dashboard waits for the API,
  data in dedicated volumes (`/app/db`, `/app/data/workspaces`; the sample data is never hidden under a volume).
  No secrets in the file: everything comes from `.env`.
- `.env.example` lists **every** setting with comments; the secret/API-key lines are **empty** on purpose.
- `render.yaml` for the API: build `pip install -r requirements.txt`, start `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT`,
  health check `/health`, Python 3.12.8, `DATABASE_URL` and `GEMINI_API_KEY` typed in on Render (`sync: false`),
  `VOUCHFLOW_SECRET_KEY` generated by Render.
- `.streamlit/secrets.toml.example` (all names; secret values empty) and `.streamlit/config.toml` (theme, 10 MB uploads).
  Streamlit Cloud: main file `dashboard/app.py`, Python 3.12, `requirements.txt` pinned.
- **Startup check** (`backend/startup_check.py`): the API and the dashboard print which variable is missing or unsafe, by name.
  In `ENVIRONMENT=production` the app refuses to start without a real `DATABASE_URL` (not SQLite) and a `VOUCHFLOW_SECRET_KEY`
  of at least 32 characters, and says what to do. Other problems are warnings.
- `DEPLOY.md`: numbered steps with the exact values for Neon, Render, Streamlit Cloud, n8n, Docker, a pre-flight checklist and
  free-tier notes.
- **Memory check:** the API process peaked at about **266 MB** after a full investigation (ChromaDB + embeddings included), inside
  Render's 512 MB free limit, so **no lighter replacement was needed**. Safeguards: per-workspace contract indexes are in memory,
  capped at 20 (least recently used are dropped), and query embeddings are cached. The first investigation after a restart
  downloads a ~80 MB embedding model once.

**Fixed while reviewing the work of the other tool (Antigravity)**
- Removed leftover debug prints (`>>> STARTUP CHECK DONE ...`) from `backend/main.py`.
- **Placeholder secrets:** the example files used a placeholder that was long enough to pass the startup check, which would
  have left a publicly known signing key in production. The examples are now empty, and placeholder text (`replace_with...`,
  `your_gemini_api_key_here`, ...) counts as "not set" in `backend/config.py`.
- Its blanket "fake Gemini client" test fixture silently replaced the clients that individual reader tests set up; replaced by a clean
  guard (see below). Docker: shared volume hid the sample data after a rebuild; no dashboard health check; ran as root.
  `DEPLOY.md`: an n8n step would have doubled the URL path; "Neon stores vectors" was wrong (the index is in memory);
  `SCREENSHOT_CHECKLIST.md` described screens that do not exist (rewritten from the real app).

**Tests never call the real Gemini, and are fast**
- `tests/conftest.py` blanks the real key before anything loads, makes any attempt to create a real Gemini client fail with a clear
  message, removes retry sleeps, and uses a tiny fake embedding for per-workspace indexes (the shared sample index keeps the real
  model, so the contract-search evaluation tests still test the real thing).
- `pytest.ini`: 90-second timeout per test (a hang is reported, not endless) and quieter warnings; `pytest-timeout` is in `requirements.txt`.
- Speed-ups: copying the sample data is now one batch per table (also makes signup faster), query embeddings are cached,
  the 20-invoice agent evaluation runs once instead of twice, subprocess tests start Python once, bcrypt uses the minimum rounds in tests only.
  The whole suite went from about **16 minutes to about 2.5 minutes** (see the number at the top of this file's checklist).
- **Sample invoices fixed:** `data/samples/sample_invoice_clean.pdf` / `sample_invoice_price_mismatch.pdf` now reuse a real sample
  order (Patel Enterprises, PO-2026-0002), so in a workspace with sample data the second one shows **price_mismatch, not missing_po**
  (11 desks x Rs. 600 + 18 % GST = Rs. 7,788). The Acme-based ones are now `template_invoice_*.pdf` (for the CSV templates).
  `scripts/make_sample_invoices.py` reads the real sample order, and a test checks the PDFs stay in sync.

**Not machine-tested:** Docker is not installed on this computer, so `Dockerfile` and `docker-compose.yml` were never built or run;
they are checked by tests only for structure and safety. Render and Streamlit Cloud were not touched (they need your accounts).
Please run `docker compose up --build` once and tell me what breaks.

## Phase 7 - README, evals and portfolio polish ✅
- `README.md` rewritten: what it does, **Mermaid architecture diagram**, the full flow (email -> n8n -> API -> agent -> alert ->
  human approval) as a sequence diagram, how to run locally, how to use it, tech stack, **Results table with the real numbers**,
  **Limitations**, **Security**, **Next steps**, project layout.
- **Honest numbers:** invoice reader = 44 of 44 real Gemini reads correct (the saved file's "47/48" mixes in 3 mock rows and 1 unread
  invoice); matcher 50/50 + 40/40 + 30/30; contract search 15/15; agent 20/20 with **template** explanations only (150 claims, 0 ungrounded).
  Limitations say plainly: generated data, same author for code and tests, free-tier AI limits, not tested on many real invoices.
- `docs/SCREENSHOT_CHECKLIST.md`: screenshots that really exist in the app, plus the **2-minute demo script**.

## What is left (for you)
0. **Push to GitHub:** the Phase 6 and Phase 7 commits exist only on this computer (the push was blocked). Run `git push origin main` when you are happy.
1. **Take the screenshots** (checklist) and record the demo; add the best images to the README.
2. **Run `docker compose up --build`** once (Docker was not available here) and the **webhook workflow in n8n** (see `n8n/README.md`).
3. **Deploy** following `DEPLOY.md` (Render for the API, Streamlit Cloud for the dashboard): creating accounts and typing secrets is yours to do.
4. Optional: put your Gemini key in the API's environment to read invoices by AI; re-run the evaluation scripts if you change the matcher.
5. Neon contains a real user account (`alex@gmail.com`, a signup made on the live app) - left untouched.

## Final acceptance checklist
- [x] Two different users cannot see each other's data (tests prove it)
- [x] Sample data loads in one click; the Demo banner shows only on sample
- [x] User can upload their own invoice, PO, GRN and contract
- [x] Ingest API works with an API key; wrong key gives 401
- [x] n8n workflow files and README are in the repo (import into real n8n still to be tried by you)
- [x] Docker and DEPLOY.md are ready (Docker itself not built here)
- [x] pytest passes (285 tests, about 2 minutes: pytest reports 1:56; Gemini always mocked; the real database is never touched)
- [x] No secrets in git: all 16 commits scanned for key/token/link patterns, and for the literal Gemini key and Neon link/password from `.env` (none found); no `.env`, secrets file, database or upload is tracked
- [x] README has real numbers and honest limits
