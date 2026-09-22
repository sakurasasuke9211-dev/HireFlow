# HireFlow

HireFlow is an AI-powered recruiting platform that moves hiring from keyword screening to **evidence-based candidate validation**.

For each candidate, HireFlow answers:

> What evidence do we have that this person meets the important requirements of the role, and what still needs to be validated?

Recruiters upload a job description and resumes, review match-and-gap analysis, generate interview questions, upload interview transcripts, and produce a final evidence report with a human hiring decision.

## Features

- **JD and resume parsing** — structured requirements and profile claims
- **Match and gap analysis** — per-requirement status with quotes and rationale
- **Interview kit** — candidate-specific questions for unproven requirements
- **Transcript analysis** — coverage probing against the JD
- **Final assessment** — combined resume + interview evidence report
- **File assistant** — find, read, summarize, and download org files in natural language

## Tech stack

| Layer | Technology |
| --- | --- |
| Web UI | Next.js 16 (App Router), React, Tailwind CSS |
| API | Python FastAPI |
| Database | Supabase (PostgreSQL) |
| File storage | Supabase Storage |
| LLM | Groq (OpenAI-compatible API) |

## Repository layout

```text
apps/
  web/          Next.js recruiter UI
  api/          FastAPI backend + job orchestration
packages/
  domain/       Shared types and enums
  agents/       LLM agents (matcher, prober, report, etc.)
  extract/      PDF/DOCX/VTT text extraction
infra/
  sql/          Supabase migrations
```

See [architecture.md](./architecture.md) for system design, agent graphs, and API reference.

## Local development

### Prerequisites

- Python 3.11+
- Node.js 20+
- A Supabase project
- A Groq API key

### 1. Environment

Copy the example env files and fill in your keys:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

Root `.env` (API):

```env
SECRET_KEY=your-dev-secret
CORS_ORIGINS=http://localhost:3000,http://localhost:3001
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
GROQ_API_KEY=your-groq-key
```

Web `apps/web/.env.local`:

```env
HIREFLOW_API_URL=http://127.0.0.1:8000
```

### 2. Database

Run the SQL migrations in `infra/sql/` in order (`001` through `009`) against your Supabase project. Create a private Storage bucket named `hireflow`.

### 3. Install dependencies

```bash
# API
pip install -r requirements-railway.txt

# Web
cd apps/web && npm install
```

### 4. Run

```bash
# Terminal 1 — API
cd apps/api
python -m uvicorn hireflow_api.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — Web
cd apps/web
npm run dev -- -p 3001
```

Open [http://localhost:3001](http://localhost:3001), register an account, and create a job.

## Production deployment

Production uses **Vercel** (frontend), **Railway** (API), and **Supabase** (database + storage).

| Host | Root / config | Required env |
| --- | --- | --- |
| **Vercel** | `apps/web` | `HIREFLOW_API_URL` |
| **Railway** | repo root | `SECRET_KEY`, `CORS_ORIGINS`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY` |
| **Supabase** | — | Run `infra/sql/` migrations; bucket `hireflow` |

Detailed steps are in [architecture.md §8.5](./architecture.md#85-hosting-vercel--railway).

## Tests

```bash
cd packages/agents
python -m pytest tests/ -q
```

## License

Private — all rights reserved unless otherwise specified.
