# Tanveer Associates AI Assistant

A production-ready **RAG + lead-management AI Assistant** for **Tanveer Associates**, a real estate developer in Islamabad, Pakistan. Built with LangChain, LangGraph, ChromaDB, FastAPI, and PostgreSQL — with **Facebook Messenger**, **WhatsApp Business**, and an embeddable **web chat widget**.

## Features

- **RAG Pipeline** — Retrieves accurate company information from a ChromaDB vector store
- **LangGraph Tool-Calling Agent** — an explicit `agent` ⟷ `tools` (`ToolNode`) loop that reasons and retrieves before answering, instead of a black-box prebuilt agent
- **No Hallucination** — answers company questions only from the knowledge base
- **Lead Qualification** — captures and stages leads (property type, budget, financing, call time) using the business's own qualification rules, per platform
- **Persistent Memory** — every conversation is remembered across turns (PostgreSQL-backed), not just per-request
- **REST API** — FastAPI backend serving all channels from one process
- **Web Chat Widget** — lightweight embeddable HTML/JS chat window
- **Facebook Messenger** — automated replies via Facebook Page webhook
- **WhatsApp Business** — automated replies via WhatsApp Cloud API webhook
- **Modular Design** — each concern (memory, RAG, leads, channels) lives in its own package

## Project Structure

```
tanveer-associates-ai-agent/
│
├── app/
│   ├── main.py                     # FastAPI app: mounts all routers + admin routes
│   └── settings.py                 # All environment variables in one place
│
├── conversation_layer/
│   ├── graph.py                    # LangGraph StateGraph: agent <-> tools loop, run_turn()
│   ├── state.py                    # AgentState schema
│   ├── tools.py                    # search_knowledge_base, save_lead_info, escalate_to_human
│   └── system_prompt.py            # Persona + lead-qualification flow instructions
│
├── webhook/
│   ├── whatsapp_webhook.py         # WhatsApp Cloud API verification + incoming messages
│   ├── messenger_webhook.py        # Facebook Messenger verification + incoming messages
│   ├── web_chat_webhook.py         # /chat endpoint for the web widget
│   └── message_sender.py           # Outbound send functions (WhatsApp + Messenger)
│
├── knowledge_base/
│   ├── company_data.py             # Company knowledge base (31 categories, 309 facts)
│   ├── vector_store.py             # ChromaDB build/load/rebuild
│   └── retriever.py                # RAG retrieval + context formatting
│
├── memory/
│   ├── short_term_memory.py        # LangGraph PostgresSaver — conversation history
│   └── long_term_memory.py         # PostgreSQL leads/CRM store
│
├── lead_intelligence/
│   ├── lead_scoring.py             # Platform-aware lead stage classifier
│   └── lead_schema.py              # Lead data model
│
├── schema/
│   └── api_schema.py               # Pydantic request/response models
│
├── jobs/
│   └── rebuild_knowledge_base_job.py  # CLI: reindex the vector store
│
├── reporting/
│   ├── leads_report.py             # Email notification when lead contact details are complete
│   └── email_module.py             # SMTP delivery
│
├── frontend/
│   └── index.html                  # Web chat widget
│
├── data/                            # Chroma vector store + CSV exports (git-ignored)
├── run_server.py                    # Entry point: python run_server.py
├── requirements.txt
├── .env
├── .gitignore
└── README.md
```

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd tanveer-associates-ai-agent
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` in the project root and fill it in:

```env
# OpenAI (Required)
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0.2

# Shared webhook verification token
VERIFY_TOKEN=my_secret_verify_2024

# WhatsApp Cloud API (Required for WhatsApp)
WHATSAPP_TOKEN=your_whatsapp_token_here
WHATSAPP_PHONE_NUMBER_ID=your_whatsapp_phone_number_id_here

# Facebook Messenger (Required for Messenger)
PAGE_ACCESS_TOKEN=your_facebook_page_access_token_here

# PostgreSQL (Required — conversation memory + leads/CRM store)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/tanveer_associates

# Chroma vector store location (local disk)
CHROMA_DB_PATH=data/chroma_db

# Optional: email an alert when a new CRM lead is created
SMTP_SERVER=
SMTP_PORT=587
SMTP_SENDER=
SMTP_PASSWORD=
```

> **Important:** Replace all placeholder values with your actual credentials.
> Port `465` uses SMTP over SSL; other configured ports use STARTTLS.
> The report recipient is currently configured in `reporting/leads_report.py`.
> A notification is sent once required contact details are complete: WhatsApp requires a name; Messenger and web chat require a name and phone. Email is optional. Ordinary messages do not trigger email.

### 5. Create the database and build the knowledge base

```bash
createdb tanveer_associates
python -m jobs.rebuild_knowledge_base_job
```

Both the `leads` table and LangGraph's checkpoint tables are created automatically the first time the app runs — no manual migrations needed.

---

## Running the Application

Everything — web chat, WhatsApp, and Messenger — runs from a single FastAPI process:

```bash
python run_server.py

# OR

uvicorn app.main:app --reload
```

| Method | Endpoint               | Description                                     |
| ------ | ---------------------- | ----------------------------------------------- |
| GET    | `/`                  | Health check                                    |
| POST   | `/chat`              | Send a message, get an AI reply (web widget)    |
| GET    | `/widget`            | Serves the embeddable web chat widget           |
| POST   | `/admin/reindex`     | Rebuild the vector database                     |
| GET    | `/admin/leads`       | List captured leads (JSON, optional`?stage=`) |
| GET    | `/webhook/whatsapp`  | WhatsApp Cloud API verification                 |
| POST   | `/webhook/whatsapp`  | Incoming WhatsApp messages                      |
| GET    | `/webhook/messenger` | Facebook Messenger verification                 |
| POST   | `/webhook/messenger` | Incoming Messenger messages                     |

**Expose your server to the internet** (for webhook testing):

```bash
ngrok http 8000
```

Copy the HTTPS URL it gives you (e.g., `https://abc123.ngrok-free.app`).

---

## Facebook Messenger Setup

### 1. Create a Facebook App

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a new app → select **Business** type
3. Add the **Messenger** product

### 2. Get Page Access Token

1. In your app dashboard, go to **Messenger** → **Settings**
2. Connect a Facebook Page
3. Generate a **Page Access Token**
4. Copy it to `.env` as `PAGE_ACCESS_TOKEN`

### 3. Configure Webhook

1. In **Messenger** → **Settings** → **Webhooks**
2. Click **Add Callback URL**
3. Enter:
   - **Callback URL:** `https://your-domain.com/webhook/messenger`
   - **Verify Token:** the value you set for `VERIFY_TOKEN` in `.env`
4. Subscribe to: `messages`, `messaging_postbacks`

### 4. Test

Send a message to your Facebook Page — the AI will reply automatically.

---

## WhatsApp Business Setup

### 1. Create a Meta Business App

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a new app → select **Business** type
3. Add the **WhatsApp** product

### 2. Get WhatsApp Credentials

1. Go to **WhatsApp** → **API Setup**
2. Copy the **Temporary Access Token** → `WHATSAPP_TOKEN` in `.env`
3. Copy the **Phone Number ID** → `WHATSAPP_PHONE_NUMBER_ID` in `.env`

### 3. Configure Webhook

1. In **WhatsApp** → **Configuration** → **Webhooks**
2. Click **Edit**
3. Enter:
   - **Callback URL:** `https://your-domain.com/webhook/whatsapp`
   - **Verify Token:** the value you set for `VERIFY_TOKEN` in `.env`
4. Subscribe to: `messages`

### 4. Test

Send a WhatsApp message to your business number — the AI will reply automatically.

---

## Environment Variables

| Variable                                    | Description                                | Default                   |
| ------------------------------------------- | ------------------------------------------ | ------------------------- |
| `OPENAI_API_KEY`                          | OpenAI API key (required)                  | —                        |
| `OPENAI_MODEL`                            | LLM model name                             | `gpt-4o-mini`           |
| `OPENAI_TEMPERATURE`                      | Response creativity (0-1)                  | `0.2`                   |
| `VERIFY_TOKEN`                            | Shared Meta webhook verification token     | `my_secret_verify_2024` |
| `WHATSAPP_TOKEN`                          | WhatsApp Cloud API token                   | —                        |
| `WHATSAPP_PHONE_NUMBER_ID`                | WhatsApp phone number ID                   | —                        |
| `PAGE_ACCESS_TOKEN`                       | Facebook Page access token                 | —                        |
| `DATABASE_URL`                            | PostgreSQL connection string (required)    | —                        |
| `CHROMA_DB_PATH`                          | ChromaDB storage directory                 | `data/chroma_db`        |
| `HANDOFF_NOTIFY_WEBHOOK_URL`              | Optional webhook to alert on human handoff | —                        |
| `SMTP_SERVER` / `SMTP_PORT`              | SMTP server and port for new-lead alerts    | — / `587`                 |
| `SMTP_SENDER` / `SMTP_PASSWORD`          | SMTP login and sender email credentials     | —                         |

## Knowledge Base

The knowledge base contains **31 categories** (309 individual facts) of company information:

- Company Overview & About, CEO & Leadership, Miusam Construction (Subsidiary)
- On-Going, In-Finishing, and Delivered Projects, All Projects Summary
- Services (Construction, Interior, Design, Consultation)
- Communities (Faisal Town Phase 1 & 2, Faisal Hills)
- Project Amenities & Features (Apollo Towers II, Casablanca)
- Payment Plans & Investment Information
- Contact Information & Social Media Links
- Key Statistics, Apartment Types, Project Locations
- Company-Specific FAQs, Blog & Content, Team
- **Lead Qualification Questions** — the sales playbook that drives `lead_intelligence/lead_scoring.py`

## Architecture

```
                    ┌───────────────────┐
                    │   FastAPI (app)   │
                    │    run_server.py  │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──┐   ┌────────▼───┐   ┌───────▼─────┐
    │ Web Widget │   │  WhatsApp  │   │  Messenger  │
    │  /chat     │   │ /webhook/  │   │  /webhook/  │
    │            │   │ whatsapp   │   │  messenger  │
    └─────────┬──┘   └────────┬───┘   └───────┬─────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  conversation_    │
                    │  layer.run_turn() │
                    └─────────┬─────────┘
                              │
                 ┌────────────┼────────────┐
                 │            │            │
       ┌─────────▼──┐ ┌───────▼───┐ ┌──────▼──────┐
       │  ChromaDB  │ │ PostgreSQL│ │ PostgreSQL  │
       │   (RAG)    │ │ (memory)  │ │ (leads/CRM) │
       └────────────┘ └───────────┘ └─────────────┘
```

## Tech Stack

| Component           | Technology                                  |
| ------------------- | ------------------------------------------- |
| Backend API         | FastAPI                                     |
| Web Frontend        | Static HTML/JS chat widget                  |
| AI Framework        | LangChain + LangGraph                       |
| Agent Type          | Explicit tool-calling graph (`ToolNode`)  |
| Vector Database     | ChromaDB                                    |
| Conversation Memory | PostgreSQL (LangGraph`PostgresSaver`)     |
| Leads/CRM Store     | PostgreSQL (`psycopg` + `psycopg_pool`) |
| Embeddings          | OpenAI Embeddings                           |
| LLM                 | OpenAI GPT (configurable)                   |
| HTTP Client         | httpx (async)                               |
| Messenger           | Facebook Graph API                          |
| WhatsApp            | WhatsApp Cloud API                          |
| Language            | Python                                      |

## License

© 2026 Tanveer Associates. All rights reserved.
