# Idea Factory v5.0 — Validate Ideas → Build Apps → Sell

Personal tool. Type an idea → 4 AIs research & score it → generate everything to build & sell.

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
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ Step 4: BUILD & SELL (one-click)                    │
    │ App Scaffold · Monetization Plan · Pricing Intel    │
    │ Product Kit · Landing Page · Launch Assets          │
    └─────────────────────────────────────────────────────┘
```

## 3 Modes

| Mode | What it does |
|------|-------------|
| **Validate** | Analyzes your idea as-is |
| **Trendy** | Remixes your idea with trending markets before analysis |
| **Wild** | Generates a creative unexpected twist, then analyzes that |

## App Builder Tools (NEW in v5)

After validation, one click generates everything you need to build and sell:

| Tool | What it produces |
|------|-----------------|
| **Generate App** | Complete project scaffold — file tree, code, package.json, Dockerfile, deploy commands, revenue model |
| **Monetization Plan** | Pricing tiers, paywall strategy, upsell flows, revenue projections, quick wins to first $ |
| **Pricing Intel** | Competitor pricing research, optimal price, price sensitivity analysis, revenue at different price points |
| **Product Kit** | ALL launch assets in one shot — branding, launch tweets, PH copy, Reddit post, sales page outline, checklist |
| **Landing Page** | Full production-quality landing page with waitlist form, pricing, testimonials, FAQ |

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
| `ANTHROPIC_API_KEY` | Claude (analysis + scoring + app builder) | **Yes** | https://console.anthropic.com/ |
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
| `/api/idea/{id}/landing-page` | GET | Generated landing page HTML (with waitlist) |
| `/api/idea/{id}/twitter-thread` | GET | Generated viral tweet thread |
| `/api/idea/{id}/generate-app` | GET | **App scaffold** — file tree, code, configs, deploy commands |
| `/api/idea/{id}/monetization-plan` | GET | **Monetization strategy** — pricing tiers, paywall, revenue projections |
| `/api/idea/{id}/pricing-intel` | GET | **Pricing intelligence** — competitor prices, optimal pricing |
| `/api/idea/{id}/product-kit` | GET | **Full product launch kit** — branding, copy, checklist, everything |
| `/api/idea/{id}/pivot-suggestions` | GET | Pivot/expansion ideas |
| `/api/idea/{id}/interview-script` | GET | Customer discovery interview questions |
| `/api/idea/{id}/gtm-playbook` | GET | Go-to-market launch playbook |
| `/api/idea/{id}/swot` | GET | SWOT analysis |
| `/api/idea/{id}/unit-economics` | GET | Unit economics breakdown |
| `/api/compare` | POST | Compare 2-5 ideas side by side |
| `/api/batch-validate` | POST | Quick-score multiple ideas |
| `/api/brainstorm` | GET | Generate ideas from a seed topic |
| `/api/email/capture` | POST | Capture email address |
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
│   ├── main.py              # FastAPI server (validation + app builder)
│   ├── requirements.txt     # Python dependencies
│   ├── .env.template        # API key template
│   ├── e2e_test.py          # 111-test E2E suite
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
