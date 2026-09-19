# VendorPulse (ContractGuard)

**Repo:** https://github.com/Hamza786110/VendorPulse

A vendor-contract renewal tracker: upload a contract, get its renewal date, auto-renew clause, price, and cancellation window pulled out automatically, get flagged and emailed before you accidentally get auto-renewed or miss a cancellation window.

---

## 1. The problem

Businesses (and individuals) sign vendor contracts — SaaS subscriptions, service agreements, leases — that quietly auto-renew unless someone remembers to cancel within a specific notice window before the renewal date. Nobody tracks this centrally. Contracts sit as PDFs in someone's inbox or drive, the cancellation window comes and goes unnoticed, and the business ends up paying for another term (or a full year) of something it meant to cancel.

The core failure isn't a lack of contracts — it's a lack of *visibility*. There's no single place that says "these 3 contracts need a decision in the next 30 days."

## 2. The solution

VendorPulse is a small SaaS tool that:

1. Lets a user upload a contract file (PDF/DOCX).
2. Uses an LLM to extract the terms that actually matter for renewal decisions: vendor name, renewal date, auto-renew (yes/no), cancellation notice window (days), price, billing frequency.
3. Runs a nightly check across every stored contract and flags any that are approaching their renewal date or their cancellation deadline.
4. Emails the user when a contract gets flagged, when extraction fails or is low-confidence, or when they update a contract and something changed.
5. Lets the user semantically search the actual text of a contract, not just its extracted fields (e.g. "does this mention a data-retention clause?").

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI | async, fast to build endpoints on |
| Auth | Custom JWT (`python-jose`), `passlib`/`bcrypt` for hashing | signup/signin/forgot-password, email-based |
| Database | MongoDB (`motor`/`pymongo`) | contracts + users, schemaless fit for evolving extracted-field shape |
| Field extraction | Groq (via `langchain-groq`) + LangChain structured output (`PydanticOutputParser`) | fast, cheap LLM inference against a fixed Pydantic schema (`ExtractedContractFields`) |
| Semantic search | ChromaDB + Google `text-embedding` (`langchain-google-genai`) | local vector store, no extra infra to run |
| Chunking | LangChain's semantic chunker (`langchain_experimental`) | splits contract text into coherent passages before embedding |
| Scheduled jobs | Apache Airflow (`@dag`/`@task` decorators) | nightly scan for upcoming renewals/cancellation windows |
| Email | SMTP via a shared `send_email()` helper (originally built for password reset) | renewal alerts, extraction-issue alerts, contract-update alerts |
| Demo UI | Streamlit | fastest way to exercise the API end to end while the real frontend is undecided |
| Containers | Docker Compose (`contractguard-backend`, `contractguard-airflow`) | run API + scheduler together locally |

## 4. How it's built — the pieces

### Data model (`contracts/models.py`)
`ContractDocument`: filename, file_path, uploaded_by, status (`uploaded` → `extracting` → `extracted`/`extraction_failed`), raw_text, extracted fields, flagged/flag_reason/flagged_at, alert_sent (dedupe flag), previous_versions (history kept when a file is replaced).

`ExtractedContractFields`: renewal_date, auto_renew, cancellation_window_days, pricing_amount/currency/frequency, vendor_name, confidence_notes (the model's own note when it's unsure about a field).

### Upload & extract (`contracts/routes.py`)
- `POST /contracts/upload` — saves the file, extracts raw text (pdfplumber/python-docx), stores the record, and schedules chunk-embed-store into Chroma as a background task (keyed on the Mongo `_id`, not the throwaway upload uuid).
- `POST /contracts/{id}/extract` — runs the Groq extraction chain on the stored raw text. Alerts by email if extraction fails outright, or if the model's own `confidence_notes` came back non-empty.
- `GET /contracts/{id}` / `GET /contracts` — fetch one or list the user's contracts.
- `GET /contracts/{id}/ask?question=...` — semantic search over that one contract's stored chunks, scoped so a user can't query someone else's contract.
- `POST /contracts/{id}/replace` — the "I have an updated version of this contract" flow: re-extracts the new file, diffs old vs new extracted fields, re-indexes the vectorstore (clearing stale chunks first), emails a summary of what changed, and archives the old version rather than discarding it.
- `GET /contracts/stats` — dashboard counts (total/extracted/extracting/failed/flagged), plain DB counts with no LLM involved.

### Retrieval pipeline (`retrieval/`)
`loaders.py` → `chunking.py` → `embeddings.py` → `vectorstore.py`: load a file into LangChain `Document`s, semantically chunk it, embed the chunks, upsert into Chroma tagged with the contract's id. `store_chunks`, `query_contract`, and `delete_contract_chunks` are the three entry points the rest of the app calls.

### Alerts (`contracts/notifications.py`)
Three email types, all best-effort (a failed/unconfigured SMTP logs and returns, never crashes the caller):
- `notify_contract_flagged` — renewal/cancellation window approaching.
- `notify_extraction_issue` — extraction failed, or succeeded with something the model wants double-checked.
- `notify_contract_updated` — a replaced file's extracted fields changed, with a plain-language diff (`diff_extracted_fields`).

### Nightly renewal check (`airflow/dags/renewal_flagging_dag.py`)
Runs daily. Scans every contract with a known renewal date, flags anything renewing or hitting its cancellation deadline within 30 days, and emails the owner — but only **once per flagged streak** (an `alert_sent` flag prevents re-emailing every night for a contract that's already been flagged). Unflagging (contract renewed/resolved) resets that dedupe flag so a future re-flag alerts again.

### Demo UI (`app.py`, Streamlit)
Two tabs: Upload & Extract (the original demo flow), and Dashboard (the `/stats` numbers as metric tiles). A third tab wired up a chatbot (LangGraph tool-calling agent answering "how many contracts do I have" type questions) but it was pulled back out after causing issues — the module (`contracts/chatbot.py`) is still on disk, just unwired.

## 5. What's done so far

- ✅ Auth: signup/signin/forgot-password, JWT-based
- ✅ Upload → text extraction → Groq structured extraction
- ✅ MongoDB storage of contracts + extracted fields
- ✅ Vectorstore pipeline built and **wired into the live upload flow** (originally only ran via a standalone test script)
- ✅ Semantic search endpoint (`/ask`)
- ✅ Nightly Airflow DAG flagging contracts nearing renewal/cancellation
- ✅ Email alerts: renewal flagged (deduped), extraction failed, low-confidence extraction, contract updated
- ✅ Replace-a-contract flow with field diffing and version history
- ✅ Dashboard stats endpoint + Streamlit tab
- ⏸️ Chatbot — built, then disabled due to issues; not currently wired in
- ⚠️ Known issue: the DAG file on GitHub currently has a broken/incomplete merge of the alert-dedupe logic (missing `get_owner_email` helper and its imports) — needs a fix pass before the nightly alert will actually run without crashing
- ⚠️ `requirements.txt` is missing some deps the auth module actually needs (`python-jose`, `passlib`, `bcrypt`, `python-multipart`, `email-validator`) — repo won't boot cleanly until those are added

## 6. What's next

- Finish syncing `contracts/routes.py` on GitHub with the alert/replace/stats wiring (in progress as of this doc)
- Fix the DAG's broken alert-dedupe merge
- Add the missing auth dependencies to `requirements.txt`
- Decide on the real frontend (Streamlit is a demo, not the product) — Vercel was the original plan
- Revisit the chatbot once the underlying issues are understood
- Longer term, from the original product concept: a proper alerts view in the UI (not just email), and pipeline health monitoring for the Airflow side