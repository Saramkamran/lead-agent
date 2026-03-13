# AI Lead Generation Agent — Build Prompt

## CONTEXT & ROLE

You are a senior full-stack engineer building a focused, production-quality AI lead
generation platform. This is scoped to be completable in 3–4 sessions.

No unnecessary complexity. Every feature must earn its place.
Build each phase completely before moving to the next.

---

## WHAT THIS SYSTEM DOES

1. Import leads via CSV or manual entry
2. Score leads automatically using rule-based logic
3. Generate personalized outreach emails using OpenAI
4. Send emails via Brevo (formerly Sendinblue)
5. Detect replies and classify intent (positive / neutral / not interested)
6. Hold simple AI conversations to book meetings
7. Display everything in a clean dashboard

---

## TECH STACK (LOCKED)

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI |
| AI | OpenAI GPT-4o-mini (scoring/offers/messages) + GPT-4o (conversations only) |
| Database | PostgreSQL via SQLAlchemy 2.0 async + Alembic |
| Background jobs | APScheduler (runs inside FastAPI process) |
| Email | Brevo Transactional Email API v3 |
| Frontend | Next.js 14, TypeScript, Tailwind CSS, shadcn/ui |
| Auth | JWT via python-jose, bcrypt password hashing |
| Deployment | Supabase (PostgreSQL) + Render (backend) + Vercel (frontend) — all free tier |

---

## PROJECT STRUCTURE

Scaffold this exact layout before writing any code:

```
/lead-agent
  /backend
    /app
      /api          # Route handlers
      /models       # SQLAlchemy ORM models
      /schemas      # Pydantic schemas
      /services     # Business logic (ai, email, scoring)
      /jobs         # APScheduler background tasks
      /core         # Config, auth, dependencies
    /alembic
    /tests
    main.py
    requirements.txt
    Dockerfile        # Render needs this
  /frontend
    /app
    /components
    /lib
    /hooks
  setup.sh            # Local dev setup script
  .env.example
  CLAUDE.md           # Project context for future sessions
  README.md
```

---

## DATABASE SCHEMA

Implement with SQLAlchemy ORM models + one Alembic migration.

```sql
leads (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         VARCHAR(255) UNIQUE NOT NULL,
  first_name    VARCHAR(100),
  last_name     VARCHAR(100),
  company       VARCHAR(255),
  title         VARCHAR(255),
  website       VARCHAR(255),
  industry      VARCHAR(100),
  company_size  VARCHAR(50),
  source        VARCHAR(50) DEFAULT 'csv',
  status        VARCHAR(50) DEFAULT 'imported',
  -- Status flow: imported → scored → contacted → replied → booked → closed
  score         INTEGER,
  score_reason  TEXT,
  custom_offer  TEXT,
  created_at    TIMESTAMP DEFAULT NOW()
)

messages (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id             UUID REFERENCES leads(id) ON DELETE CASCADE,
  type                VARCHAR(50),   -- cold_email, followup_1, followup_2
  subject             VARCHAR(500),
  body                TEXT,
  status              VARCHAR(50) DEFAULT 'pending',  -- pending, sent, opened, clicked
  sent_at             TIMESTAMP,
  provider_message_id VARCHAR(255),  -- Brevo message ID
  created_at          TIMESTAMP DEFAULT NOW()
)

conversations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id     UUID REFERENCES leads(id) ON DELETE CASCADE,
  status      VARCHAR(50) DEFAULT 'active',  -- active, booked, closed
  sentiment   VARCHAR(50),                   -- positive, neutral, negative
  thread      JSONB DEFAULT '[]',            -- [{role, content, timestamp}]
  created_at  TIMESTAMP DEFAULT NOW(),
  updated_at  TIMESTAMP DEFAULT NOW()
)

campaigns (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                VARCHAR(255) NOT NULL,
  status              VARCHAR(50) DEFAULT 'draft',  -- draft, active, paused
  sender_name         VARCHAR(100),
  sender_email        VARCHAR(255),
  sender_company      VARCHAR(255),
  daily_limit         INTEGER DEFAULT 30,
  min_score           INTEGER DEFAULT 50,
  target_industry     VARCHAR(100),
  calendly_link       VARCHAR(500),
  created_at          TIMESTAMP DEFAULT NOW()
)
```

---

## ENGINEERING RULES

These apply to every file:

1. **Use GPT-4o-mini for everything except conversations.** Conversations use GPT-4o.
2. **Never use LLMs for scoring.** Use the rule engine defined in Phase 2.
3. **Cache AI outputs.** Store generated messages in the DB — never regenerate the same lead twice.
4. **Explicit max_tokens on every OpenAI call.** No open-ended generation.
5. **All secrets via environment variables.** Never hardcoded anywhere in the codebase.
6. **Every endpoint returns structured errors:**
   `{ "error": "message", "code": "ERROR_CODE" }`
7. **Every background job logs its activity** to stdout with timestamps.

---

## PHASE 1 — BACKEND CORE

Build in this order. Fully implement each before moving to the next.

### 1.1 Setup
- FastAPI app factory with: CORS middleware, request logging middleware, global error handler
- SQLAlchemy async engine + session dependency injection
- Alembic configured for async PostgreSQL (asyncpg driver)
- Migration for all 4 tables above
- `GET /health` → `{ "status": "ok", "db": "ok" }`
- `requirements.txt` with all pinned versions

### 1.2 Auth
- `POST /auth/register` — email + password, bcrypt hash, store user
- `POST /auth/login` → returns `{ "access_token": "...", "token_type": "bearer" }`
- JWT bearer middleware — validates `Authorization: Bearer <token>` on all protected routes
- Token expiry: 8 hours
- Single user per deployment is fine

### 1.3 Lead API
- `POST /leads/import` — accept multipart CSV upload, validate emails, skip duplicates, bulk insert, return `{ imported: N, skipped: N, errors: [] }`
- `GET /leads` — paginated (page, page_size), filter by status, min_score
- `GET /leads/{id}` — full detail including related messages and conversation
- `PATCH /leads/{id}` — update any field
- `DELETE /leads/{id}` — hard delete
- `GET /leads/stats` — returns count per status for pipeline view

**CSV format to accept:**
```csv
email,first_name,last_name,company,title,website,industry,company_size
sarah@acme.com,Sarah,Johnson,Acme Corp,VP Operations,acmecorp.com,Real Estate,50-200
mike@proptech.io,Mike,Chen,PropTech,CEO,,SaaS,1-10
```

### 1.4 Campaign API
- `POST /campaigns` — create with all fields
- `GET /campaigns` — list with lead counts per campaign
- `GET /campaigns/{id}` — full detail
- `PATCH /campaigns/{id}` — update (block edits if status=active)
- `POST /campaigns/{id}/start` — validate config, set status=active
- `POST /campaigns/{id}/pause` — set status=paused

---

## PHASE 2 — AI SERVICES

All AI logic lives in `/backend/app/services/`. No external microservices.

### `scoring_service.py` — NO LLM for score calculation

```python
SCORE_WEIGHTS = {
    "company_size": {
        "500+": 30,
        "100-499": 25,
        "50-200": 18,
        "10-49": 10,
        "1-10": 5,
        "": 5
    },
    "title_seniority": {
        # Check these keyword groups against the title field (case-insensitive)
        "founder|ceo|owner|president": 30,
        "vp|vice president|director": 25,
        "manager|head of|lead": 15,
        "default": 8
    },
    "industry_fit": {
        # Compare lead.industry to campaign.target_industry
        "exact_match": 20,
        "no_match": 0
    },
    "has_website": 10,  # +10 if website field is populated
    "has_linkedin": 5   # +5 if linkedin_url field is populated
}
# Total possible = 100
```

After calculating the numeric score, call `gpt-4o-mini` ONLY to generate
`score_reason` — a single sentence explaining the score. Max 40 tokens.

Store score + reason in `leads.score` and `leads.score_reason`.

### `offer_service.py`

Generate a 1-sentence value proposition per lead.

**Caching rule:** If a lead with the same `industry + title + company_size`
already has an offer in the database, copy it — skip the API call entirely.

**Prompt:**
```
Write one sentence. Format: "We help [role] at [company type] to [specific outcome]."
Role: {title} | Industry: {industry} | Size: {company_size}
Max 25 words. No filler words. Be specific.
```

Model: `gpt-4o-mini`. Max tokens: 60.

Store result in `leads.custom_offer`.

### `message_service.py`

Generate all 3 messages in a single API call. Model: `gpt-4o-mini`.

**System prompt:**
```
You write cold outreach emails. Be direct, human, and brief.
Never start with "I hope this finds you well." No fluff.
Lead with a specific pain point relevant to their industry and role.
Return valid JSON only — no markdown, no explanation outside the JSON.
```

**User prompt:**
```
Generate 3 outreach emails for this lead.

Lead: {first_name} {last_name}, {title} at {company} ({industry}, {company_size})
Offer: {custom_offer}
Sender: {sender_name}, {sender_company}
Calendly booking link: {calendly_link}

Return this exact JSON structure:
{
  "cold_email": {
    "subject": "...",
    "body": "..."
  },
  "followup_1": {
    "subject": "Re: [original subject]",
    "body": "..."
  },
  "followup_2": {
    "subject": "Re: [original subject]",
    "body": "..."
  }
}

cold_email body: max 100 words.
followup_1 body: max 60 words. Reference the previous email briefly.
followup_2 body: max 50 words. Final nudge, low pressure.
Include the Calendly link only in followup_1 and followup_2.
```

Max tokens: 600. Parse JSON response, store all 3 as rows in `messages` table
with status=pending.

**Never call this if messages already exist for the lead.**

### `conversation_service.py`

Two functions:

**1. `classify_intent(reply_text: str) -> str`**
Model: `gpt-4o-mini`. Max tokens: 5.
```
Classify this email reply as exactly one word: positive, neutral, or negative.
Reply: {reply_text}
```

**2. `generate_reply(conversation: Conversation, lead: Lead, campaign: Campaign) -> str`**
Model: `gpt-4o`. Max tokens: 150.

System prompt:
```
You are {sender_name} from {sender_company}.
You are having an email conversation with {lead_first_name}, {lead_title} at {lead_company}.
Your goal is to book a 30-minute discovery call.
Calendly link: {calendly_link}

Rules:
- Maximum 3 sentences per reply
- Be warm and human, never pushy or salesy
- If they want to meet: share the Calendly link in this reply
- If they say they are not interested: thank them politely, wish them well, end the conversation
- Never mention that you are an AI
- Do not repeat information already covered in the thread

Last 4 messages from the thread:
{last_4_messages}
```

User prompt: `Their latest reply: {latest_reply}\n\nYour response:`

After generating, append both the inbound reply and the AI response to
`conversations.thread` and send the reply via the email service.

---

## PHASE 3 — EMAIL + BACKGROUND JOBS

### `email_service.py`

Use `httpx` (async) to call the Brevo REST API directly. No SDK required.

**Brevo API details:**
- Endpoint: `POST https://api.brevo.com/v3/smtp/email`
- Auth header: `api-key: {BREVO_API_KEY}` (not a Bearer token)
- Content-Type: `application/json`

**Request payload shape:**
```json
{
  "sender": { "name": "Your Name", "email": "you@yourdomain.com" },
  "to": [{ "email": "lead@example.com", "name": "Lead Name" }],
  "subject": "Your subject here",
  "textContent": "Plain text body here"
}
```

**Functions to implement:**

`send_email(to_email, to_name, subject, body, from_email, from_name) -> str`
- POST to Brevo API with the payload above
- On success: extract `messageId` from response JSON, store in `messages.provider_message_id`, return the message ID
- On failure: log the full error response with timestamp, mark `messages.status = 'failed'`, do NOT raise (background jobs must continue)

**Note:** `htmlContent` can be used instead of `textContent` if you want to send HTML emails. For this project, use `textContent` for simplicity and deliverability.

### Webhook endpoints

`POST /webhooks/brevo/events` — handle Brevo transactional email event webhooks.

Brevo sends a JSON payload per event. The relevant fields are:
- `event` — string, e.g. `"opened"`, `"clicked"`, `"delivered"`, `"hard_bounce"`, `"soft_bounce"`
- `email` — the recipient's email address
- `messageId` — matches `messages.provider_message_id`
- `date` — ISO timestamp

Event handling:
- `opened` → find message by `provider_message_id`, update `messages.status = 'opened'`
- `clicked` → update `messages.status = 'clicked'`
- `hard_bounce` or `soft_bounce` → update `messages.status = 'bounced'`, update `leads.status = 'bounced'`
- All other events → log and ignore

Configure this webhook URL in the Brevo dashboard under:
**Transactional → Settings → Webhook → Add a new webhook**
URL: `https://your-app.onrender.com/webhooks/brevo/events`
Select events: Delivered, Opened, Clicked, Hard bounce, Soft bounce

`POST /webhooks/brevo/inbound` — handle Brevo inbound email parsing.

Brevo inbound parsed email payload fields (note: different from SendGrid):
- `From` — sender email address string, e.g. `"John Smith <john@example.com>"`
- `Subject` — email subject string
- `TextBody` — plain text body of the reply
- `To` — recipient address

Parsing steps:
1. Extract sender email from `From` field (handle both `name <email>` and bare `email` formats)
2. Extract plain text from `TextBody`
3. Find lead by matching sender email against `leads.email`
4. Call `classify_intent(TextBody)`
5. If positive or neutral:
   - Create `conversations` record with first thread entry
   - Call `generate_reply()`
   - Send reply via `email_service`
   - Update `leads.status = 'replied'`
6. If negative:
   - Update `leads.status = 'not_interested'`

Configure inbound parsing in the Brevo dashboard under:
**Transactional → Settings → Inbound parsing**
URL: `https://your-app.onrender.com/webhooks/brevo/inbound`

### Background Jobs (APScheduler)

Start scheduler when FastAPI starts. Three jobs:

**Job 1: Score new leads**
- Schedule: every 10 minutes
- Find leads where `status='imported'` and `score IS NULL`
- For each: calculate score → generate offer → update status to `scored`
- Batch size: max 50 per run

**Job 2: Send daily outreach**
- Schedule: daily at 9:00 AM (use timezone from env var, default UTC)
- Find active campaigns
- For each campaign: find `scored` leads where `score >= campaign.min_score`
  and `status='scored'`
- Respect `campaign.daily_limit` — count emails already sent today
- For each eligible lead: generate messages (if not generated) → send cold_email
  → update `leads.status = 'contacted'`

**Job 3: Send follow-ups**
- Schedule: daily at 9:30 AM
- Find leads where `status='contacted'`
- If `sent_at < now() - 3 days` and no followup_1 sent → send followup_1
- If `sent_at < now() - 7 days` and no followup_2 sent → send followup_2
- Skip leads where `status` is `replied`, `booked`, or `not_interested`

---

## PHASE 4 — FRONTEND DASHBOARD

Next.js 14 App Router, TypeScript, Tailwind CSS, shadcn/ui.

### Pages:

**`/` → redirect to `/dashboard`**

**`/login`**
- Email + password form
- On success: store JWT in localStorage, redirect to `/dashboard`
- On fail: show error message

**`/dashboard`**
- 4 stat cards: Total Leads, Contacted This Week, Replied, Meetings Booked
- Lead status pipeline: horizontal bar showing count at each stage
  (Imported → Scored → Contacted → Replied → Booked)

**`/leads`**
- Searchable, filterable table
- Columns: Name, Company, Title, Score (badge), Status, Date Added, Actions
- Score badge colors: green ≥70, yellow 50–69, red <50, grey = unscored
- Top bar: "Import CSV" button → modal with drag-and-drop file input
- Click any row → slide-over panel showing:
  - Lead details (all fields, editable inline)
  - Score breakdown (visual bar per scoring category)
  - Sent messages (subject, sent date, status)
  - Conversation thread (if exists)

**`/campaigns`**
- Table: Name, Status, Leads, Sent, Reply Rate, Actions
- "New Campaign" button → modal with all campaign fields
- Campaign row actions: View, Start, Pause, Edit
- Campaign detail page: stats + list of assigned leads + Start/Pause button

**`/conversations`**
- List: lead name, company, sentiment badge, last message preview, date
- Click → full thread view styled like an email client (alternating left/right bubbles)
- "Take over" button — disables AI for this thread, enables manual reply input

### API client `/frontend/lib/api.ts`
- Typed `apiFetch` wrapper using native `fetch`
- Auto-attaches `Authorization: Bearer <token>` from localStorage
- On 401: clear token, redirect to `/login`
- All response types as TypeScript interfaces matching backend Pydantic schemas
- Exported functions for every endpoint: `getLeads()`, `importLeads()`,
  `getCampaigns()`, `createCampaign()`, `getConversations()`, etc.

---

## PHASE 5 — DEPLOYMENT

### Local Development Setup

**Prerequisites:**
- PostgreSQL 15 (postgresql.org) — create a database named `leadgen`
- Python 3.11 (pyenv recommended)
- Node.js 18+ (nvm recommended)

Generate a `setup.sh` in the project root:
```bash
#!/bin/bash
echo "Setting up backend..."
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

echo "Setting up frontend..."
cd frontend
npm install
cd ..

echo "Copying env file..."
cp .env.example .env
echo "Done. Fill in .env then run:"
echo "  cd backend && alembic upgrade head"
echo "  cd backend && uvicorn main:app --reload --port 8000"
echo "  cd frontend && npm run dev"
```

### Production Deployment (Free Tier)

**Database — Supabase (free, never sleeps)**
1. Create account at supabase.com → New Project
2. Settings → Database → copy Connection String (URI)
3. Replace `postgresql://` with `postgresql+asyncpg://`
4. Run migrations from local: `alembic upgrade head`

**Backend — Render (free, 512MB RAM)**
1. Push repo to GitHub
2. render.com → New Web Service → connect repo
3. Settings:
   - Root Directory: `backend`
   - Runtime: Python 3.11
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add all env variables from `.env` in Render's Environment tab
5. Deploy → note your URL: `https://your-app.onrender.com`

Note: Render free tier spins down after 15 minutes of inactivity.
First request after sleep takes ~30 seconds. Acceptable for active use.

**Frontend — Vercel (free, unlimited)**
1. vercel.com → New Project → import same GitHub repo
2. Set Root Directory to `frontend`
3. Add environment variable:
   `NEXT_PUBLIC_API_URL = https://your-app.onrender.com`
4. Deploy → note your URL: `https://your-app.vercel.app`

**Brevo webhook configuration:**
- Go to Brevo dashboard → Transactional → Settings
- **Webhook (event tracking):**
  URL: `https://your-app.onrender.com/webhooks/brevo/events`
  Events to enable: Delivered, Opened, Clicked, Hard bounce, Soft bounce
- **Inbound parsing:**
  URL: `https://your-app.onrender.com/webhooks/brevo/inbound`

### `.env.example`

```env
# PostgreSQL (Supabase in production, local postgres in dev)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/leadgen

# Auth
JWT_SECRET=generate-with-openssl-rand-hex-32
JWT_EXPIRE_HOURS=8

# OpenAI
OPENAI_API_KEY=sk-...

# Brevo (formerly Sendinblue)
BREVO_API_KEY=xkeysib-...
BREVO_FROM_EMAIL=you@yourdomain.com
BREVO_FROM_NAME=Your Name

# App URLs
BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://localhost:8000

# Scheduler timezone (e.g. America/New_York, Europe/London, Asia/Karachi)
SCHEDULER_TIMEZONE=UTC
```

---

## PHASE 6 — TESTS

```
/backend/tests/
  test_lead_import.py     — CSV parsing, dedup, validation edge cases
  test_scoring.py         — All scoring rule combinations, verify no LLM called
  test_message_gen.py     — Mock OpenAI, verify caching (no duplicate API calls)
  test_reply_webhook.py   — Intent classification routing (positive/neutral/negative)
  test_auth.py            — Register, login, JWT expiry, protected route rejection
  test_email_service.py   — Mock httpx, verify Brevo API payload shape and header format
```

Use `pytest` + `pytest-asyncio` + `httpx.AsyncClient`.
Mock all external services (OpenAI, Brevo API) using `unittest.mock.patch`.

For `test_email_service.py`, verify:
- The `api-key` header is set correctly (not `Authorization: Bearer`)
- The payload contains `sender`, `to`, `subject`, `textContent`
- `provider_message_id` is extracted from the response and stored
- On API failure, status is set to `failed` and no exception propagates

---

## CLAUDE.md FILE

Create this file at the project root after Phase 1 so future sessions can
orient quickly without re-reading all the code:

```markdown
# Lead Agent — Project Context

## What this is
AI lead generation system: import leads → score → personalize emails →
send → detect replies → AI conversation → book meetings.

## Stack
- Backend: FastAPI + SQLAlchemy async + APScheduler (port 8000)
- Frontend: Next.js 14 App Router (port 3000)
- Database: PostgreSQL (Supabase in prod, local in dev)
- AI: OpenAI GPT-4o-mini (scoring/messages) + GPT-4o (conversations)
- Email: Brevo Transactional Email API v3 (httpx, no SDK)

## Key architectural decisions
- No Docker, no Redis, no message queue
- APScheduler runs inside the FastAPI process
- AI outputs cached in DB — never regenerate existing leads
- Scoring is 100% rule-based (no LLM)
- Single user auth (JWT, 8hr expiry)
- Brevo API auth uses `api-key` header, NOT `Authorization: Bearer`
- Brevo inbound webhook fields: `From`, `Subject`, `TextBody` (not SendGrid format)
- messages table uses `provider_message_id` column (not `sendgrid_id`)

## File map
- /backend/app/services/scoring_service.py — rule-based lead scoring
- /backend/app/services/message_service.py — OpenAI message generation
- /backend/app/services/conversation_service.py — reply handling + AI chat
- /backend/app/services/email_service.py — Brevo sending via httpx
- /backend/app/jobs/ — APScheduler background jobs
- /backend/app/api/ — FastAPI route handlers
- /frontend/lib/api.ts — typed API client

## Environment
Copy .env.example to .env and fill in values before running.
Run migrations: cd backend && alembic upgrade head
```

---

## BUILD ORDER

```
Phase 1 → Backend core + DB + auth + lead API
          Verify: curl /health returns ok, import sample CSV, check DB rows

Phase 2 → AI services (scoring → offer → messages → conversation)
          Verify: score 5 leads manually, check offers cached, generate message set

Phase 3 → Email sending + background jobs + webhooks
          Verify: trigger scoring job manually, send test email via Brevo sandbox

Phase 4 → Frontend dashboard
          Verify: all pages load, CSV import works end-to-end in browser

Phase 5 → Deploy to Supabase + Render + Vercel
          Verify: production URLs live, migrations ran, frontend hits prod API

Phase 6 → Tests
          Verify: pytest -v passes with all mocks in place
```

After each phase confirm you are ready before proceeding.
No TODO comments. No placeholder functions. Every function fully implemented.

---

## SUCCESS CRITERIA

- [ ] Import 20 leads via CSV → all reach `scored` status within 10 minutes
- [ ] Start a campaign → leads above min_score receive personalized cold emails
- [ ] Simulate inbound reply → AI response generated and sent automatically
- [ ] All 4 dashboard pages load with real data, no console errors
- [ ] `alembic upgrade head` runs clean against Supabase with no errors
- [ ] Render deploy logs show `Application startup complete`
- [ ] Vercel frontend loads and successfully calls the Render backend API
- [ ] `pytest -v` passes with all external services mocked
- [ ] No API keys or secrets exist anywhere in the codebase

---

## SESSION STRATEGY

This project is designed for 3–4 Claude Code sessions on Pro:

- **Session 1:** Phase 1 (backend foundation)
- **Session 2:** Phases 2 + 3 (AI services + email jobs)
- **Session 3:** Phase 4 (frontend)
- **Session 4:** Phase 5 + 6 (deploy + tests)

Use /compact frequently within sessions to preserve context window.
