# n8n automation for VouchFlow AI (beginner guide)

**What it does:** when an email with an invoice attached arrives in Gmail, n8n sends the file to
VouchFlow, VouchFlow checks it (purchase order, goods received note, contract), and n8n sends you a
**Telegram message**: either "problem found" (with the supplier, the amount, what is wrong and a link) or a
short "verified" message. **Nothing is ever approved or paid automatically** - a person always clicks
Approve in the dashboard.

```
Gmail  ->  n8n  ->  VouchFlow API  ->  checks + agent  ->  n8n  ->  Telegram message  ->  you approve in the dashboard
```

There are two workflow files in this folder:

| File | What it is | Needs |
|---|---|---|
| `webhook_workflow.json` | **Start here.** Test with one command, no Gmail, no Telegram. | VouchFlow API key only |
| `invoice_workflow.json` | The real one: Gmail -> VouchFlow -> Telegram. | API key + Telegram bot + Gmail login |

---

## Part 1 - Get VouchFlow ready

You need three things from VouchFlow:

1. **The API running.** In a terminal in the project folder:
   ```
   python -m uvicorn backend.main:app --reload
   ```
   It listens on `http://localhost:8000`. (Check: open http://localhost:8000/health - it shows `{"status":"ok"}`.)
2. **A workspace with your purchase orders etc.** Open the dashboard (`streamlit run dashboard/app.py`), create an
   account and use the **My data** page to upload purchase orders, goods received notes and contract prices.
   *(For a quick test, use the three template files you can download there - the sample invoices in
   `data/samples/` match them exactly.)*
3. **An API key.** Dashboard -> **Settings** -> type a name (e.g. `n8n`) -> **Create key**. Copy the key that appears
   (starts with `vf_`). **It is shown only once.** If you lose it, revoke it and create a new one.

> **To read invoices the API needs a Gemini key.** Put `GEMINI_API_KEY=...` in the `.env` file next to the API.
> Without it, VouchFlow still saves and checks the invoice but marks it **"needs review"** because it could not read it.

---

## Part 2 - Install and start n8n

1. Install **Node.js** (the "LTS" version) from https://nodejs.org if you do not have it. Check: `node --version`.
2. In a terminal run:
   ```
   npx n8n
   ```
   The first time it downloads n8n (a few minutes). When it says **"Editor is now accessible via: http://localhost:5678"**
   open that address in your browser and create the owner account it asks for. Leave the terminal open - n8n runs there.

---

## Part 3 - Test with the webhook workflow (no Gmail needed)

1. In n8n: **Workflows -> Create workflow**. Click the **...** menu (top right) -> **Import from file...** ->
   choose `n8n/webhook_workflow.json`.
2. **Create the API-key credential.** Double-click the node **VouchFlow ingest**. Under *Credential for Header Auth*
   choose **Create new credential** and fill in:
   - **Name:** `X-API-Key`
   - **Value:** your key (`vf_...`)

   Save it (call it `VouchFlow API key`). The key lives inside n8n, **not** in the workflow file.
3. Double-click the node **Settings** and check `api_base_url` (default `http://localhost:8000`).
4. Click **Execute workflow** (it now waits for a test call - the *Webhook* node shows the test address, ending in
   `/webhook-test/vouchflow-invoice`).
5. In another terminal, in the project folder (PowerShell):
   ```
   curl.exe -X POST "http://localhost:5678/webhook-test/vouchflow-invoice" -F "file=@data/samples/sample_invoice_clean.pdf"
   ```
6. You get VouchFlow's answer as JSON, for example:
   ```
   { "invoice_id": 7, "status": "verified", "mistakes": [], "recommended_action": "ready_for_human_approval",
     "dashboard_link": "http://localhost:8501/investigation?invoice=7", "human_approval_required": true, ... }
   ```
   Now try the second sample: `data/samples/sample_invoice_price_mismatch.pdf` -> `"status": "mismatch_detected"`,
   `"mistakes": ["price_mismatch"]` (the chair is billed at Rs. 4,800 but the contract price is Rs. 4,500).

> **The two sample invoices are fake** and are made by `python scripts/make_sample_invoices.py`. They match the
> template CSV files (supplier *Acme Office Supplies*, PO-1001). If you upload the same invoice twice, VouchFlow
> correctly flags the second one as a duplicate.

You can also skip n8n and call the API directly:
```
curl.exe -X POST "http://localhost:8000/api/invoices/ingest" -H "X-API-Key: PASTE_YOUR_KEY" -F "file=@data/samples/sample_invoice_clean.pdf"
```

---

## Part 4 - The real workflow (Gmail -> Telegram)

### 4a. Make a Telegram bot (2 minutes)
1. In Telegram, open a chat with **@BotFather**, send `/newbot` and follow the questions. It gives you a **token**
   (looks like `123456789:ABC...`). Keep it secret.
2. Open a chat with your new bot and send it any message (for example "hi").
3. Find your **chat id**: open this address in your browser, replacing `YOUR_TOKEN` (do not share the page):
   `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
   Look for `"chat":{"id":123456789,...` - that number is your chat id.

### 4b. Import and connect
1. In n8n import `n8n/invoice_workflow.json` (same as in Part 3).
2. **Settings** node: set `api_base_url` and paste your `telegram_chat_id`.
3. Node **VouchFlow ingest**: pick the `VouchFlow API key` credential you made in Part 3.
4. The three **Telegram** nodes: create a credential **Telegram API**, paste the bot token as *Access Token*, and
   select it in all three nodes.
5. Node **Gmail Trigger**: create a **Gmail OAuth2** credential and sign in with the Google account that receives the
   invoices. Google asks you to create an "OAuth client" once - n8n explains the steps right in the credential window
   (https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/).
6. Click **Execute workflow** once to test (send yourself an email with a PDF invoice attached), then switch the
   workflow to **Active** (toggle, top right) so it keeps running.

### What the Telegram messages look like
- Problem: `MISMATCH: Invoice INV-ACME-0002 from Acme Office Supplies - Rs. 63,720.00` /
  `Problems: price mismatch (difference Rs. ...)` / `Recommended: Ask the supplier for clarification` /
  `A person must approve it: <link>`
- Clean: `Invoice INV-ACME-0001 (Acme Office Supplies, Rs. 60,180) is verified. A person still has to approve it: <link>`
- Failure (wrong key, too many calls, bad file): `VouchFlow could not process invoice.pdf: ...`

The link opens the dashboard's Investigation page for that invoice (you log in first).

---

## If something goes wrong

| You see | Meaning | Fix |
|---|---|---|
| `401` / "Missing or invalid API key" | wrong, missing or revoked key | create a new key on the Settings page; update the n8n credential |
| `429` "Too many requests" | more than 20 files per minute with one key | wait a minute (the limit is `INGEST_RATE_LIMIT_PER_MINUTE`) |
| `400` "Invalid file type" / "does not look like a real PDF" | the attachment is not an invoice document | only PDF, PNG, JPG up to 10 MB are accepted |
| Connection refused | the API is not running, or n8n cannot reach `localhost` | start the API; if n8n runs in Docker use `http://host.docker.internal:8000` |
| `"extraction_ok": false`, status `needs_review` | the API has no Gemini key, or the invoice is unreadable | add `GEMINI_API_KEY` to the API's `.env` |
| `"missing_po"` in mistakes | the invoice's PO number is not in your workspace | upload the purchase orders in **My data** |
| Telegram node fails | wrong token or chat id | re-check both; send your bot a message first |

## Safety notes
- Keys and tokens are stored by n8n as **credentials**; the workflow files contain none (a test checks this).
- An API key opens **one workspace only**. Revoke it any time on the **Settings** page.
- The workflow only **reads** and **reports**. It never calls the approval endpoint - approving is done by a person.
