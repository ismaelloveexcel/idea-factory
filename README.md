# Idea Factory v2.0 — AI-Powered Idea Validation + Monetization

Validate startup ideas in 30 seconds using AI. Get a validation score, pre-sell content, shareable reports, and grow your audience automatically.

## What's New in v2.0

### Revenue Features (Zero Manual Work)
- **Email Capture** — Collects emails on every validation, graveyard visit, and leaderboard view. Export anytime via `/api/emails`.
- **PDF Validation Reports** — Professional multi-page reports users can download and share. Each download = brand exposure.
- **Public Graveyard Wall** (`/public/graveyard`) — SEO-optimized page of killed ideas. Attracts organic search traffic for "failed startup ideas", "ideas not to build", etc.
- **Public Leaderboard** (`/public/leaderboard`) — Top-scoring ideas ranked by AI score. Drives competition and return visits.
- **Shareable Idea Pages** (`/public/idea/{token}`) — Every validation gets a unique public URL with OG meta tags for Twitter/LinkedIn/Reddit previews.
- **Twitter Thread Generator** — Auto-generates viral 5-tweet threads from any validated idea. One click to copy and post.
- **Validation-as-a-Service API** (`/api/v1/validate`) — Same analysis endpoint, ready for external integrations.
- **Market Trends API** (`/api/trends`) — Aggregated data from all validations (categories, scores, decisions).

### Viral Growth Mechanics
- Share buttons on every result (Twitter, LinkedIn, Reddit, Copy Link)
- OG meta tags on all public pages for rich social previews
- Email capture CTAs on graveyard, leaderboard, and shared idea pages
- Auto-categorization of ideas for browsable public pages

### Scoring System
Every idea gets a 0-100 validation score based on:
- Gate 1 pass (30 pts) — Can build v1 in 7 days?
- Gate 2 pass (30 pts) — Can charge $10+ on day 1?
- Gate 3 pass (20 pts) — Pain severe enough to switch now?
- Confidence bonus (up to 20 pts) — AI's confidence in gate answers

## Quick Start (Local)

```bash
# 1. Clone and setup
git clone <your-repo-url> && cd idea-factory
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 2. Install and run backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# 3. Open frontend (separate terminal)
cd frontend
python -m http.server 3000
# Visit http://localhost:3000/simple.html
```

Or use Docker:
```bash
docker-compose up
```

## Deploy to Railway (One-Click)

1. Push to GitHub
2. Go to [railway.app](https://railway.app), connect your repo
3. Add environment variable: `ANTHROPIC_API_KEY`
4. Add `BASE_URL` = your Railway URL (e.g., `https://idea-factory-production.up.railway.app`)
5. Deploy — Railway auto-detects the Dockerfile

The `railway.json` and `Procfile` are already configured.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `GET /` | Health check | Returns API status |
| `POST /api/analyze` | Analyze idea | Full AI validation with scoring |
| `POST /api/signal` | Log signal | Track pay/reply/click signals |
| `GET /api/ideas` | List ideas | All ideas (newest first) |
| `GET /api/stats` | Dashboard stats | Validated/built/killed/emails/avg score |
| `POST /api/decision/{id}` | Finalize | Set KILL/BUILD decision |
| `POST /api/email/capture` | Capture email | Store email from any source |
| `GET /api/emails` | List emails | All captured emails (admin) |
| `GET /api/idea/{id}/twitter-thread` | Twitter thread | Generate/cache viral thread |
| `GET /api/idea/{id}/pdf` | PDF report | Download validation report |
| `GET /api/trends` | Market trends | Aggregated validation data |
| `POST /api/v1/validate` | External API | Validation-as-a-service |
| `GET /public/graveyard` | Graveyard page | Public killed ideas (HTML) |
| `GET /public/leaderboard` | Leaderboard page | Public top ideas (HTML) |
| `GET /public/idea/{token}` | Shared idea | Individual idea page (HTML) |

## Revenue Model

| Channel | How It Works | Revenue Type |
|---|---|---|
| Email List | Captured on every interaction | Audience asset (newsletter, launches) |
| PDF Reports | Professional download, branded | Lead magnet, premium upgrade path |
| Graveyard SEO | Organic traffic from search | Ad revenue, email capture, affiliate |
| Leaderboard | Competition drives return visits | Engagement, email capture |
| Social Sharing | OG tags + threads = viral loops | Organic growth |
| API Access | External tools integrate | Usage-based pricing (future) |

## Tech Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite (Postgres-ready)
- **Frontend:** Vanilla HTML/CSS/JS (zero build step)
- **AI:** Claude Sonnet 4 via Anthropic API
- **PDF:** fpdf2 (lightweight, no system deps)
- **Deploy:** Railway / Docker / any PaaS

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `BASE_URL` | No | Public URL for share links (default: localhost:8000) |
| `DATABASE_URL` | No | Database connection (default: SQLite) |
| `PORT` | No | Server port (default: 8000) |

## File Structure

```
idea-factory/
├── backend/
│   ├── main.py              # FastAPI server (all endpoints)
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile           # Container config
├── frontend/
│   ├── index.html           # Original full-featured UI
│   └── simple.html          # Backend-connected UI (recommended)
├── .env.example             # Environment template
├── docker-compose.yml       # Local multi-service setup
├── railway.json             # Railway deployment config
├── Procfile                 # PaaS deployment
└── README.md                # This file
```
