# VouchFlow AI — Progress

Follows `VOUCHFLOW_MASTER_PLAN.md` (Phases 2–7). One commit per phase.
**Continue from:** Phase 3 (Phase 2 is done and pushed).

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

## What is left
- **Phase 3** — upload own invoices / PO + GRN CSV / contracts, per-workspace contract search,
  "Demo data" vs "Live workspace", 5 Gemini explanations per user per day, reset/delete workspace.
- **Phase 4** — ingest API with workspace API keys (Settings page), summary endpoint, rate limit.
- **Phase 5** — n8n workflows (Gmail + webhook), beginner n8n README, sample invoice.
- **Phase 6** — Docker, docker-compose, render.yaml, secrets example, startup check, DEPLOY.md.
- **Phase 7** — README with real eval numbers, limitations, security, screenshots checklist.

## Final acceptance checklist
- [x] Two different users cannot see each other's data (tests prove it)
- [ ] Sample data loads in one click; the Demo banner shows only on sample (banner rule: Phase 3)
- [ ] User can upload their own invoice, PO, GRN and contract
- [ ] Ingest API works with an API key; wrong key gives 401
- [ ] n8n workflow files and README are in the repo
- [ ] Docker and DEPLOY.md are ready
- [x] pytest passes (187 tests)
- [ ] No secrets in git (checked before every commit; final check in Phase 7)
- [ ] README has real numbers and honest limits
