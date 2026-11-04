# VouchFlow AI — Progress

Follows `VOUCHFLOW_MASTER_PLAN.md` (Phases 2–7). One commit per phase.
**Continue from:** Phase 5 (Phases 2, 3 and 4 are done and pushed).

---

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

## What is left
- **Phase 5** — n8n workflows (Gmail + webhook), beginner n8n README, sample invoice.
- **Phase 6** — Docker, docker-compose, render.yaml, secrets example, startup check, DEPLOY.md.
- **Phase 7** — README with real eval numbers, limitations, security, screenshots checklist.

## Final acceptance checklist
- [x] Two different users cannot see each other's data (tests prove it)
- [x] Sample data loads in one click; the Demo banner shows only on sample
- [x] User can upload their own invoice, PO, GRN and contract
- [x] Ingest API works with an API key; wrong key gives 401
- [ ] n8n workflow files and README are in the repo
- [ ] Docker and DEPLOY.md are ready
- [x] pytest passes (187 tests)
- [ ] No secrets in git (checked before every commit; final check in Phase 7)
- [ ] README has real numbers and honest limits
