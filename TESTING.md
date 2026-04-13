# Testing Guide — Idea Factory v4.0

## Quick Checks

### 1. Health Check

```bash
curl http://localhost:8000/api/health
```

**Expected:**
```json
{"status": "ok", "version": "4.0.0", "engines": {"claude": true, "perplexity": false, "gpt4o": true, "grok": true}}
```

---

### 2. Analyze an Idea (SSE Stream)

```bash
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"idea": "An app that helps freelancers track unpaid invoices", "mode": "validate"}'
```

**Expected:** Server-Sent Events stream with:
- `step` events (ai: perplexity/grok/claude/gpt, status: start/done/skipped)
- `result` event with score, verdict, concept, gates, etc.

---

### 3. Test Modes

**Validate** (default — analyzes as-is):
```bash
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"idea": "A tool for tracking gym progress", "mode": "validate"}'
```

**Trendy** (remixes with trending markets first):
```bash
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"idea": "A tool for tracking gym progress", "mode": "trendy"}'
```

**Wild** (generates creative twist first):
```bash
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"idea": "A tool for tracking gym progress", "mode": "wild"}'
```

For trendy/wild modes, expect an extra `step` event with `"ai": "mode"` showing the remixed idea.

---

### 4. Stats

```bash
curl http://localhost:8000/api/stats
```

---

### 5. PDF Report

```bash
# Use an idea ID from a previous analysis
curl http://localhost:8000/api/idea/{id}/pdf -o report.pdf
```

---

## Automated E2E Suite

Run all 178 tests:

```bash
cd backend
pip install requests
python e2e_test_v4.py
```

Covers: health, frontend, stats, SSE streaming, result structure (42+ fields), DB persistence, signals, decisions, PDF, premium report, landing page, twitter thread, public pages, email capture, admin, cron, trends.

---

## Scoring Reference

| Score | Verdict |
|-------|---------|
| 70-100 | **GO** — Strong idea, build it |
| 40-69 | **MAYBE** — Needs work, test first |
| 0-39 | **SKIP** — Weak, move on |

---

## 🐛 Error Cases to Test

### 1. Missing API Key

**Test:**
```bash
# Remove .env file or set invalid key
ANTHROPIC_API_KEY=invalid uvicorn main:app
```

**Expected:** 
- `/api/analyze` returns HTTP 500
- Error message: "ANTHROPIC_API_KEY not configured"

---

### 2. Incomplete Input

**Request:**
```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "raw_idea": "Some idea",
    "pain": {
      "pain_who": "People"
    }
  }'
```

**Expected:** HTTP 422 Validation Error

---

### 3. Invalid Signal Type

**Request:**
```bash
curl -X POST http://localhost:8000/api/signal \
  -H "Content-Type: application/json" \
  -d '{
    "idea_id": "test123",
    "signal_type": "invalid"
  }'
```

**Expected:** Signal ignored (backend doesn't increment anything)

---

### 4. Non-Existent Idea

**Request:**
```bash
curl -X POST http://localhost:8000/api/signal \
  -H "Content-Type: application/json" \
  -d '{
    "idea_id": "nonexistent",
    "signal_type": "pay"
  }'
```

**Expected:** HTTP 404 "Idea not found"

---

## 📊 Frontend Testing

### Open Simple UI

```bash
cd frontend
python -m http.server 3000
```

Visit: http://localhost:3000/simple.html

### Test Cases:

**1. Backend Connection Check**
- Status badge should show "✓ Backend Connected" (green)
- If backend offline: Shows "✗ Backend Offline" (red)

**2. Form Validation**
- Submit empty form → Toast: "⚠️ Fill all fields"
- Submit with <80 chars in pain quotes → Toast: "⚠️ Add more detailed pain quotes"

**3. Full Flow**
- Fill all fields with valid data
- Click "Analyze Idea"
- Button text changes to "Analyzing..."
- Results appear with:
  - Concept, target user, core pain, value promise
  - 3 gate cards (green=pass, red=fail)
  - Decision box (green=BUILD, red=KILL, yellow=TEST)
  - Pre-sell content (Reddit + X posts)

---

## 🔍 Database Inspection

```bash
# Install sqlite3 if needed
sudo apt install sqlite3

# Open database
sqlite3 backend/idea_factory.db

# View all ideas
SELECT id, concept, final_decision FROM ideas;

# View stats
SELECT * FROM stats;

# Exit
.exit
```

---

## 🧹 Reset Test Data

```bash
rm backend/idea_factory.db
# Restart backend to recreate empty database
```

---

## ✅ Checklist Before Production

- [ ] API key stored in `.env` (not hardcoded)
- [ ] `.env` file in `.gitignore`
- [ ] Database file in `.gitignore`
- [ ] CORS configured for production domain (not `allow_origins=["*"]`)
- [ ] Frontend points to production API URL (not localhost)
- [ ] Rate limiting added to `/api/analyze` endpoint
- [ ] Error logging configured
- [ ] Backup strategy for SQLite database

---

## 🚨 Known Limitations

1. **SQLite = Single User** — Multiple users will cause write conflicts
2. **No Authentication** — Anyone with API URL can use it
3. **No Rate Limiting** — Could rack up Claude API costs
4. **CORS = Allow All** — Insecure for production

**For Production:** Consider PostgreSQL + JWT auth + rate limiting
