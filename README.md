# Idea Factory — Kill or Build

**AI-powered idea validation system for solo entrepreneurs.**

Stop building products nobody wants. Validate demand BEFORE writing code.

---

## 🎯 What This Does

1. **Pain-First Validation** — Forces you to prove people have the pain BEFORE you build
2. **3-Gate Scoring** — AI evaluates: Can people pay NOW? Can you build fast? Is pain severe?
3. **Pre-Sell Testing** — Generates Reddit/X posts to test demand in 48 hours
4. **Signal Tracking** — Counts payments, replies, clicks to decide: KILL or BUILD
5. **Auto GitHub Repos** — Creates repo automatically when idea passes validation

---

## 🏗️ Architecture

```
idea-factory/
├── backend/              # FastAPI + SQLite
│   ├── main.py          # API server
│   └── requirements.txt
├── frontend/            # HTML + vanilla JS
│   └── index.html       # Your original UI
├── .env.example         # API key template
└── README.md           # This file
```

**Tech Stack:**
- **Backend:** FastAPI + SQLAlchemy + SQLite
- **AI:** Claude Sonnet 4 (via Anthropic API)
- **Frontend:** Pure HTML/CSS/JS (no framework)
- **Database:** SQLite (local file, zero setup)

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Claude API key (get from: https://console.anthropic.com/)

### Step 1: Clone & Setup

```bash
git clone https://github.com/ismaelsudally/idea-factory.git
cd idea-factory
```

### Step 2: Configure API Key

```bash
cp .env.example .env
```

Edit `.env` and add your Claude API key:
```
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

### Step 3: Install Dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 4: Start Backend

```bash
uvicorn main:app --reload
```

Backend running at: http://localhost:8000

### Step 5: Open Frontend

```bash
# In a new terminal, from project root:
cd frontend
python -m http.server 3000
```

Frontend running at: http://localhost:3000

---

## 📡 API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `GET /` | - | Health check |
| `POST /api/analyze` | JSON | Validate idea, returns scores |
| `POST /api/signal` | JSON | Log demand signal (pay/reply/click) |
| `GET /api/ideas` | - | List all ideas |
| `GET /api/stats` | - | Get validation stats |
| `POST /api/decision/{idea_id}` | - | Finalize KILL/BUILD decision |

### Example: Analyze Idea

**Request:**
```json
POST /api/analyze
{
  "raw_idea": "A tool that scrapes pain from Reddit and scores startup ideas",
  "pain": {
    "pain_who": "Solo founders validating SaaS",
    "pain_quotes": "I built for 6 months, nobody paid...\nHow do I know if my idea is worth building?",
    "pain_freq": "Every solo founder asks this weekly",
    "pain_buyers": "@startupfounder, @indiemaker, @saasbuilder"
  }
}
```

**Response:**
```json
{
  "id": "a4f3e1b2",
  "concept": "Reddit pain scraper → idea scorer",
  "target_user": "Solo founders validating SaaS ideas",
  "core_pain": "Building for months without validating demand first",
  "value_promise": "Know if people will pay BEFORE writing code",
  "g1": "Can you build v1 in <7 days?",
  "g1r": "YES — Scraping API + scoring logic = 3 days max",
  "g2": "Can you charge >$10 on day 1?",
  "g2r": "YES — Solo founders pay $29/mo for validation tools",
  "g3": "Is pain severe enough they'll switch NOW?",
  "g3r": "YES — Founders lose months building unwanted products",
  "reddit": "Anyone else build for 6 months then get zero sales?...",
  "x_post": "Built a SaaS, 0 customers. Realized I never validated demand...",
  "offer": "Validate your idea in 48h before writing code",
  "price": "$29",
  "cta": "DM me 'interested'",
  "final_decision": "BUILD"
}
```

---

## 🔄 Workflow

```
1. YOU DESCRIBE PAIN
   ↓ "Solo founders waste months building unwanted products"
   
2. AI SCORES IDEA
   ↓ Runs 3 gates: Build speed? Revenue speed? Pain severity?
   
3. AI GENERATES PRE-SELL
   ↓ Creates Reddit post + X post to test demand
   
4. YOU POST & TRACK SIGNALS
   ↓ 48 hours: Count payments, replies, clicks
   
5. DECISION ENGINE
   ↓ 1 payment? → BUILD NOW
   ↓ 5+ replies? → REFINE & REPOST
   ↓ 10+ clicks, 0 intent? → KILL
```

---

## 🗄️ Database Schema

**ideas table:**
```sql
CREATE TABLE ideas (
  id TEXT PRIMARY KEY,
  date DATETIME,
  pain_who TEXT,
  pain_quotes TEXT,
  pain_freq TEXT,
  pain_buyers TEXT,
  raw_idea TEXT,
  concept TEXT,
  target_user TEXT,
  core_pain TEXT,
  value_promise TEXT,
  g1 TEXT, g1r TEXT,  -- Gate 1 question + result
  g2 TEXT, g2r TEXT,  -- Gate 2 question + result
  g3 TEXT, g3r TEXT,  -- Gate 3 question + result
  reddit TEXT,
  x_post TEXT,
  offer TEXT,
  price TEXT,
  cta TEXT,
  pay INTEGER DEFAULT 0,
  rep INTEGER DEFAULT 0,
  clk INTEGER DEFAULT 0,
  countdown_start DATETIME,
  final_decision TEXT,  -- KILL | TEST FIRST | BUILD
  repo_url TEXT,
  ai_response JSON
);
```

**stats table:**
```sql
CREATE TABLE stats (
  id INTEGER PRIMARY KEY,
  validated INTEGER DEFAULT 0,
  built INTEGER DEFAULT 0,
  killed INTEGER DEFAULT 0,
  week INTEGER DEFAULT 0,
  week_start DATETIME
);
```

---

## 🛠️ Development

### Run Tests (Coming Soon)
```bash
pytest backend/tests/
```

### Check API Docs
```
http://localhost:8000/docs  # Swagger UI
http://localhost:8000/redoc # ReDoc
```

### Reset Database
```bash
rm backend/idea_factory.db
# Restart server to recreate tables
```

---

## 🚢 Deployment (Future)

**Option A: Docker**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY backend/ .
RUN pip install -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Option B: Railway.app**
1. Push to GitHub
2. Connect Railway to repo
3. Add `ANTHROPIC_API_KEY` env var
4. Deploy

**Option C: Fly.io**
```bash
fly launch
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly deploy
```

---

## 📊 Roadmap

### ✅ Phase 1: Validation Engine (COMPLETE)
- [x] Pain-first input flow
- [x] Claude API integration
- [x] 3-gate scoring system
- [x] Pre-sell content generation
- [x] SQLite persistence

### 🚧 Phase 2: App Generator (IN PROGRESS)
- [ ] Template system (React, Next.js, FastAPI)
- [ ] Code generation via Claude
- [ ] Auto GitHub repo creation
- [ ] Vercel/Railway deployment automation

### 📋 Phase 3: Marketing Automation (PLANNED)
- [ ] Auto-post to Reddit/X/HN
- [ ] Email waitlist builder
- [ ] Landing page generator
- [ ] Analytics dashboard

### 🌍 Phase 4: Multi-Region (PLANNED)
- [ ] Regional market insights (UAE vs US vs EU)
- [ ] Platform preferences by region (Instagram vs TikTok)
- [ ] Localized pricing recommendations

---

## 🤝 Contributing

This is a solo project by [@ismaelsudally](https://github.com/ismaelsudally).

If you find bugs or have feature requests:
1. Open an issue
2. Or fork + PR

---

## 📄 License

MIT License - Build whatever you want with this.

---

## 🙏 Credits

- **Original Concept:** Ismael Sudally
- **AI Partner:** Claude (Anthropic)
- **Inspired by:** ludo.ai, ProductHunt Ship, Indie Hackers

---

## ⚠️ Important Notes

**API Key Security:**
- NEVER commit `.env` to git
- NEVER expose API keys in frontend code
- Backend handles all Claude API calls

**Cost Estimation:**
- Each idea analysis: ~3,000 tokens (~$0.01)
- 100 ideas/month: ~$1.00
- Claude Sonnet 4 pricing: https://www.anthropic.com/pricing

**Limitations:**
- SQLite = single user (for now)
- No authentication (local use only)
- GitHub integration requires manual PAT setup

---

## 💬 Questions?

Open an issue or DM [@ismaelsudally](https://github.com/ismaelsudally)

**Built with Claude. Validated with pain. Shipped with speed.**
