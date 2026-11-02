# 🧾 VouchFlow AI - Intelligent 3-Way Matching AP Assistant

**VouchFlow AI** is an intelligent AI finance assistant for Accounts Payable (AP) teams. It extracts invoice data with OCR/LLMs, verifies supplier invoices against Purchase Orders (PO), Goods Received Notes (GRN), and Master Contracts (3-way matching), flags discrepancies with itemized evidence, and keeps a human in the loop for final approval.

> **Phase 3 Release (3-Way Matching Checker):** Features a 100% deterministic, rule-based matching engine in pure Python. Performs price reconciliation (Invoice vs PO vs Contract), quantity verification (Invoice vs GRN), mathematical cross-totals (line items sum, 18% GST calculation, grand total tolerance 0.01), missing PO detection, duplicate invoice detection (identical invoice number, supplier+date+amount, or file hash), and extraction quality gating (confidence < 0.70 forces `needs_review`). Results are persisted in `invoice_checks` with full audit logging, evaluated via `scripts/run_matching_eval.py` (achieving 100% precision, recall, and F1 across all 50 ground truth invoices), and covered by comprehensive unit tests.

---

## 🏗️ Folder Structure

```text
vouchflow-ai/
├── backend/
│   ├── config.py                 # Pydantic Settings (DATABASE_URL, GEMINI_API_KEY, GEMINI_MODEL_LIST)
│   ├── main.py                   # FastAPI application (extraction & matching endpoints)
│   ├── database/
│   │   ├── db.py                 # Engine, sessionmaker, and get_db dependency
│   │   ├── models.py             # SQLAlchemy models (8 business tables + invoice_extractions + invoice_checks + audit logs)
│   │   └── schemas.py            # Pydantic v2 schemas (ExtractedInvoice, InvoiceCheckResult, MatchFinding)
│   ├── services/
│   │   └── invoice_service.py    # Service logic for invoices, uploads, extractions, matching & audit logs
│   └── tools/
│       ├── invoice_reader.py     # Multimodal Invoice Reader (pdfplumber + Gemini Flash vision fallback)
│       └── matcher.py            # Deterministic 3-Way Matching Engine (pure Python, 0% LLM)
├── dashboard/
│   └── app.py                    # Streamlit finance dashboard
├── data/
│   ├── contracts/                # 8 Supplier master contract agreements
│   ├── evaluation/               # ground_truth.csv, extraction_results.csv, matching_results.csv & model_state.json
│   ├── goods_received_notes/     # Warehouse receipt notes
│   ├── invoices/                 # 50 Generated invoice PDFs & uploaded documents
│   └── purchase_orders/          # Purchase orders
├── docs/                         # Project documentation
├── scripts/
│   ├── generate_data.py          # Generates 50 PDF invoices, contracts & ground truth
│   ├── seed_db.py                # Fills the SQLite/PostgreSQL database
│   ├── run_extraction_eval.py    # Benchmarks extraction accuracy against ground_truth.csv
│   └── run_matching_eval.py      # Evaluates 3-way matching accuracy, precision, recall & confusion matrix
├── tests/
│   ├── test_api.py               # Tests for health, listing, detail & file upload endpoints
│   ├── test_generator.py         # Tests for PDF generation and ground truth distribution
│   ├── test_reader.py            # Unit tests for Invoice Reader with mocked Gemini (offline)
│   └── test_matcher.py           # Unit tests for 3-way matching engine across all discrepancy types
├── .env.example                  # Environment configuration template
├── .gitignore                    # Git ignore file
├── requirements.txt              # Pinned Python package dependencies
└── README.md                     # This setup and user guide
```

---

## 🗄️ Database Tables & Schema

All models are defined in [backend/database/models.py](file:///c:/Users/khushboo%20pingle/Desktop/vouchflow-ai/backend/database/models.py) using SQLAlchemy 2.x:

1. **`suppliers`**: Vendor company profiles, addresses, contact details, and Indian GSTIN numbers.
2. **`contracts`**: Master price agreements specifying agreed unit prices, payment terms, and GST clauses.
3. **`purchase_orders`**: Approved internal orders issued to suppliers.
4. **`po_items`**: Line items for each purchase order (quantity, agreed unit price, line total).
5. **`goods_received_notes`**: Warehouse physical delivery confirmations (GRN).
6. **`grn_items`**: Physical quantities verified as received by warehouse personnel.
7. **`invoices`**: Supplier bills submitted for payment.
8. **`invoice_items`**: Billed line items (item name, quantity, unit price, total price).
9. **`invoice_extractions`**: Extracted JSON invoice payloads, confidence scores, models used, and timestamps.
10. **`invoice_checks`**: 3-way matching check results, status (`verified`, `mismatch_detected`, `needs_review`), `mistake_types`, itemized `findings_json`, and financial difference.
11. **`audit_logs`**: Tracks every sensitive system action (`who`, `action`, `time`, `details`) ensuring complete compliance.

### Invoice Status Values:
- **`verified`**: Clean match across Invoice, PO, GRN, and Contract (70% of generated data).
- **`needs_review`**: Uploaded or missing essential references (e.g. missing PO) or low extraction confidence.
- **`mismatch_detected`**: Discrepancy detected (price mismatch, quantity mismatch, wrong total, duplicate).
- **`pending_approval`**: Checked and queued for finance manager approval.

> **Design Principle:** Running an extraction or matching check records findings in `invoice_extractions` or `invoice_checks` without mutating the original `invoices.status` directly, keeping AP workflow history clean and audited.

---

## 🚀 Quickstart Guide (Windows)

### 1. Environment Setup

Clone or open the `vouchflow-ai` directory in your terminal:

```powershell
# Navigate to the repository
cd "C:\Users\khushboo pingle\Desktop\vouchflow-ai"

# Optional: Create and activate a Python virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` (or configure your existing `.env`):

```env
DATABASE_URL=sqlite:///./vouchflow.db
DATA_DIR=./data
ENVIRONMENT=development

# Gemini API Configuration (for live invoice reading)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

> **Security Note:** Your `GEMINI_API_KEY` is never printed, logged, or exposed in audit trails or API responses.

---

## ⚡ Running the Project

### Step 1: Generate Synthetic Invoices & Contracts

Run the data generator to create 8 supplier contracts, 50 invoice PDFs with ReportLab (in `data/invoices/`), and the ground truth answer sheet:

```powershell
python scripts/generate_data.py
```

- **Output:**
  - 8 contract text files in `data/contracts/`
  - 50 invoice PDFs in `data/invoices/` using `"Rs."`, line items, and 18% GST (9% CGST + 9% SGST)
  - Answer key in `data/evaluation/ground_truth.csv` with 35 clean invoices and 15 planted mistakes.

---

### Step 2: Seed the Database

Populate your database with suppliers, contracts, purchase orders, goods received notes, invoices, and line items:

```powershell
python scripts/seed_db.py
```

This script is **idempotent** and can be run multiple times safely.

---

### Step 3: Run the FastAPI Backend API

Start the backend API server with auto-reload:

```powershell
python -m uvicorn backend.main:app --reload
```

- **API Base URL:** `http://localhost:8000`
- **Interactive Swagger Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Endpoints:**
  - `GET /health` &rarr; Health check
  - `GET /invoices` &rarr; Lists invoices with supplier name, PO number, totals, and status (supports optional `?status=verified`)
  - `GET /invoices/{id}` &rarr; Full invoice details with line items
  - `POST /invoices/upload` &rarr; Saves uploaded PDF/image, creates a record with status `needs_review`, and logs audit event
  - `POST /invoices/{id}/extract` &rarr; Triggers Invoice Reader extraction; saves result to `invoice_extractions`
  - `GET /invoices/{id}/extraction` &rarr; Retrieves saved extraction JSON, confidence score, and metadata
  - `POST /invoices/{id}/check` &rarr; Triggers 3-way matching checker; saves findings and financial difference to `invoice_checks`
  - `GET /invoices/{id}/check` &rarr; Retrieves stored 3-way matching check results and itemized discrepancy findings
  - `GET /audit-logs` &rarr; View recent audit events

---

### Step 4: Run the Extraction Evaluation Script

Benchmark the extraction engine against the ground-truth answer sheet with automatic multi-model rotation:

```powershell
# Evaluate 10 invoices using live Gemini API (rotates models on daily limits)
python scripts/run_extraction_eval.py --count 10

# Resume extraction: skips previously successful extractions (free-tier friendly)
python scripts/run_extraction_eval.py --count 10 --resume

# Force re-running all extractions, ignoring cache
python scripts/run_extraction_eval.py --count 10 --force

# Or run in offline mock mode (no API calls, fast verification)
python scripts/run_extraction_eval.py --count 10 --mock
```

- **Multi-Model Rotation:** Automatically rotates across `GEMINI_MODEL_LIST` when daily free-tier limits (429 Daily) are reached.
- **State Persistence:** Remembers exhausted models in `data/evaluation/model_state.json` and resets each day.
- **Metrics evaluated:** Vendor name, invoice number, invoice date, grand total, and line item count.
- **Export:** Detailed side-by-side comparison with `model_name` and `error_message` saved to `data/evaluation/extraction_results.csv`.

---

### Step 5: Run the 3-Way Matching Evaluation Script

Benchmark the 3-way matching engine against all 50 ground truth invoices:

```powershell
# Evaluate all 50 invoices
python scripts/run_matching_eval.py --all

# Or evaluate a subset (e.g. first 10)
python scripts/run_matching_eval.py --count 10
```

- **Metrics Evaluated:**
  - Overall status accuracy (`verified`, `mismatch_detected`, `needs_review`)
  - Mistake type accuracy (`none`, `price_mismatch`, `quantity_mismatch`, `wrong_total`, `duplicate_invoice`, `missing_po`)
  - Precision, Recall, and F1 score per mistake category
  - Full ASCII confusion matrix
- **Export:** Summary saved to `data/evaluation/matching_results.csv`.
- **Results:** 50/50 (100.0%) Status Accuracy, 100.0% Precision/Recall/F1 across all mistake categories.

---

### Step 6: Run the Streamlit Dashboard

In a new terminal window, start the Streamlit dashboard:

```powershell
python -m streamlit run dashboard/app.py
```

- **Dashboard URL:** [http://localhost:8501](http://localhost:8501)
- **Features:**
  - **Metric Cards:** Total Invoices, Verified, Needs Review, Mismatch Detected
  - **Interactive Invoice Ledger:** Filter by status with color-coded status badges
  - **Single Invoice Drill-Down:** Line items and pricing breakdown
  - **Quick Upload Box:** Test invoice document uploads directly

---

### Step 7: Run Automated Tests

Execute the full automated test suite (28 tests, 100% offline, zero external API calls):

```powershell
# Run the complete test suite (28 tests)
python -m pytest -v

# Or run specific test modules
python -m pytest tests/test_matcher.py -v
python -m pytest tests/test_reader.py -v
python -m pytest tests/test_api.py -v
python -m pytest tests/test_generator.py -v
```

---

## 🎯 Ground Truth Discrepancy Matrix

The answer key is saved in [data/evaluation/ground_truth.csv](file:///c:/Users/khushboo%20pingle/Desktop/vouchflow-ai/data/evaluation/ground_truth.csv):

| Mistake Type | Count | Expected Status | Description |
| :--- | :---: | :--- | :--- |
| `none` (Clean) | 35 | `verified` | Invoice perfectly matches PO, GRN, and Contract |
| `price_mismatch` | 3 | `mismatch_detected` | Invoiced unit price differs from contract/PO agreed price |
| `quantity_mismatch` | 3 | `mismatch_detected` | Invoiced quantity exceeds quantity physically received on GRN |
| `wrong_total` | 3 | `mismatch_detected` | Mathematical calculation error on invoice total |
| `duplicate_invoice` | 3 | `mismatch_detected` | Resubmission of an already processed invoice |
| `missing_po` | 3 | `needs_review` | Invoice has no purchase order reference |
