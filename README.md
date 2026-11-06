# VendorPulse (ContractGuard)
 
> Upload a vendor contract. Get its renewal terms extracted automatically, get emailed before it renews, and ask questions about your contracts in plain English.
 
**Repo:** https://github.com/Hamza786110/VendorPulse
 
---
 
## The problem
 
Businesses sign vendor contracts (SaaS subscriptions, service agreements, leases) that quietly auto-renew unless someone remembers to act before a deadline. Contracts sit as PDFs in inboxes and drives, nobody tracks them in one place, and the company pays for another term it meant to cancel.
 
The failure isn't a lack of contracts, it's a lack of **visibility**. There's no single place that says "these contracts need a decision soon."
 
## The solution
 
VendorPulse is a small SaaS tool that:
 
1. Lets a user upload a contract (PDF or DOCX).
2. Uses an LLM to extract the terms that matter: vendor name, renewal date, auto-renew clause, cancellation notice window, price, currency and billing frequency.
3. Indexes the contract text so it can be searched semantically.
4. Triggers an Airflow job that emails the owner **5 days before the renewal date**. A nightly run also catches anything missed.
5. Emails the user when extraction fails or comes back low-confidence, and when a replaced contract changes the extracted terms.
6. Offers a per-user chatbot that answers questions about the user's own contracts, grounded in MongoDB data rather than guesses.
---
 
## Architecture
 
```
                 ┌────────────────────┐
                 │  Streamlit UI      │  app.py (auth, upload, dashboard, detail)
                 │  + chat_ui.py      │  chat screen
                 └─────────┬──────────┘
                           │ REST + JWT
                 ┌─────────▼──────────┐        ┌────────────────────┐
                 │  FastAPI backend   │───────▶│  MongoDB Atlas     │
                 │  auth / contracts  │        │  users, contracts, │
                 │  / chatbot         │        │  chat_messages     │
                 └───┬─────────┬──────┘        └─────────▲──────────┘
                     │         │                         │
        embeds chunks│         │ trigger DAG run         │ pymongo
                     ▼         ▼                         │
            ┌─────────────┐  ┌────────────────────┐      │
            │  ChromaDB   │  │  Apache Airflow    │──────┘
            │ vectorstore │  │  renewal_flagging  │──▶ SMTP email
            └─────────────┘  └────────────────────┘
```
 
**Key design choices**
 
- MongoDB is the source of truth for structured fields. ChromaDB holds only text chunks for semantic search.
- FastAPI uses Motor (async), Airflow uses pymongo (sync). Both are intentional.
- The Airflow DAG reuses the backend's email code by mounting `./auth` and `./contracts` into the Airflow container read-only.
- The chatbot's `user_id` always comes from the JWT, never from the request body.
---
 
## Tech stack
 
| Layer | Choice |
|---|---|
| API | FastAPI, Uvicorn |
| Auth | JWT (`python-jose`), `passlib` + `bcrypt`, email-based password reset |
| Database | MongoDB Atlas via Motor (API) and pymongo (Airflow) |
| Field extraction | Groq via `langchain-groq`, structured output into a Pydantic schema |
| Document loading | `pdfplumber`, `PyPDFLoader`, `python-docx` / `docx2txt` |
| Semantic search | LangChain `SemanticChunker`, Google GenAI embeddings, ChromaDB (persistent local client) |
| Chatbot | LangChain `create_agent` (LangGraph-backed ReAct agent) on Groq, with MongoDB-backed per-user memory |
| Scheduling / automation | Apache Airflow 2.10 (standalone, SequentialExecutor) |
| Email | SMTP through a shared `send_email()` helper |
| Frontend | Streamlit |
| Packaging | Docker + Docker Compose, `uv` (Python 3.13) |
 
---
 
## Features
 
### Authentication (`auth/`)
Sign up, sign in, `GET /auth/me`, forgot-password and reset-password flow over SMTP. All contract and chatbot routes are user-scoped via the JWT.
 
### Contracts (`contracts/routes.py`)
 
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/contracts/upload` | Save file, extract raw text, store record, index chunks in the background |
| POST | `/contracts/{id}/extract` | Run Groq structured extraction on the stored text |
| GET | `/contracts` | List the current user's contracts |
| GET | `/contracts/{id}` | One contract with extracted fields |
| GET | `/contracts/{id}/rag-status` | Indexing progress for the live pipeline checklist |
| GET | `/contracts/{id}/ask?question=...` | Semantic search over that contract's chunks |
| POST | `/contracts/{id}/replace` | Upload an updated version: re-extract, diff old vs new fields, re-index, email a change summary, keep the old version in `previous_versions` |
| GET | `/contracts/stats` | Dashboard counts (plain DB counts, no LLM) |
 
Extracted fields (`ExtractedContractFields`): `renewal_date`, `auto_renew`, `cancellation_window_days`, `pricing_amount`, `pricing_currency`, `pricing_frequency`, `vendor_name`, `confidence_notes`.
 
### Renewal reminders (`airflow/dags/renewal_flagging_dag.py`)
- `renewal_flagging_dag` runs `@daily`.
- Extraction, replacement and similar events also trigger a run through the Airflow REST API (`contracts/airflow_client.py`), so new uploads are checked without waiting for the schedule.
- A contract whose renewal date is within 5 days gets one reminder email to its owner.
- `renewal_reminder_sent` prevents re-emailing every night.
### Email alerts (`contracts/notifications.py`)
Best-effort. A failed or unconfigured SMTP logs and returns, and never crashes the caller.
- Renewal reminder
- Extraction failed or low-confidence
- Contract updated (plain-language field diff)
### Chatbot (`contracts/chatbot*.py`)
A ReAct agent that can only read data through read-only, user-scoped tools:
 
`contract_stats`, `list_contracts`, `get_contract_details`, `upcoming_renewals`, `list_uploads`, `reminder_status`, `search_contract_content`
 
- Counts, dates and prices are computed in code, not by the LLM.
- Missing fields come back as `"not extracted"`, so the model can't fill gaps itself.
- Only the question and final answer are stored (collection `chat_messages`). Tool results are re-fetched fresh each time, and only a short history window is loaded.
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/contracts/chatbot` | Ask a question |
| GET | `/contracts/chatbot/history` | Load recent messages |
| DELETE | `/contracts/chatbot/history` | Clear chat |
 
### Streamlit UI
- `app.py`: sign in / sign up / forgot password, upload and extract with a live pipeline checklist, dashboard with KPIs and contract list, contract detail view.
- `chat_ui.py`: the chat screen for the assistant.
---
 
## Project structure
 
```
.
├── main.py                    # FastAPI app, Mongo lifespan, routers
├── app.py                     # Streamlit frontend
├── chat_ui.py                 # Streamlit chat screen
├── auth/                      # signup/signin/reset, JWT, SMTP helper
├── contracts/
│   ├── routes.py              # upload, extract, ask, replace, stats
│   ├── chains.py              # Groq extraction chain
│   ├── models.py              # Pydantic models / schema
│   ├── notifications.py       # email alerts + field diff
│   ├── airflow_client.py      # triggers DAG runs
│   ├── stats.py               # dashboard counts
│   └── chatbot*.py            # routes, tools, memory, agent
├── retrieval/                 # loaders, chunking, embeddings, vectorstore
├── airflow/
│   ├── Dockerfile
│   └── dags/renewal_flagging_dag.py
├── scripts/                   # smoke_test.py, chatbot tests
├── docker-compose.yml         # backend + airflow
├── Dockerfile
└── pyproject.toml / uv.lock
```
 
---
 
## Getting started
 
### Prerequisites
- Docker Desktop with Docker Compose
- [`uv`](https://docs.astral.sh/uv/) and Python 3.13 (for running Streamlit locally)
- A MongoDB Atlas cluster (free M0 works)
- A Groq API key and a Google AI Studio API key
- SMTP credentials (for example a Gmail App Password)
### 1. Clone and configure
 
```bash
git clone https://github.com/Hamza786110/VendorPulse.git
cd VendorPulse
```
 
Create a `.env` file in the project root:
 
```env
# Database
MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>/...
MONGODB_DB_NAME=contractguard
 
# Auth
JWT_SECRET_KEY=change-me
 
# LLM / embeddings
GROQ_API_KEY=...
GOOGLE_API_KEY=...
# CHATBOT_MODEL=...              # optional override
# CHATBOT_REASONING_EFFORT=none  # optional
# MAX_EXTRACTION_CHARS=...       # optional
 
# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=...
FRONTEND_RESET_URL=http://localhost:8501
 
# Airflow
AIRFLOW_API_USER=vp_api
AIRFLOW_API_PASSWORD=change-me
```
 
### 2. Start the backend and Airflow
 
```bash
docker compose up --build
```
 
| Service | URL |
|---|---|
| FastAPI backend (container `contractguard-backend`) | http://localhost:8001 (docs at `/docs`) |
| Airflow (container `contractguard-airflow`) | http://localhost:8080 |
 
The backend is mapped to host port **8001** to avoid colliding with a local `uvicorn` on 8000. Airflow is resource-heavy, so give Docker Desktop enough CPU and RAM.
 
### 3. Run the frontend
 
```bash
uv sync
uv run streamlit run app.py
```
 
The UI talks to `API_BASE_URL` (default `http://localhost:8001`).
 
### 4. Smoke test (optional)
 
With `docker compose up` running:
 
```bash
TEST_EMAIL=you@example.com python scripts/smoke_test.py path/to/contract.pdf
```
 
It walks through signup, upload, indexing, extraction, the Airflow run, a semantic question and stats. Use your own inbox for `TEST_EMAIL`, since the app sends real emails.
 
---
 
## Known limitations
 
- Semantic chunking works well on prose but can fragment tables and structured sections into weak chunks, so retrieval on those parts may be poor.
- Gmail SMTP is fine for development, but reset emails tend to land in spam. A transactional provider (Postmark, SendGrid) is the production path.
- The password-reset link points to `localhost` by default, which doesn't work across devices without a LAN IP or tunnel.
- The `chroma_db/` folder and a sample uploaded PDF are committed to the repo. They should be gitignored.
- Next.js frontend and Render/Vercel deployment are planned but not done.
## Roadmap
 
- Deploy backend and Airflow (Render) and decide on the long-term frontend
- Production email delivery
- In-app alerts view alongside email
- Retrieval quality improvements for tabular contract content
---
