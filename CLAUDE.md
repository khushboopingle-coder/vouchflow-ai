# VouchFlow AI — notes for Claude

AI finance assistant for Accounts Payable. It reads supplier invoice PDFs, checks them
against purchase orders (PO), goods received notes (GRN) and supplier contracts
(3-way matching), and flags mistakes. **A human always approves** — the agent only advises.

## Owner's rules (always follow)
- The user is a beginner: explain in simple words.
- Show a short plan and **wait for OK** before changing anything.
- Give complete files, not fragments.
- **Never change ground truth files** (`data/evaluation/*ground_truth*.csv`).
- **Never print the API key** (`GEMINI_API_KEY` in `.env`; do not `cat .env`).
- Keep `python -m pytest -q` passing.

## Tech
- Python 3.14, FastAPI + SQLAlchemy 2 + Pydantic v2
- Database: PostgreSQL on Neon via `DATABASE_URL` in `.env` (secret: never print, never
  commit). Missing -> local SQLite `vouchflow.db` (gitignored). Driver: psycopg v3;
  `settings.database_url` adds `+psycopg`. Migrations: Alembic (`alembic.ini`, `migrations/`)
- Streamlit dashboard
- Gemini via `google-genai` directly (automatic model switching via `GEMINI_MODEL_LIST`)
- Contract search (RAG): LangChain `Chroma` wrapper (from `langchain_community`) + ChromaDB,
  local ONNX MiniLM embeddings, stored in `data/chroma_db/`
- Investigation Agent: LangGraph `StateGraph`

## Folders
- `backend/main.py` — FastAPI routes: health, invoices list/detail/upload, extract, check,
  audit-logs, investigate/investigation, and Phase 8 approvals:
  `POST /invoices/{id}/decision`, `GET /approvals/queue`, `GET /approvals/decisions`
- `backend/config.py` — settings from `.env`; `database_url`, `is_sqlite`, `database_kind`
- `backend/database/db.py` — engine; `init_db()`: SQLite -> create_all, PostgreSQL -> Alembic upgrade
- `migrations/versions/` — `0001` all 13 tables; `0002` users + workspaces (+ "sample");
  `0003` workspace flags (sample_loaded, has_user_data) + `ai_usage`
- `backend/auth/` — bcrypt `passwords.py`, signed API `tokens.py` (VOUCHFLOW_SECRET_KEY),
  `dependencies.py` (`current_account`: Bearer token -> 401)
- `backend/services/upload_service.py` (Phase 3: validated uploads + all-or-nothing CSV imports,
  files in git-ignored `data/workspaces/<id>/`), `ai_usage_service.py` (5 Gemini explanations/user/day;
  default explanation is the template), `auth_service.py` (signup/login), `workspace_service.py`
  (`require_invoice` gate, sample workspace, load/clear/delete workspace data)
- `backend/database/` — `db.py` (engine/session), `models.py` (tables), `schemas.py` (Pydantic)
- `backend/services/invoice_service.py` — business logic + audit logging
- `backend/services/approval_service.py` — HUMAN approve/reject rules: software names
  (agent/system/n8n/bot...) refused, investigation required, note required for reject or
  for approving against agent advice, one decision per report, audit-logged.
  Table `invoice_decisions`. Does NOT change `invoices.status`.
- `backend/tools/` — `invoice_reader.py` (pdfplumber + Gemini), `matcher.py` (rule-based,
  no LLM), `contract_finder.py` (RAG), `embeddings.py`
- `backend/agent/` — `graph.py` (LangGraph nodes), `state.py`, `tools.py`
- `backend/guardrails/` — `grounding.py`, `permissions.py`, `injection.py`
- `dashboard/app.py` — entry point / router (Streamlit Cloud main file): `st.navigation`
  (hidden) + own sidebar menu via `st.page_link`; Home, Investigation, Approvals, Evals
- `dashboard/home.py` — Home page: KPI cards, invoice ledger, invoice inspection
- `dashboard/views/data.py` — "My data": uploads + CSV templates (Phase 3)
- `dashboard/views/login.py` — `render()` login/signup screen (router shows it for every URL
  while logged out)
- `.streamlit/config.toml` — light theme + DM Sans font; colours must equal `ui_common.PALETTE`
  (checked by `tests/test_theme.py`)
- `dashboard/views/` — `investigation.py`, `approvals.py`, `evals.py` (Evals is read-only).
  NOT named `pages/`: Streamlit's auto-multipage folder would hide the router's sidebar/banner
- `dashboard/ui_common.py` — shared helpers: API first, falls back to services on local DB; `PALETTE` (the ONLY place with colours — no hex codes in other dashboard files),
  `apply_global_css()` (called once at the top of app.py, home.py and each page),
  sidebar brand/menu, demo banner, status pills, `render_html_table` (invoice ledger).
  app.py reloads `ui_common`/`demo_setup` when their files change (Streamlit keeps old
  helper modules in memory otherwise -> "has no attribute" errors after an update)
- `dashboard/demo_setup.py` — demo start-up (Streamlit Cloud): copies Gemini secrets to env,
  seeds an EMPTY database from `mock_data.json` (invoices 1–50), checks + investigates
  6 demo invoices (extraction only if a key exists). Never runs the generator scripts
  (they rewrite ground truth). Called from `app.py` and `ui_common.apply_page_style`.
- `data/` — `invoices/` (PDFs), `contracts/` (8 txt), `evaluation/` (ground truth + results CSVs)
- `scripts/` — data generation, DB seeding, eval scripts
- `tests/` — pytest suite (Gemini is mocked, runs offline)
- `docs/architecture.md`

## Commands (Windows, run from project root)
```
pip install -r requirements.txt
python scripts/generate_data.py          # fake invoices, contracts, ground truth
python -m alembic upgrade head           # create/update tables (uses DATABASE_URL)
python scripts/seed_db.py --demo-runs    # fill DB + 6 demo investigations (--force to wipe PG)
python -m uvicorn backend.main:app --reload   # API at http://127.0.0.1:8000
streamlit run dashboard/app.py           # dashboard
python -m pytest -q                      # tests
python scripts/run_extraction_eval.py    # evals: also run_matching_eval, run_contract_rag_eval,
python scripts/run_agent_eval.py         #        eval_hard_v2
```

## Deploy (Streamlit Community Cloud)
- Main file path: `dashboard/app.py` · Python 3.12 · `requirements.txt` is pinned
- No API, no .env, no key needed (agent uses template explanation). Optional key:
  add `GEMINI_API_KEY` in the app's Secrets (visitors would then use that quota).
- Cloud DB is temporary; it re-seeds itself after a restart. Peak memory ~470 MB locally.

## Phases
- Done: Foundation, Phase 1 reader, Phases 2–3 checker, Phase 4 contract search,
  Phase 5 agent with guardrails and evals (agent 20/20 on test set),
  Phase 8 dashboard pages (Investigation, Approvals, Evals) + approvals backend.
- Master plan (VOUCHFLOW_MASTER_PLAN.md): Phases 2 (login + workspaces) and 3 (own data + AI limits) DONE; see PROGRESS.md.
- Pending idea (not done, needs OK): switch `langchain_community.vectorstores.Chroma`
  to `langchain_chroma` package.

## Notes
- WORKSPACES (Phase 2): every service function takes `workspace_id`; never query invoices,
  POs, GRNs, contracts, suppliers, decisions or audit logs without it. The dashboard calls
  services directly with `ui.workspace_id()`; the API uses `current_account`.
- Tests: `tests/helpers.py::temp_user()` gives a throw-away user with a sample copy
  (`user.ids[1]` = their copy of sample invoice 1); `api_user` fixture in conftest.
- Contract search per workspace: `ask_contract(..., workspace_id=)`; user workspaces get an IN-MEMORY
  Chroma index (sample contracts only if `sample_loaded`, plus their own uploads). Demo banner/badge only
  when `workspace_service.is_demo(ws)`.
- PROGRESS.md tracks the master plan (Phases 2-7) and where to continue.
- `.env` has TWO `DATABASE_URL` lines (line 2 SQLite, line 8 Neon); the last one wins -> Neon.
- Tests are forced to SQLite by `tests/conftest.py` (set `TEST_DATABASE_URL` to override).
- After changing models: `python -m alembic revision --autogenerate -m "..."`, review it,
  `python -m alembic upgrade head`; `tests/test_database_config.py` runs `alembic check`.
- Local `vouchflow.db` is stamped at Alembic head (has an `alembic_version` table).
- Neon holds 50 invoices + 6 demo investigations (seeded without the Gemini key).
- Tests use the real `vouchflow.db`; tests that create rows should delete them afterwards
  (see `tests/test_approvals.py`). A test run rewrites `data/chroma_db/*.bin` and the date in
  `data/evaluation/model_state.json` — this is normal.
