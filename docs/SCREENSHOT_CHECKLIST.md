# Screenshots and demo script

Everything below describes screens that exist in the app today. Take the screenshots with **fake data only**
(the sample data), save them in `docs/images/` and link the best ones from the README.

**Before you start:** run the API and the dashboard (`README.md`, "Run it on your computer"), create an account with
*Start with sample data* ticked, and use a window about 1280 x 800 wide.

## Screenshots to take

### 1. Log in and private workspace
- [ ] **Login screen** (`/`, logged out): brand, tabs *Log in* / *Create account*, checkbox *Start with sample data (recommended)*.
- [ ] **Sidebar** after login: your email and workspace name, the **Demo data** badge, the menu (Home, Investigation,
      Approvals, Evals, My data, Settings), *Workspace tools*, *Log out*.
- [ ] *(Optional)* A second account with an empty workspace: badge **Live workspace**, no demo banner.

### 2. Home
- [ ] **KPI cards**: Total invoices, Verified, Needs review, Mismatches.
- [ ] **Invoice ledger**: brown header, status pills, search box, "Review snapshot" cards on the right.
- [ ] **Invoice inspection** (scroll down): supplier, PO, dates, subtotal, grand total and the line-item table.

### 3. Investigation (the main screenshot)
- [ ] Pick a **mismatch** invoice (invoice 19 has a price mismatch), click *Run investigation*.
- [ ] The summary row (Check status, Confidence, Findings, Contract quotes) and the **recommendation** box.
- [ ] **Evidence for "Price"**: the green/red *Match* / *Mismatch* pill, the difference in rupees, and the table
      *What we compared | Value | Source*.
- [ ] **Contract quotes** opened, showing the clause number and title.
- [ ] **Guardrails** row: Grounding "N/N verified", Prompt injection "None found", Blocked actions.
- [ ] *(Optional)* The *Use AI explanation (Gemini) - N of 5 left today* checkbox.

### 4. Approvals (the human decides)
- [ ] **Waiting for a decision** table and the agent's recommendation.
- [ ] The **decision form**: *Your full name*, Approve / Reject, *Note*, *Submit decision*.
- [ ] A refused attempt: type `investigation_agent` as the name and submit -> the red message saying only a named
      finance person may decide (this shows the "no auto-approval" rule).
- [ ] **Recent decisions** table after a real name has approved something.

### 5. My data and Settings
- [ ] **My data**: the five tabs and the *Download template* buttons; a row-by-row error message from a bad CSV.
- [ ] **Settings**: the key shown **once** (blur it before publishing!), then the list with *Revoke*.

### 6. Automation
- [ ] **n8n canvas** of `invoice_workflow.json`: Gmail Trigger, Settings, Split attachments, VouchFlow ingest, IF, three Telegram nodes.
- [ ] **Telegram message** for the price-mismatch sample: supplier, amount, problem, recommended action, link.
- [ ] The **webhook test** answer (`curl` output with `status`, `mistakes`, `dashboard_link`).

### 7. Evals
- [ ] **Evals** page overview with the six score cards and one tab (for example *Investigation agent*).

> Do not publish screenshots that show a real API key, a database link, a Gemini key or a real email address.

---

## 2-minute demo script

*Say it in your own words. Times are a guide.*

**0:00 - Problem (15 s).** "Finance teams check every supplier invoice against the purchase order, the goods received
note and the contract. It is slow and mistakes slip through. VouchFlow does the checking and explains it. A person
always approves. All data you see is fake."

**0:15 - Start (20 s).** Create an account with sample data. "Each user gets a private workspace; the badge says
*Demo data*." Point at the sidebar (email, workspace).

**0:35 - Find a problem (30 s).** Home: "most invoices are clean, a few are flagged." Open a **mismatch** invoice in *Investigation* and
click *Run investigation*. Show the **Price** evidence: "invoiced Rs. 12,600, PO and contract say Rs. 12,000 - and every
number says where it came from." Open the **contract quote**: "the agent cites the clause, or says *no source found*
instead of guessing." Mention the guardrail row.

**1:05 - A person decides (25 s).** Approvals: type `investigation_agent` -> refused. "Software can never approve."
Enter a real name, write a note, click *Reject*. "Every decision is in the audit log."

**1:30 - Automation (20 s).** Show the Telegram alert from the price-mismatch sample invoice (or the n8n canvas): "Email
arrives, n8n sends it to the API, the agent checks it, and I get this message with a link. Still nothing is paid."

**1:50 - Honest close (10 s).** "On my test sets the rule checks score 120 of 120 and the agent 20 of 20 - but that is
generated data written by the same author, so the next step is real invoices and independent review."
