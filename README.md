# Idea Factory v4.0 — Multi-AI Idea Validator

Type one sentence. Four AIs research, analyze, and score your idea in real time.

## How It Works

```
You type: "An app that matches dog owners with local dog walkers"
                              ↓
    ┌─────────────────────────┼─────────────────────────┐
    │ Step 1 (parallel)       │                         │
    │ Perplexity: web search  │  Grok: X/Twitter scan   │
    │ competitors & market    │  sentiment & buzz       │
    └─────────┬───────────────┴────────────┬────────────┘
              ↓                            ↓
    ┌─────────────────────────┼─────────────────────────┐
    │ Step 2 (parallel)       │                         │
    │ Claude: deep analysis   │  GPT-4o: business model │
    │ gates, risks, strategy  │  revenue & projections  │
    └─────────┬───────────────┴────────────┬────────────┘
              ↓                            ↓
         Step 3: Score (0-100) → Save → Stream results
```

## 3 Modes

| Mode | What it does |
|------|-------------|
| **Validate** | Analyzes your idea as-is |
| **Trendy** | Remixes your idea with trending markets before analysis |
| **Wild** | Generates a creative unexpected twist, then analyzes that |

## Quick Start

### Windows
```
git clone https://github.com/ismaelloveexcel/idea-factory.git
cd idea-factory
# Copy backend\.env.template → backend\.env and add your API keys
start.bat
```

### Mac / Linux
```bash
git clone https://github.com/ismaelloveexcel/idea-factory.git
cd idea-factory
cp backend/.env.template backend/.env
# Edit backend/.env and add your API keys
./start.sh
```

Opens at **http://localhost:8000**

### Docker
```bash
docker-compose up
```

## API Keys

| Key | Engine | Required | Get it at |
|-----|--------|----------|-----------|
| `ANTHROPIC_API_KEY` | Claude (analysis + scoring) | **Yes** | https://console.anthropic.com/ |
| `OPENAI_API_KEY` | GPT-4o (business model) | Recommended | https://platform.openai.com/api-keys |
| `GROK_API_KEY` | Grok (X sentiment) | Recommended | https://console.x.ai/ |
| `PERPLEXITY_API_KEY` | Perplexity (web research) | Optional | https://www.perplexity.ai/settings/api |

The app works with just Claude. Each additional key activates another engine.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Server status + engine availability |
| `/api/analyze` | POST | Analyze idea (SSE stream). Body: `{"idea": "...", "mode": "validate"}` |
| `/api/ideas` | GET | List all validated ideas |
| `/api/stats` | GET | Dashboard stats |
| `/api/signal` | POST | Log pay/reply/click signals |
| `/api/decision/{id}` | POST | Set KILL/BUILD decision |
| `/api/idea/{id}/pdf` | GET | Download PDF report |
| `/api/idea/{id}/premium-report` | GET | Premium deep-dive report |
| `/api/idea/{id}/landing-page` | GET | Generated landing page HTML |
| `/api/idea/{id}/twitter-thread` | GET | Generated viral tweet thread |
| `/api/email/capture` | POST | Capture email address |
| `/api/emails` | GET | List captured emails (admin) |
| `/api/trends` | GET | Market trends from all validations |
| `/public/graveyard` | GET | Public killed ideas page |
| `/public/leaderboard` | GET | Public top ideas page |
| `/public/idea/{token}` | GET | Shareable idea page |

## Scoring

Every idea gets a 0-100 score based on:
- Gate 1 (30 pts) — Can you build v1 in 7 days?
- Gate 2 (30 pts) — Can you charge $10+ on day 1?
- Gate 3 (20 pts) — Pain severe enough to switch now?
- Confidence bonus (up to 20 pts)

**Verdict:** GO (70+) · MAYBE (40-69) · SKIP (<40)

## Tech Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** Vanilla HTML/CSS/JS (single file, no build step)
- **AI:** Anthropic Claude + OpenAI GPT-4o + xAI Grok + Perplexity
- **Streaming:** Server-Sent Events (SSE)
- **PDF:** fpdf2

## File Structure

```
idea-factory/
├── backend/
│   ├── main.py              # FastAPI server (~1200 lines)
│   ├── requirements.txt     # Python dependencies
│   ├── .env.template        # API key template
│   ├── e2e_test_v4.py       # 178-test E2E suite
│   └── Dockerfile
├── frontend/
│   ├── index.html           # Main app UI (dark theme)
│   └── simple.html          # Minimal test UI
├── start.bat                # Windows launcher
├── start.sh                 # Mac/Linux launcher
├── docker-compose.yml
├── railway.json
├── Procfile
└── README.md
```
