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
- Python 3.14, FastAPI + SQLAlchemy 2 + Pydantic v2, SQLite (`vouchflow.db`, gitignored)
- Streamlit dashboard
- Gemini via `google-genai` directly (automatic model switching via `GEMINI_MODEL_LIST`)
- Contract search (RAG): LangChain `Chroma` wrapper (from `langchain_community`) + ChromaDB,
  local ONNX MiniLM embeddings, stored in `data/chroma_db/`
- Investigation Agent: LangGraph `StateGraph`

## Folders
- `backend/main.py` — FastAPI routes: health, invoices list/detail/upload, extract, check,
  audit-logs, investigate/investigation, and Phase 8 approvals:
  `POST /invoices/{id}/decision`, `GET /approvals/queue`, `GET /approvals/decisions`
- `backend/config.py` — settings from `.env`
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
- `.streamlit/config.toml` — light theme + DM Sans font; colours must equal `ui_common.PALETTE`
  (checked by `tests/test_theme.py`)
- `dashboard/pages/` — `1_Investigation.py`, `2_Approvals.py`, `3_Evals.py` (Evals is read-only)
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
python scripts/seed_db.py                # fill database (safe to re-run)
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
- Left: Phase 7 n8n automation (must never call /decision), Docker, README with results, demo video.
- Pending idea (not done, needs OK): switch `langchain_community.vectorstores.Chroma`
  to `langchain_chroma` package.

## Notes
- Tests use the real `vouchflow.db`; tests that create rows should delete them afterwards
  (see `tests/test_approvals.py`). A test run rewrites `data/chroma_db/*.bin` and the date in
  `data/evaluation/model_state.json` — this is normal.
