# Testing Guide — Idea Factory

## 🧪 Quick Test Flow

### 1. Backend Health Check

```bash
curl http://localhost:8000/
```

**Expected:**
```json
{"status":"Idea Factory API running","version":"1.0.0"}
```

---

### 2. Test Idea Analysis

**Request:**
```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "raw_idea": "A Chrome extension that blocks LinkedIn cold outreach DMs",
    "pain": {
      "pain_who": "Startup founders and VCs",
      "pain_quotes": "I get 50+ spam DMs per day\nLinkedIn is unusable because of cold outreach\nI spend 20min daily deleting spam messages",
      "pain_freq": "Every single day, multiple times",
      "pain_buyers": "@paulg, @naval, @dhh"
    }
  }'
```

**Expected Response Structure:**
```json
{
  "id": "a4f3e1b2",
  "concept": "LinkedIn spam blocker Chrome extension",
  "target_user": "Startup founders drowning in cold DMs",
  "core_pain": "50+ spam DMs daily waste 20min",
  "value_promise": "Clean LinkedIn inbox in one click",
  "g1": "Can you build v1 in <7 days?",
  "g1r": "YES — Chrome extension API = 2 days",
  "g2": "Can you charge >$10 on day 1?",
  "g2r": "YES — Founders pay $29/mo for productivity tools",
  "g3": "Is pain severe enough they'll switch NOW?",
  "g3r": "YES — 20min daily = 121hr/year wasted",
  "final_decision": "BUILD"
}
```

---

### 3. Test Signal Logging

```bash
curl -X POST http://localhost:8000/api/signal \
  -H "Content-Type: application/json" \
  -d '{
    "idea_id": "a4f3e1b2",
    "signal_type": "pay"
  }'
```

**Expected:**
```json
{
  "status": "success",
  "pay": 1,
  "rep": 0,
  "clk": 0
}
```

---

### 4. Get All Ideas

```bash
curl http://localhost:8000/api/ideas
```

**Expected:** Array of all validated ideas

---

### 5. Get Stats

```bash
curl http://localhost:8000/api/stats
```

**Expected:**
```json
{
  "validated": 5,
  "built": 2,
  "killed": 3,
  "week": 5
}
```

---

## 🎯 Test Scenarios

### Scenario A: Strong Idea (Should PASS all gates)

**Input:**
- **Pain Who:** Solo developers launching SaaS
- **Pain Quotes:** 
  - "Spent 3 months building, got 0 customers"
  - "How do I validate before coding?"
  - "Lost $5k on unwanted features"
- **Pain Freq:** Every solo founder experiences this
- **Pain Buyers:** @levelsio, @dannypostmaa, @marc_louvion
- **Idea:** Tool that validates SaaS ideas in 48h using AI + pre-sell posts

**Expected Decision:** `BUILD`

---

### Scenario B: Weak Idea (Should FAIL gates)

**Input:**
- **Pain Who:** People who like cats
- **Pain Quotes:**
  - "Cats are cute"
  - "I wish I had more cat pictures"
- **Pain Freq:** Sometimes
- **Pain Buyers:** My friends
- **Idea:** Social network for cat lovers

**Expected Decision:** `KILL`

**Reasons:**
- Gate 1: FAIL — "My friends" is not specific enough
- Gate 2: FAIL — No monetization urgency
- Gate 3: FAIL — Not a severe pain

---

### Scenario C: Test-First Idea (Mixed gates)

**Input:**
- **Pain Who:** Freelance designers
- **Pain Quotes:**
  - "Invoice clients manually takes 2 hours/week"
  - "Hate chasing late payments"
- **Pain Freq:** Weekly
- **Pain Buyers:** @femkesvs, @shl, @traf
- **Idea:** Invoice automation tool for designers

**Expected Decision:** `TEST FIRST`

**Reasons:**
- Gate 1: PASS — Real named buyers
- Gate 2: MAYBE — Revenue possible but competitive space
- Gate 3: PASS — Weekly pain is actionable

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
