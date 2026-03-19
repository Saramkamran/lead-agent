# Lead Agent — Project Context

## What this is
AI lead generation system: import leads → scan website → score → generate SOP emails →
send via SMTP → detect replies via IMAP → AI conversation → book meetings.

Built for Blackbird. Sender identity is "Hassan from Blackbird".

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI |
| AI — conversations | OpenAI GPT-4o |
| AI — scoring reason / offer | OpenAI GPT-4o-mini |
| AI — website scanning | Anthropic Claude claude-haiku-4-5-20251001 (via `anthropic` SDK) |
| Database | PostgreSQL via SQLAlchemy 2.0 async + Alembic (hosted on Supabase) |
| Background jobs | APScheduler (runs inside FastAPI process) |
| Email sending | aiosmtplib — STARTTLS port 587 or SSL port 465 |
| Email receiving | aioimaplib IMAP polling loop — no webhooks |
| Frontend | Next.js 14 App Router, TypeScript, Tailwind CSS |
| Auth | JWT via python-jose, bcrypt |
| Deployment | Supabase (DB) + Render (backend) + Vercel (frontend) |

---

## Key Architecture Decisions

- **No global IMAP env vars used for polling.** The DB (`outreach_accounts` table) is the sole source of truth. Deleting an account from the UI stops polling it immediately.
- **SOP email templates, not AI generation.** All 4 outreach emails (cold + 3 followups) are hardcoded templates in `message_service.py`. No OpenAI calls for message body.
- **Website scanning before outreach.** New leads are scanned with Claude claude-haiku-4-5-20251001 to detect website problems (no booking, no pricing, weak CTA). The detected `hook_text` is injected into the cold email observation.
- **APScheduler runs inside the FastAPI process.** No Celery, no Redis, no external queue.
- **AI outputs cached in DB.** Messages, offers, and scans are never regenerated for the same lead.
- **Scoring is 100% rule-based.** No LLM used for score calculation. GPT-4o-mini only generates the `score_reason` sentence.
- **Multiple outreach accounts.** Each lead is assigned one `outreach_account_id`. SMTP sends and IMAP polling use per-account credentials. Passwords encrypted at rest with `APP_SECRET_KEY`.
- **Weekday-only sending.** Both outreach and followup jobs skip Saturday and Sunday.
- **7-category reply classification.** `interested | question | not_interested | unsubscribe | out_of_office | wrong_person | spam_complaint`
- **Booking response is a hardcoded template**, not AI-generated. Sent immediately when intent = `interested`. Calendar link is hardcoded in `scan_service.py` as `CALENDAR_LINK`.
- **Three-layer reply matching** to handle Gmail's Message-ID replacement: (1) In-Reply-To/References header correlation, (2) lead email + status fallback, (3) lead email + outbound email_log fallback.

---

## File Map

```
backend/
  main.py                               — App factory, IMAP poller loop, lifespan hooks
  app/
    api/
      auth.py                           — POST /auth/register, /auth/login
      campaigns.py                      — CRUD + start/pause
      conversations.py                  — List, get, patch, manual reply
      health.py                         — GET /health
      jobs.py                           — POST /jobs/outreach (manual trigger)
      leads.py                          — CRUD, CSV import, process endpoint, scan endpoints
      outreach_accounts.py              — CRUD + POST /test-connection
    core/
      auth.py                           — JWT middleware
      config.py                         — Settings (pydantic-settings, reads .env)
      crypto.py                         — encrypt_secret / decrypt_secret (Fernet)
      database.py                       — AsyncSessionLocal, get_db dependency
    jobs/
      scheduler.py                      — 5 APScheduler jobs (scan, score, outreach, followups, reset)
    models/
      campaign.py, conversation.py, email_log.py, lead.py,
      message.py, outreach_account.py, user.py, website_scan.py
    schemas/
      auth.py, campaign.py, lead.py, outreach_account.py
    services/
      conversation_service.py           — classify_intent (7 categories), generate_reply (GPT-4o)
      email_service.py                  — send_email (aiosmtplib), poll_imap_account (aioimaplib)
      message_service.py                — SOP template builder, generate_messages (cached)
      offer_service.py                  — 1-sentence offer via GPT-4o-mini (cached by industry+title+size)
      reply_handler.py                  — Matches inbound emails → classify → route → respond
      scan_service.py                   — fetch_pages (httpx), analyze_with_claude, scan_website
      scoring_service.py                — Rule-based score + GPT-4o-mini score_reason

frontend/
  app/
    dashboard/                          — Stats cards + status pipeline
    leads/                              — Table + slide-over (details, messages, scan, process button)
    campaigns/                          — name, daily_limit, min_score only
    conversations/                      — Thread view, take-over, manual reply
    outreach-accounts/                  — Add/edit/delete SMTP+IMAP accounts, test connection
  lib/api.ts                            — Typed fetch wrapper, all API functions
```

---

## Lead Status Flow

```
imported → scored → contacted → follow_up_1 → follow_up_2 → follow_up_3
                                     ↓ (reply)
                                   replied
                                     ↓
                          not_interested / disqualified / booked
```

Stop statuses (sequence halts): `replied`, `booked`, `not_interested`, `disqualified`, `follow_up_3`

---

## Scan Status Flow

```
pending → scanning → success   (hook_text injected into cold email)
                   → failed    (generic observation used instead)
                   → pending   (retry once on next 5-min cycle)
```

Scoring job skips leads with `scan_status IN ('pending', 'scanning')` — waits for scan first.

---

## Background Jobs (APScheduler)

| Job | Schedule | What it does |
|---|---|---|
| `job_scan_leads` | Every 5 min | Scans website of `imported` + `scan_status=pending` leads (batch 5) |
| `job_score_new_leads` | Every 10 min | Scores `imported` leads with no score (after scan attempted) |
| `job_send_daily_outreach` | 9:00 AM weekdays | Sends cold emails to `scored` leads above `min_score` |
| `job_send_followups` | 9:30 AM weekdays | Sends followup_1 (day 2), followup_2 (day 5), followup_3 (day 9) |
| `job_reset_daily_limits` | Midnight daily | Resets `leads_assigned = 0` on all outreach accounts |

---

## Email Sequence Timing

- **Cold email** — sent by outreach job
- **Followup 1** — 2 days after cold email
- **Followup 2** — 3 days after followup 1 (day 5 total)
- **Followup 3** ("Closing the loop") — 4 days after followup 2 (day 9 total)

---

## Reply Handling (7 intents)

| Intent | Action |
|---|---|
| `interested` | Auto-send hardcoded booking response with `CALENDAR_LINK`. Create conversation record. |
| `question` | Create/update conversation, generate AI reply via GPT-4o, send. |
| `not_interested` | Set `lead.status = 'not_interested'`. No reply sent. |
| `unsubscribe` | Set `lead.status = 'disqualified'`. No reply sent. |
| `spam_complaint` | Set `lead.status = 'disqualified'`. No reply sent. |
| `out_of_office` | Record `reply_category`. Do NOT change status — sequence pauses naturally. |
| `wrong_person` | Set `lead.status = 'replied'`, `reply_category = 'wrong_person'` for manual review. |

---

## Hardcoded Constants (scan_service.py)

```python
CALENDAR_LINK = "https://calendar.app.google/fSPntmSnuAu5dFKu6"
LOOM_VIDEO_LINK = "https://www.instagram.com/reel/DV1MBFrAiKY/..."
```

These are imported by `message_service.py`, `reply_handler.py`, and `conversation_service.py`.

---

## Multi-Account SMTP/IMAP

- Up to 5 outreach accounts (enforced in API)
- Accounts stored in `outreach_accounts` table; passwords encrypted with Fernet (`APP_SECRET_KEY`)
- IMAP poller queries the DB every `IMAP_POLL_INTERVAL_SECONDS` — only active accounts are polled
- Each lead is auto-assigned to the first active account with remaining daily capacity
- `leads_assigned` counter reset to 0 at midnight by `job_reset_daily_limits`
- `POST /outreach-accounts/{id}/test-connection` tests both SMTP and IMAP before saving

---

## Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://...

# Auth
JWT_SECRET=...
JWT_EXPIRE_HOURS=8
APP_SECRET_KEY=...          # Fernet key for encrypting SMTP passwords

# AI
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-... # Used for website scanning (Claude claude-haiku-4-5-20251001)

# Global SMTP fallback (used if a lead has no outreach_account_id)
SMTP_HOST=
SMTP_PORT=465
SMTP_USER=
SMTP_PASS=
SMTP_FROM_NAME=
SMTP_FROM_EMAIL=

# Global IMAP (no longer used for polling — kept for backwards compat)
IMAP_HOST=
IMAP_PORT=993
IMAP_USER=
IMAP_PASS=
IMAP_POLL_INTERVAL_SECONDS=60
IMAP_REPLY_FOLDER=INBOX

# Scheduler
SCHEDULER_TIMEZONE=UTC

# URLs
BACKEND_URL=https://your-app.onrender.com
NEXT_PUBLIC_API_URL=https://your-app.onrender.com
```

---

## Deployment

- **Database:** Supabase (PostgreSQL, never sleeps)
- **Backend:** Render (auto-deploys on push to `master` branch of `Saramkamran/lead-agent`)
- **Frontend:** Vercel (auto-deploys on push)
- **Keep Render alive:** UptimeRobot pinging `GET /health` every 5 minutes (free tier sleeps after 15 min)
- **Run migrations:** `cd backend && alembic upgrade head` (run locally against Supabase URL)

---

## Known Quirks

- **Gmail replaces Message-ID headers** on send — reply matching falls through to email+outbound-log fallback automatically.
- **Hostinger uses port 465** (implicit TLS), not 587 (STARTTLS). Set `smtp_port=465` and `imap_port=993`.
- **CSV import normalises headers** — accepts `Email`, `Contact Name`, `Domain`, `Employee Count` etc. in addition to the canonical lowercase names.
- **Messages are never regenerated** — if a lead already has messages in the DB, `generate_messages()` returns them as-is and logs "Messages already exist — skipping generation". This is intentional caching.
