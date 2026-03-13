# Lead Agent

AI-powered lead generation platform. Import leads, score them, send personalized emails, detect replies, and book meetings automatically.

## Quick Start

```bash
# 1. Clone and setup
bash setup.sh

# 2. Fill in your credentials
nano .env

# 3. Run migrations
cd backend
alembic upgrade head

# 4. Start backend
uvicorn main:app --reload --port 8000

# 5. Start frontend (separate terminal)
cd frontend
npm run dev
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 15 (create a `leadgen` database)

## Environment Variables

Copy `.env.example` to `.env` and fill in:

- `DATABASE_URL` — PostgreSQL connection string
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `OPENAI_API_KEY` — from platform.openai.com
- `SENDGRID_API_KEY` — from app.sendgrid.com
- `SENDGRID_FROM_EMAIL` — your verified sender email

## API

Once running, visit `http://localhost:8000/docs` for interactive API docs.

## Deployment

- Database: [Supabase](https://supabase.com) (free tier)
- Backend: [Render](https://render.com) (free tier, root dir: `backend`)
- Frontend: [Vercel](https://vercel.com) (free tier, root dir: `frontend`)
