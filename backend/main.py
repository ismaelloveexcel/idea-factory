"""
Idea Factory v4.0 — Multi-AI Idea Validator
Personal tool. Type an idea → 4 AIs research & score it.

Pipeline:
  Step 1 (parallel): Perplexity (web search) + Grok (X sentiment)
  Step 2 (parallel): Claude (deep analysis) + GPT-4o (business model)
  Step 3: Combine → Score → Save

STACK: FastAPI + SQLite + Anthropic + OpenAI + Perplexity + Grok + Stripe
"""

import os
import json
import uuid
import secrets
import io
import re
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Optional, List

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Query, Request, Header, Response, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Boolean, Text, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()


# ─── CONFIG ───────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./idea_factory.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-me-in-production")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# AI API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")

# Stripe / Monetization
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_PRO_MONTHLY = os.getenv("STRIPE_PRICE_PRO_MONTHLY", "")
STRIPE_PRICE_API_MONTHLY = os.getenv("STRIPE_PRICE_API_MONTHLY", "")
FREE_TIER_LIMIT = int(os.getenv("FREE_TIER_LIMIT", "3"))

# Stripe client (optional)
try:
    import stripe as _stripe_module
    _stripe_key = STRIPE_SECRET_KEY
    if _stripe_key and not _stripe_key.startswith("sk_test_placeholder") and len(_stripe_key) > 20:
        _stripe_module.api_key = _stripe_key
        STRIPE_ENABLED = True
    else:
        STRIPE_ENABLED = False
except ImportError:
    _stripe_module = None
    STRIPE_ENABLED = False

# API access keys registry (populated via admin)
_API_KEYS: dict = {}  # key → {"user": str, "is_pro": bool}

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── DATABASE MODELS ──────────────────────────────────
class IdeaDB(Base):
    __tablename__ = "ideas"
    id = Column(String, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    raw_idea = Column(Text)
    concept = Column(String)
    target_user = Column(String)
    core_pain = Column(String)
    value_promise = Column(String)
    g1 = Column(String)
    g1r = Column(String)
    g2 = Column(String)
    g2r = Column(String)
    g3 = Column(String)
    g3r = Column(String)
    reddit = Column(Text)
    x_post = Column(Text)
    offer = Column(String)
    price = Column(String)
    cta = Column(String)
    pay = Column(Integer, default=0)
    rep = Column(Integer, default=0)
    clk = Column(Integer, default=0)
    final_decision = Column(String, nullable=True)
    score = Column(Integer, default=0)
    ai_response = Column(JSON, nullable=True)
    is_public = Column(Boolean, default=True)
    share_token = Column(String, unique=True, index=True, nullable=True)
    view_count = Column(Integer, default=0)
    category = Column(String, nullable=True)
    regional_scores = Column(JSON, nullable=True)
    timing_analysis = Column(JSON, nullable=True)
    moat_analysis = Column(JSON, nullable=True)
    perplexity_research = Column(JSON, nullable=True)
    grok_sentiment = Column(JSON, nullable=True)
    gpt_business = Column(JSON, nullable=True)
    # Legacy columns (kept for old data compatibility)
    pain_who = Column(String, nullable=True)
    pain_quotes = Column(Text, nullable=True)
    pain_freq = Column(String, nullable=True)
    pain_buyers = Column(String, nullable=True)
    email = Column(String, nullable=True)
    user_id = Column(String, nullable=True, index=True)
    twitter_thread = Column(Text, nullable=True)
    countdown_start = Column(DateTime, nullable=True)
    repo_url = Column(String, nullable=True)
    is_premium_report = Column(Boolean, default=False)
    blueprint = Column(JSON, nullable=True)
    landing_page_html = Column(Text, nullable=True)
    revenue_sim = Column(JSON, nullable=True)
    mvp_plan = Column(JSON, nullable=True)
    distribution_plan = Column(JSON, nullable=True)


class StatsDB(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True, index=True)
    validated = Column(Integer, default=0)
    built = Column(Integer, default=0)
    killed = Column(Integer, default=0)
    week = Column(Integer, default=0)
    week_start = Column(DateTime, default=datetime.utcnow)


class EmailCaptureDB(Base):
    __tablename__ = "email_captures"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, index=True)
    idea_id = Column(String, nullable=True)
    source = Column(String, default="validation")
    captured_at = Column(DateTime, default=datetime.utcnow)
    tags = Column(String, nullable=True)


class UserSessionDB(Base):
    __tablename__ = "user_sessions"
    session_id = Column(String, primary_key=True, index=True)
    ip = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    validations_count = Column(Integer, default=0)
    is_pro = Column(Boolean, default=False)
    stripe_customer_id = Column(String, nullable=True)
    referral_code = Column(String, unique=True, nullable=True, index=True)
    referred_by = Column(String, nullable=True)
    referral_credits = Column(Integer, default=0)


Base.metadata.create_all(bind=engine)

# Safe migration: add new columns to existing DBs
_MIGRATE = [
    ("perplexity_research", "TEXT"), ("grok_sentiment", "TEXT"), ("gpt_business", "TEXT"),
    ("user_id", "TEXT"), ("email", "TEXT"), ("twitter_thread", "TEXT"),
    ("countdown_start", "TIMESTAMP"), ("repo_url", "TEXT"),
    ("is_premium_report", "INTEGER DEFAULT 0"),
    ("blueprint", "TEXT"), ("landing_page_html", "TEXT"),
    ("revenue_sim", "TEXT"), ("mvp_plan", "TEXT"), ("distribution_plan", "TEXT"),
]
with engine.connect() as _conn:
    for _col, _type in _MIGRATE:
        try:
            _conn.execute(text(f"ALTER TABLE ideas ADD COLUMN {_col} {_type}"))
            _conn.commit()
        except Exception:
            pass


# ─── PYDANTIC MODELS ─────────────────────────────────
class IdeaInput(BaseModel):
    idea: str
    mode: str = "validate"  # validate, trendy, wild

class AnalyzeRequest(BaseModel):
    idea: str  # Required (use raw_idea as alias handled below)
    mode: str = "validate"
    email: Optional[str] = None
    pain: Optional[dict] = None

class ReferralInput(BaseModel):
    code: str

class CheckoutInput(BaseModel):
    product_type: str  # pro_monthly, single_report, api_monthly
    idea_id: Optional[str] = None

class SignalUpdate(BaseModel):
    idea_id: str
    signal_type: str

class EmailCaptureInput(BaseModel):
    email: str
    source: str = "validation"
    idea_id: Optional[str] = None
    tags: Optional[str] = None


# ─── DEPENDENCIES ─────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def check_admin(x_admin_secret: str = Header(None)):
    if not x_admin_secret or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    return True


# ─── SESSION HELPERS ──────────────────────────────────
def _get_or_create_session(request: Request, db: Session) -> UserSessionDB:
    """Get or create a user session from cookie. Returns (session, is_new)."""
    sid = request.cookies.get("session_id")
    if sid:
        sess = db.query(UserSessionDB).filter(UserSessionDB.session_id == sid).first()
        if sess:
            sess.last_seen = datetime.utcnow()
            db.commit()
            return sess
    # Create new session
    new_sid = secrets.token_urlsafe(24)
    ip = (request.client.host if request.client else "unknown")
    ref_code = secrets.token_urlsafe(6).upper()
    sess = UserSessionDB(session_id=new_sid, ip=ip, referral_code=ref_code)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess

def _check_api_key(x_api_key: str = Header(None)):
    """Validate API key for programmatic access."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    if x_api_key not in _API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return _API_KEYS[x_api_key]


# ─── SSE HELPER ───────────────────────────────────────
def sse(event_type: str, data: dict) -> str:
    data["type"] = event_type
    return f"data: {json.dumps(data)}\n\n"


# ─── JSON PARSER ─────────────────────────────────────
def parse_json_response(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1])
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', clean)
        if match:
            return json.loads(match.group())
        raise HTTPException(500, "Failed to parse AI response")


# ═════════════════════════════════════════════════════
#  AI CLIENTS
# ═════════════════════════════════════════════════════

async def _call_openai_api(base_url: str, api_key: str, model: str,
                            prompt: str, max_tokens: int = 2000) -> str:
    """Generic OpenAI-compatible API caller (Perplexity, GPT, Grok)."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def _call_claude(prompt: str, max_tokens: int = 3000) -> str:
    """Call Claude via Anthropic SDK (async)."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    msg = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ── Perplexity: live web research ─────────────────────
async def research_with_perplexity(idea: str) -> Optional[dict]:
    if not PERPLEXITY_API_KEY:
        return None
    try:
        prompt = f"""I'm evaluating this startup idea. Search the web and give me real data.

IDEA: {idea}

Find and return this JSON (no markdown, no backticks):
{{
  "competitors": [
    {{"name": "Company name", "url": "website", "price": "pricing", "weakness": "their main weakness"}}
  ],
  "market_size": "estimated market size with source",
  "growth_rate": "market growth rate if available",
  "reddit_discussions": [
    {{"subreddit": "r/name", "title": "post title", "sentiment": "positive/negative/mixed", "key_quote": "relevant quote"}}
  ],
  "pricing_benchmarks": [
    {{"product": "name", "price": "$X/mo", "model": "subscription/one-time/freemium"}}
  ],
  "key_trends": ["trend 1", "trend 2"],
  "potential_customers": "who is actively looking for this",
  "sources": ["url1", "url2"]
}}

Return ONLY valid JSON. Use real companies and real data."""
        raw = await _call_openai_api(
            "https://api.perplexity.ai", PERPLEXITY_API_KEY, "sonar", prompt, 2000
        )
        return parse_json_response(raw)
    except Exception as e:
        print(f"[Perplexity] {e}")
        return None


# ── Grok: X / social sentiment ────────────────────────
async def scan_with_grok(idea: str) -> Optional[dict]:
    if not GROK_API_KEY:
        return None
    try:
        prompt = f"""Analyze what people are saying on X (Twitter) and social media about this problem.

IDEA: {idea}

Return this JSON (no markdown, no backticks):
{{
  "buzz_level": "HIGH or MEDIUM or LOW",
  "trend_direction": "RISING or STABLE or DECLINING",
  "sentiment": "mostly positive, mostly negative, or mixed",
  "sample_posts": [
    {{"text": "example post or complaint", "engagement": "high/medium/low"}},
    {{"text": "another relevant post", "engagement": "high/medium/low"}}
  ],
  "hashtags": ["relevant", "hashtags"],
  "pain_signals": ["specific complaints people have"],
  "summary": "2-sentence summary of the social conversation"
}}

Return ONLY valid JSON."""
        raw = await _call_openai_api(
            "https://api.x.ai/v1", GROK_API_KEY, "grok-3-mini", prompt, 1500
        )
        return parse_json_response(raw)
    except Exception as e:
        print(f"[Grok] {e}")
        return None


# ── Claude: deep strategic analysis ───────────────────
async def analyze_with_claude(idea: str, research: Optional[dict],
                               sentiment: Optional[dict]) -> dict:
    research_block = ""
    if research:
        research_block = f"""
WEB RESEARCH (real data from Perplexity):
- Competitors: {json.dumps(research.get('competitors', []))}
- Market size: {research.get('market_size', 'unknown')}
- Reddit discussions: {json.dumps(research.get('reddit_discussions', []))}
- Pricing benchmarks: {json.dumps(research.get('pricing_benchmarks', []))}
- Trends: {json.dumps(research.get('key_trends', []))}
"""

    sentiment_block = ""
    if sentiment:
        sentiment_block = f"""
SOCIAL SENTIMENT (from X via Grok):
- Buzz: {sentiment.get('buzz_level', 'unknown')}
- Trend: {sentiment.get('trend_direction', 'unknown')}
- Sentiment: {sentiment.get('sentiment', 'unknown')}
- Pain signals: {json.dumps(sentiment.get('pain_signals', []))}
- Summary: {sentiment.get('summary', '')}
"""

    prompt = f"""You are a startup validation expert. Analyze this idea using ALL the research data below.
Use simple, clear language anyone can understand. No jargon.

IDEA: {idea}
{research_block}{sentiment_block}

Return this EXACT JSON (no markdown, no backticks):
{{
  "concept": "What this is in one sentence (max 12 words)",
  "target_user": "Who exactly needs this — be specific",
  "core_pain": "The #1 problem this solves, in plain English",
  "value_promise": "What the user gets, in one sentence",
  "category": "SaaS, Marketplace, Tool, Service, Content, Hardware, Community, API, Plugin, or Other",
  "summary": "2-3 sentences explaining your verdict. Plain English.",
  "gate1": {{
    "question": "Can you build a basic version in 7 days?",
    "answer": "YES or NO",
    "reasoning": "Why, in 1-2 sentences",
    "confidence": 80
  }},
  "gate2": {{
    "question": "Will people pay $10+ on day one?",
    "answer": "YES or NO",
    "reasoning": "Why, in 1-2 sentences",
    "confidence": 75
  }},
  "gate3": {{
    "question": "Is the pain bad enough people will switch now?",
    "answer": "YES or NO",
    "reasoning": "Why, in 1-2 sentences",
    "confidence": 70
  }},
  "pain_score": 72,
  "market_score": 65,
  "execution_score": 80,
  "timing_score": 68,
  "who_needs_this": "Describe 2-3 types of people who need this most",
  "why_now": "What makes this the right time to build this",
  "competitors_analysis": "Brief analysis of competition (use research data if available)",
  "regional_scores": [
    {{"region": "North America", "demand": 85, "reasoning": "Why"}},
    {{"region": "Europe", "demand": 60, "reasoning": "Why"}},
    {{"region": "Latin America", "demand": 50, "reasoning": "Why"}},
    {{"region": "Asia-Pacific", "demand": 40, "reasoning": "Why"}},
    {{"region": "South Asia", "demand": 55, "reasoning": "Why"}},
    {{"region": "Middle East & Africa", "demand": 35, "reasoning": "Why"}},
    {{"region": "Southeast Asia", "demand": 45, "reasoning": "Why"}}
  ],
  "timing_analysis": {{
    "readiness": "NOW or WAIT_3_MONTHS or WAIT_6_MONTHS",
    "reasoning": "Why now or why wait",
    "trend_direction": "RISING or STABLE or DECLINING",
    "trigger_event": "Recent event that makes this timely (or empty)"
  }},
  "moat_analysis": {{
    "defensibility": "LOW or MEDIUM or HIGH",
    "copy_time_days": 30,
    "moat_type": "Speed, Network, Data, Brand, or None",
    "reasoning": "How easy is it for someone to copy this"
  }},
  "next_steps": [
    "Step 1: specific action",
    "Step 2: specific action",
    "Step 3: specific action",
    "Step 4: specific action",
    "Step 5: specific action"
  ],
  "reddit_post": "Ready-to-post Reddit text (250 chars max). Conversational, lead with the pain.",
  "x_post": "Ready-to-post tweet (280 chars max) with a hook",
  "offer": "Clear 1-sentence offer",
  "price": "Suggested price point",
  "cta": "Call-to-action text",
  "final_decision": "BUILD or SKIP or MAYBE",
  "kill_reason": "If SKIP, one sentence why. Otherwise empty.",
  "one_line_pitch": "A catchy 1-line pitch for sharing"
}}

Return ONLY valid JSON."""
    raw = await _call_claude(prompt, 3500)
    return parse_json_response(raw)


# ── GPT-4o: business model & revenue ──────────────────
async def model_with_gpt(idea: str, research: Optional[dict],
                          sentiment: Optional[dict]) -> Optional[dict]:
    if not OPENAI_API_KEY:
        return None
    try:
        ctx = ""
        if research:
            ctx = f"""
Market data:
- Market size: {research.get('market_size', 'unknown')}
- Pricing benchmarks: {json.dumps(research.get('pricing_benchmarks', []))}
- Competitors: {json.dumps(research.get('competitors', []))}
"""
        prompt = f"""You are a startup business model expert. Build a realistic model for this idea.
Use simple language. Be specific with numbers.

IDEA: {idea}
{ctx}

Return this JSON (no markdown, no backticks):
{{
  "business_type": "SaaS Subscription, One-time, Marketplace, Freemium, etc.",
  "pricing_strategy": "How to price it and why",
  "suggested_price": "$X/mo or $X one-time",
  "revenue_projections": {{
    "month_1": {{"users": 10, "revenue": 290, "costs": 100}},
    "month_3": {{"users": 80, "revenue": 2320, "costs": 300}},
    "month_6": {{"users": 300, "revenue": 8700, "costs": 800}},
    "month_12": {{"users": 1000, "revenue": 29000, "costs": 2000}}
  }},
  "breakeven_month": 3,
  "year1_potential": "$87,000",
  "key_risks": ["risk 1", "risk 2", "risk 3"],
  "key_advantages": ["advantage 1", "advantage 2", "advantage 3"],
  "monetization_tips": "1-2 sentences on how to maximize revenue",
  "funding_needed": "Bootstrappable or amount needed"
}}

Return ONLY valid JSON."""
        raw = await _call_openai_api(
            "https://api.openai.com/v1", OPENAI_API_KEY, "gpt-4o", prompt, 1500
        )
        return parse_json_response(raw)
    except Exception as e:
        print(f"[GPT-4o] {e}")
        return None


# ─── SCORE CALCULATOR ─────────────────────────────────
def calculate_score(a: dict) -> int:
    s = 0
    if a.get("gate1", {}).get("answer", "").upper().startswith("YES"): s += 25
    if a.get("gate2", {}).get("answer", "").upper().startswith("YES"): s += 25
    if a.get("gate3", {}).get("answer", "").upper().startswith("YES"): s += 15
    confs = [a.get(g, {}).get("confidence", 50) for g in ["gate1", "gate2", "gate3"]
             if isinstance(a.get(g, {}).get("confidence"), (int, float))]
    if confs:
        s += int((sum(confs) / len(confs) / 100) * 15)
    regions = a.get("regional_scores", [])
    if regions:
        s += int((max((r.get("demand", 0) for r in regions), default=0) / 100) * 10)
    t = a.get("timing_analysis", {})
    if t.get("readiness") == "NOW": s += 5
    elif t.get("readiness") == "WAIT_3_MONTHS": s += 2
    m = a.get("moat_analysis", {})
    if m.get("defensibility") == "HIGH": s += 5
    elif m.get("defensibility") == "MEDIUM": s += 3
    return min(s, 100)


# ─── RESULT COMBINER ─────────────────────────────────
def combine_results(idea_text, analysis, research, sentiment, business,
                    idea_id, share_token, score):
    sources = ["claude"]
    if research: sources.append("perplexity")
    if sentiment: sources.append("grok")
    if business: sources.append("gpt-4o")

    return {
        "id": idea_id,
        "idea": idea_text,
        "concept": analysis.get("concept", ""),
        "target_user": analysis.get("target_user", ""),
        "core_pain": analysis.get("core_pain", ""),
        "value_promise": analysis.get("value_promise", ""),
        "verdict": analysis.get("final_decision", "MAYBE"),
        "score": score,
        "summary": analysis.get("summary", ""),
        "category": analysis.get("category", "Other"),
        "scores": {
            "pain": analysis.get("pain_score", 0),
            "market": analysis.get("market_score", 0),
            "execution": analysis.get("execution_score", 0),
            "timing": analysis.get("timing_score", 0),
        },
        "gates": {
            "build_fast": analysis.get("gate1", {}),
            "will_pay": analysis.get("gate2", {}),
            "urgent_pain": analysis.get("gate3", {}),
        },
        "who_needs_this": analysis.get("who_needs_this", ""),
        "why_now": analysis.get("why_now", ""),
        "competitors_analysis": analysis.get("competitors_analysis", ""),
        "next_steps": analysis.get("next_steps", []),
        "regional_scores": analysis.get("regional_scores", []),
        "timing_analysis": analysis.get("timing_analysis", {}),
        "moat_analysis": analysis.get("moat_analysis", {}),
        "research": research or {},
        "social_buzz": sentiment or {},
        "business_model": business or {},
        "content": {
            "reddit": analysis.get("reddit_post", ""),
            "tweet": analysis.get("x_post", ""),
            "pitch": analysis.get("one_line_pitch", ""),
            "offer": analysis.get("offer", ""),
            "price": analysis.get("price", ""),
            "cta": analysis.get("cta", ""),
        },
        "ai_sources": sources,
        "share_url": f"{BASE_URL}/public/idea/{share_token}",
        "kill_reason": analysis.get("kill_reason", ""),
    }


# ═════════════════════════════════════════════════════
#  APP
# ═════════════════════════════════════════════════════
app = FastAPI(title="Idea Factory", version="4.0.0",
              description="Multi-AI idea validation — personal tool")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


# ═════════════════════════════════════════════════════
#  ENDPOINTS
# ═════════════════════════════════════════════════════
@app.get("/")
async def root():
    base = os.path.join(os.path.dirname(__file__), "..", "frontend")
    for name in ["index.html", "app.html"]:
        p = os.path.join(base, name)
        if os.path.exists(p):
            with open(p) as f:
                return HTMLResponse(content=f.read())
    return {"status": "Idea Factory running", "version": "4.0.0"}


@app.get("/api/health")
def health():
    return {
        "status": "ok", "version": "4.0.0",
        "engines": {
            "claude": bool(ANTHROPIC_API_KEY),
            "perplexity": bool(PERPLEXITY_API_KEY),
            "gpt4o": bool(OPENAI_API_KEY),
            "grok": bool(GROK_API_KEY),
        }
    }


# ─── MODE TRANSFORMS ─────────────────────────────────
async def transform_idea_for_mode(idea: str, mode: str) -> str:
    """For trendy/wild modes, use Claude to remix the idea before analysis."""
    if mode == "validate":
        return idea

    if mode == "trendy":
        prompt = f"""Take this startup idea and combine it with current trending technologies,
markets, or cultural moments to create a more timely and relevant version.
Keep the core intent but make it ride a wave that's happening NOW.

ORIGINAL IDEA: {idea}

Return ONLY the remixed idea as 1-2 sentences. No explanation. No labels. Just the idea."""
    elif mode == "wild":
        prompt = f"""Take this startup idea and give it an unexpected, creative twist.
Mash it with a completely different industry, flip the business model, or find an angle
nobody would think of. Make it weird but viable.

ORIGINAL IDEA: {idea}

Return ONLY the wild remix as 1-2 sentences. No explanation. No labels. Just the idea."""
    else:
        return idea

    try:
        return (await _call_claude(prompt, 300)).strip('"').strip()
    except Exception:
        return idea


@app.post("/api/analyze")
async def analyze_idea(data: AnalyzeRequest, request: Request, response: Response):
    """Multi-AI analysis streamed via Server-Sent Events."""
    idea_text = (data.idea or "").strip()
    mode = (data.mode or "validate").strip().lower()
    if mode not in ("validate", "trendy", "wild"):
        mode = "validate"
    if not idea_text:
        raise HTTPException(400, "Tell me your idea — even a rough sentence works")

    # Rate limit: track per session
    db_rate = SessionLocal()
    try:
        sess = _get_or_create_session(request, db_rate)
        if not sess.is_pro and sess.validations_count >= FREE_TIER_LIMIT:
            raise HTTPException(429, f"Free tier limit reached ({FREE_TIER_LIMIT} validations). Upgrade to Pro for unlimited access.")
        response.set_cookie("session_id", sess.session_id, max_age=86400 * 365, httponly=True, samesite="lax")
    finally:
        db_rate.close()

    async def stream():
        original_idea = idea_text

        try:
            # ── Mode Transform (trendy/wild) ─────────────────
            if mode != "validate":
                mode_label = "Remixing with trending markets..." if mode == "trendy" else "Generating a wild twist..."
                yield sse("step", {"ai": "mode", "status": "start", "label": mode_label})
                transformed = await transform_idea_for_mode(idea_text, mode)
                yield sse("step", {"ai": "mode", "status": "done",
                                   "summary": transformed})
                working_idea = transformed
            else:
                working_idea = idea_text

            # ── Step 1: Research + Sentiment (parallel) ──────
            yield sse("step", {"ai": "perplexity", "status": "start",
                               "label": "Searching the web for competitors & market data..."})
            yield sse("step", {"ai": "grok", "status": "start",
                               "label": "Scanning X for what people are saying..."})

            research, sentiment = await asyncio.gather(
                research_with_perplexity(working_idea),
                scan_with_grok(working_idea),
            )

            if research:
                n = len(research.get("competitors", []))
                yield sse("step", {"ai": "perplexity", "status": "done",
                                   "summary": f"Found {n} competitors & market data"})
            else:
                yield sse("step", {"ai": "perplexity", "status": "skipped",
                                   "summary": "No API key — skipped"})

            if sentiment:
                yield sse("step", {"ai": "grok", "status": "done",
                                   "summary": sentiment.get("summary", "Social data collected")})
            else:
                yield sse("step", {"ai": "grok", "status": "skipped",
                                   "summary": "No API key — skipped"})

            # ── Step 2: Analysis + Business Model (parallel) ─
            yield sse("step", {"ai": "claude", "status": "start",
                               "label": "Running deep strategic analysis..."})
            yield sse("step", {"ai": "gpt", "status": "start",
                               "label": "Building business model & revenue projections..."})

            analysis, business = await asyncio.gather(
                analyze_with_claude(working_idea, research, sentiment),
                model_with_gpt(working_idea, research, sentiment),
            )

            yield sse("step", {"ai": "claude", "status": "done",
                               "summary": "Analysis complete"})
            if business:
                yield sse("step", {"ai": "gpt", "status": "done",
                                   "summary": f"Year 1 potential: {business.get('year1_potential', 'calculated')}"})
            else:
                yield sse("step", {"ai": "gpt", "status": "skipped",
                                   "summary": "No API key — skipped"})

            # ── Step 3: Score & Save ─────────────────────────
            idea_id = str(uuid.uuid4())[:8]
            share_token = secrets.token_urlsafe(12)
            score = calculate_score(analysis)
            result = combine_results(working_idea, analysis, research, sentiment,
                                     business, idea_id, share_token, score)
            result["mode"] = mode
            if mode != "validate":
                result["original_idea"] = original_idea

            db = SessionLocal()
            try:
                db.add(IdeaDB(
                    id=idea_id, raw_idea=original_idea,
                    concept=analysis.get("concept", ""),
                    target_user=analysis.get("target_user", ""),
                    core_pain=analysis.get("core_pain", ""),
                    value_promise=analysis.get("value_promise", ""),
                    g1=analysis.get("gate1", {}).get("question", ""),
                    g1r=f"{analysis.get('gate1', {}).get('answer', '')} — {analysis.get('gate1', {}).get('reasoning', '')}",
                    g2=analysis.get("gate2", {}).get("question", ""),
                    g2r=f"{analysis.get('gate2', {}).get('answer', '')} — {analysis.get('gate2', {}).get('reasoning', '')}",
                    g3=analysis.get("gate3", {}).get("question", ""),
                    g3r=f"{analysis.get('gate3', {}).get('answer', '')} — {analysis.get('gate3', {}).get('reasoning', '')}",
                    reddit=analysis.get("reddit_post", ""),
                    x_post=analysis.get("x_post", ""),
                    offer=analysis.get("offer", ""),
                    price=analysis.get("price", ""),
                    cta=analysis.get("cta", ""),
                    final_decision=analysis.get("final_decision", "MAYBE"),
                    score=score,
                    ai_response=result,
                    is_public=True,
                    share_token=share_token,
                    category=analysis.get("category", "Other"),
                    regional_scores=analysis.get("regional_scores"),
                    timing_analysis=analysis.get("timing_analysis"),
                    moat_analysis=analysis.get("moat_analysis"),
                    perplexity_research=research,
                    grok_sentiment=sentiment,
                    gpt_business=business,
                    pain_who=analysis.get("target_user", ""),
                    pain_freq="AI-researched",
                ))
                stats = db.query(StatsDB).first()
                if stats:
                    stats.validated += 1
                    stats.week += 1
                else:
                    db.add(StatsDB(validated=1, week=1))
                # Increment session validation count
                sid = request.cookies.get("session_id")
                if sid:
                    user_sess = db.query(UserSessionDB).filter(UserSessionDB.session_id == sid).first()
                    if user_sess:
                        user_sess.validations_count += 1
                db.commit()
            except Exception:
                traceback.print_exc()
            finally:
                db.close()

            yield sse("result", result)


        except Exception as e:
            traceback.print_exc()
            yield sse("error", {"message": f"Analysis failed: {e}. Please try again."})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/signal")
async def log_signal(signal: SignalUpdate, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == signal.idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    if signal.signal_type == "pay":   idea.pay += 1
    elif signal.signal_type == "rep": idea.rep += 1
    elif signal.signal_type == "clk": idea.clk += 1
    db.commit()
    return {"status": "ok", "pay": idea.pay, "rep": idea.rep, "clk": idea.clk}


@app.get("/api/ideas")
async def get_ideas(db: Session = Depends(get_db)):
    ideas = db.query(IdeaDB).order_by(IdeaDB.date.desc()).limit(100).all()
    return [{"id": i.id, "concept": i.concept, "score": i.score,
             "verdict": i.final_decision, "category": i.category,
             "date": i.date.isoformat() if i.date else None,
             "share_url": f"{BASE_URL}/public/idea/{i.share_token}" if i.share_token else None}
            for i in ideas]


@app.get("/api/idea/{idea_id}")
async def get_idea(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    return idea.ai_response or {"id": idea.id, "concept": idea.concept,
                                 "score": idea.score, "verdict": idea.final_decision}


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    s = db.query(StatsDB).first()
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    avg = db.query(func.avg(IdeaDB.score)).scalar() or 0
    top = db.query(func.max(IdeaDB.score)).scalar() or 0
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ideas_today = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= today_start).scalar() or 0
    total_upgrades = db.query(func.count(UserSessionDB.session_id)).filter(UserSessionDB.is_pro == True).scalar() or 0
    return {
        "validated": s.validated if s else 0,
        "built": s.built if s else 0,
        "killed": s.killed if s else 0,
        "week": s.week if s else 0,
        "total_ideas": total,
        "avg_score": round(avg),
        "top_score": top,
        "ideas_today": ideas_today,
        "total_upgrades": total_upgrades,
    }


@app.post("/api/decision/{idea_id}")
async def finalize_decision(idea_id: str, decision: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    idea.final_decision = decision
    s = db.query(StatsDB).first()
    if s:
        if decision in ("KILL", "SKIP"): s.killed += 1
        elif decision == "BUILD": s.built += 1
    db.commit()
    return {"status": "ok", "decision": decision}


@app.post("/api/email/capture")
async def capture_email(data: EmailCaptureInput, db: Session = Depends(get_db)):
    db.add(EmailCaptureDB(email=data.email, idea_id=data.idea_id,
                          source=data.source, tags=data.tags))
    db.commit()
    return {"status": "captured"}


# ═════════════════════════════════════════════════════
#  PDF REPORT
# ═════════════════════════════════════════════════════
@app.get("/api/idea/{idea_id}/pdf")
async def pdf_report(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    def safe(t):
        if not t: return "N/A"
        return str(t).encode("latin-1", "ignore").decode("latin-1")

    # Cover
    pdf.add_page()
    pdf.set_fill_color(8, 8, 8)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(200, 255, 0)
    pdf.set_font("Helvetica", "B", 32)
    pdf.ln(60)
    pdf.cell(0, 15, "IDEA FACTORY", ln=True, align="C")
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 10, "Multi-AI Validation Report", ln=True, align="C")
    pdf.ln(30)
    pdf.set_text_color(239, 239, 239)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 10, safe(idea.concept or "Untitled"), align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, safe(f"Score: {idea.score}/100  |  Verdict: {idea.final_decision}"), ln=True, align="C")
    sources = []
    if idea.ai_response and isinstance(idea.ai_response, dict):
        sources = idea.ai_response.get("ai_sources", ["claude"])
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, safe(f"Powered by: {', '.join(s.upper() for s in sources)}"), ln=True, align="C")

    # Summary
    pdf.add_page()
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Summary", ln=True)
    pdf.ln(8)
    for lbl, val in [("Concept", idea.concept), ("Who Needs This", idea.target_user),
                     ("Biggest Problem", idea.core_pain), ("What They Get", idea.value_promise),
                     ("Category", idea.category), ("Score", f"{idea.score}/100")]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 8, lbl.upper())
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 8, safe(str(val) if val else "N/A"))
        pdf.ln(2)

    # Gates
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "3 Key Questions", ln=True)
    pdf.ln(8)
    for name, result in [("Can you build it fast?", idea.g1r),
                          ("Will people pay?", idea.g2r),
                          ("Is it urgent?", idea.g3r)]:
        rs = str(result) if result else "N/A"
        ok = rs.upper().startswith("YES")
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, name, ln=True)
        if ok: pdf.set_text_color(0, 160, 80)
        else: pdf.set_text_color(220, 50, 50)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(20, 7, "YES" if ok else "NO")
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "", 10)
        parts = rs.split("\u2014", 1)
        pdf.multi_cell(0, 7, safe(parts[1].strip() if len(parts) > 1 else rs))
        pdf.ln(4)

    # Content
    pdf.add_page()
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Ready-to-Post Content", ln=True)
    pdf.ln(8)
    for lbl, val in [("Reddit Post", idea.reddit), ("Tweet", idea.x_post),
                     ("Offer", idea.offer), ("Price", idea.price), ("CTA", idea.cta)]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, lbl.upper(), ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 7, safe(str(val) if val else "N/A"))
        pdf.ln(4)

    # Competitors from Perplexity
    if idea.perplexity_research and isinstance(idea.perplexity_research, dict):
        comps = idea.perplexity_research.get("competitors", [])
        if comps:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(0, 12, "Competitors Found", ln=True)
            pdf.ln(8)
            for c in comps:
                pdf.set_font("Helvetica", "B", 12)
                pdf.cell(0, 8, safe(c.get("name", "?")), ln=True)
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 6, safe(f"Price: {c.get('price', '?')}  |  Weakness: {c.get('weakness', '?')}"), ln=True)
                pdf.set_text_color(30, 30, 30)
                pdf.ln(4)

    # Business model from GPT
    if idea.gpt_business and isinstance(idea.gpt_business, dict):
        biz = idea.gpt_business
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 12, "Business Model", ln=True)
        pdf.ln(8)
        for lbl, val in [("Type", biz.get("business_type")),
                         ("Price", biz.get("suggested_price")),
                         ("Year 1", biz.get("year1_potential")),
                         ("Break Even", f"Month {biz.get('breakeven_month', '?')}"),
                         ("Funding", biz.get("funding_needed"))]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(45, 8, lbl.upper())
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 8, safe(str(val) if val else "N/A"))
            pdf.ln(2)

    buf = io.BytesIO(pdf.output())
    buf.seek(0)
    fn = f"idea_factory_{idea.id}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})


# ═════════════════════════════════════════════════════
#  PREMIUM FEATURES (no paywall)
# ═════════════════════════════════════════════════════
@app.get("/api/idea/{idea_id}/premium-report")
async def premium_report(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    if idea.blueprint and idea.revenue_sim:
        return {"idea_id": idea_id, "blueprint": idea.blueprint,
                "revenue_sim": idea.revenue_sim, "mvp_plan": idea.mvp_plan,
                "distribution_plan": idea.distribution_plan}

    prompt = f"""Generate a build plan for this validated idea. Simple language.

IDEA: {idea.concept}
TARGET: {idea.target_user}
PAIN: {idea.core_pain}
SCORE: {idea.score}/100

Return ONLY JSON:
{{
  "blueprint": {{
    "product_name": "Suggested name",
    "tagline": "10-word tagline",
    "tech_stack": ["tech1", "tech2", "tech3"],
    "mvp_features": ["f1", "f2", "f3", "f4", "f5"],
    "day1_actions": ["a1", "a2", "a3"],
    "week1_milestones": ["m1", "m2", "m3"],
    "pricing_model": "How to price",
    "competitive_advantage": "What makes it hard to copy"
  }},
  "revenue_sim": {{
    "month1": {{"users": 10, "revenue": 290, "costs": 50}},
    "month3": {{"users": 50, "revenue": 1450, "costs": 150}},
    "month6": {{"users": 200, "revenue": 5800, "costs": 400}},
    "month12": {{"users": 800, "revenue": 23200, "costs": 1200}},
    "break_even_month": 2,
    "assumptions": "Key assumptions"
  }},
  "mvp_plan": {{
    "total_hours": 40,
    "phases": [
      {{"name": "Phase 1", "hours": 16, "tasks": ["t1", "t2", "t3"]}},
      {{"name": "Phase 2", "hours": 8, "tasks": ["t1", "t2"]}},
      {{"name": "Phase 3", "hours": 16, "tasks": ["t1", "t2", "t3"]}}
    ],
    "tools_needed": ["tool1", "tool2"]
  }},
  "distribution_plan": {{
    "channels": [{{"name": "Channel", "strategy": "How", "priority": "HIGH"}}],
    "launch_sequence": ["Step 1", "Step 2", "Step 3"],
    "content_ideas": ["c1", "c2", "c3"]
  }}
}}"""
    try:
        r = parse_json_response(await _call_claude(prompt, 3000))
    except Exception as e:
        raise HTTPException(503, f"AI temporarily unavailable: {e}")
    idea.blueprint = r.get("blueprint")
    idea.revenue_sim = r.get("revenue_sim")
    idea.mvp_plan = r.get("mvp_plan")
    idea.distribution_plan = r.get("distribution_plan")
    db.commit()
    return {"idea_id": idea_id, "blueprint": idea.blueprint,
            "revenue_sim": idea.revenue_sim, "mvp_plan": idea.mvp_plan,
            "distribution_plan": idea.distribution_plan}


@app.get("/api/idea/{idea_id}/landing-page")
async def generate_landing_page(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    if idea.landing_page_html:
        return HTMLResponse(content=idea.landing_page_html)
    prompt = f"""Generate a complete landing page HTML for this product. Single file, embedded CSS/JS.
Dark theme (#080808 bg, #c8ff00 accent). Include: hero, pain points, solution, pricing, FAQ, footer.

PRODUCT: {idea.concept}
TARGET: {idea.target_user}
PAIN: {idea.core_pain}
PRICE: {idea.price}
CTA: {idea.cta}

Return ONLY HTML. No markdown."""
    try:
        html = await _call_claude(prompt, 4000)
    except Exception as e:
        raise HTTPException(503, f"AI temporarily unavailable: {e}")
    if html.startswith("```"):
        lines = html.split("\n")
        html = "\n".join(lines[1:-1])
    idea.landing_page_html = html
    db.commit()
    return HTMLResponse(content=html)


@app.get("/api/idea/{idea_id}/twitter-thread")
async def twitter_thread(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    if idea.twitter_thread:
        return {"idea_id": idea_id, "thread": idea.twitter_thread}
    prompt = f"""Write a viral 5-tweet thread about this startup idea.
IDEA: {idea.concept} | TARGET: {idea.target_user} | SCORE: {idea.score}/100
Format: numbered (1/5…). Each max 280 chars. Return ONLY the thread."""
    try:
        t = await _call_claude(prompt, 1500)
    except Exception as e:
        raise HTTPException(503, f"AI temporarily unavailable: {e}")
    idea.twitter_thread = t
    db.commit()
    return {"idea_id": idea_id, "thread": t}


# ═════════════════════════════════════════════════════
#  ADMIN
# ═════════════════════════════════════════════════════
@app.get("/api/admin/dashboard")
async def admin_dashboard(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    avg = db.query(func.avg(IdeaDB.score)).scalar() or 0
    builds = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%BUILD%")).scalar() or 0
    top = db.query(IdeaDB).order_by(IdeaDB.score.desc()).limit(5).all()
    pro_users = db.query(func.count(UserSessionDB.session_id)).filter(UserSessionDB.is_pro == True).scalar() or 0
    emails = db.query(func.count(EmailCaptureDB.id)).scalar() or 0
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ideas_today = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= today_start).scalar() or 0
    return {
        "total_ideas": total,
        "avg_score": round(avg),
        "builds": builds,
        "top_ideas": [{"id": i.id, "concept": i.concept, "score": i.score} for i in top],
        "overview": {
            "total_ideas": total,
            "avg_score": round(avg),
            "builds": builds,
            "pro_users": pro_users,
            "emails_captured": emails,
            "ideas_today": ideas_today,
        },
        "revenue": {
            "pro_users": pro_users,
            "mrr_estimate": pro_users * 29,
            "total_upgrades": pro_users,
        },
        "next_actions": [
            f"You have {emails} emails captured — consider sending a newsletter",
            f"{builds} ideas marked BUILD — follow up with users",
            f"Average score is {round(avg)}/100 — {'strong pipeline' if avg >= 60 else 'needs more ideas'}",
        ],
    }


@app.post("/api/cron/auto-rank")
async def auto_rank(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    ideas = db.query(IdeaDB).filter(IdeaDB.score > 0).all()
    updated = 0
    for i in ideas:
        bonus = (i.pay or 0) * 10 + (i.rep or 0) * 3 + (i.clk or 0)
        t = i.score + min(bonus, 30)
        new = "BUILD" if t >= 80 else "MAYBE" if t >= 50 else "SKIP"
        if i.final_decision != new:
            i.final_decision = new
            updated += 1
    db.commit()
    return {"checked": len(ideas), "updated": updated, "ideas_checked": len(ideas)}


# ═════════════════════════════════════════════════════
#  PUBLIC PAGES
# ═════════════════════════════════════════════════════

def _html_head(title, desc):
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title><meta name="description" content="{desc}">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#080808;--sf:#111;--bd:#1e1e1e;--tx:#eee;--mt:#666;--ac:#c8ff00;--gn:#00e87a;--rd:#ff3b3b;--or:#ff9f1c;--fn:'Inter',system-ui,sans-serif;--mn:'JetBrains Mono',monospace}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:var(--fn)}}
.ctr{{max-width:900px;margin:0 auto;padding:30px 20px}}
h1{{font-size:32px;font-weight:800;margin-bottom:6px}}
.sub{{font-family:var(--mn);font-size:11px;color:var(--mt);text-transform:uppercase;letter-spacing:.15em;margin-bottom:24px}}
.cd{{background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:20px;margin-bottom:12px}}
.cd:hover{{border-color:#333}}
.bg{{display:inline-block;padding:3px 10px;border-radius:20px;font-family:var(--mn);font-size:10px;text-transform:uppercase}}
.bg-s{{background:rgba(255,59,59,.12);color:var(--rd)}}.bg-b{{background:rgba(0,232,122,.12);color:var(--gn)}}.bg-m{{background:rgba(200,255,0,.12);color:var(--ac)}}
.bar{{height:5px;background:var(--bd);border-radius:3px;margin:6px 0;overflow:hidden}}.bar-f{{height:100%;border-radius:3px}}
.meta{{font-family:var(--mn);font-size:10px;color:var(--mt)}}
.btn{{display:inline-block;background:var(--ac);color:var(--bg);padding:10px 20px;border-radius:8px;font-family:var(--mn);font-size:11px;font-weight:600;cursor:pointer;border:none;text-decoration:none}}
.btn:hover{{opacity:.9}}
nav{{display:flex;gap:20px;margin-bottom:24px;padding-bottom:14px;border-bottom:1px solid var(--bd);align-items:center;flex-wrap:wrap}}
nav a{{font-family:var(--mn);font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--mt);text-decoration:none}}
nav a:hover,nav a.active{{color:var(--ac)}}
.nb{{font-weight:800;font-size:16px;color:var(--ac)!important;margin-right:auto}}
.sr{{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}}
.st{{background:var(--sf);border:1px solid var(--bd);border-radius:10px;padding:14px;flex:1;min-width:100px;text-align:center}}
.sn{{font-size:24px;font-weight:800;color:var(--ac)}}.sl{{font-family:var(--mn);font-size:9px;color:var(--mt);text-transform:uppercase;margin-top:2px}}
a{{color:var(--ac);text-decoration:none}}
</style></head>"""

def _nav(active=""):
    return f"""<nav>
  <a href="/" class="nb">IDEA FACTORY</a>
  <a href="/public/graveyard" class="{'active'if active=='graveyard'else''}">Graveyard</a>
  <a href="/public/leaderboard" class="{'active'if active=='leaderboard'else''}">Leaderboard</a>
</nav>"""


@app.get("/public/graveyard", response_class=HTMLResponse)
async def graveyard(category: Optional[str] = None, page: int = Query(1, ge=1),
                    db: Session = Depends(get_db)):
    pp = 20
    q = db.query(IdeaDB).filter(IdeaDB.is_public == True,
        (IdeaDB.final_decision.ilike("%KILL%")) | (IdeaDB.final_decision.ilike("%SKIP%")))
    if category: q = q.filter(IdeaDB.category == category)
    total = q.count()
    ideas = q.order_by(IdeaDB.date.desc()).offset((page-1)*pp).limit(pp).all()

    cards = ""
    for i in ideas:
        reason = ""
        if i.ai_response and isinstance(i.ai_response, dict):
            reason = i.ai_response.get("kill_reason", "") or i.ai_response.get("summary", "")
        ds = i.date.strftime("%b %d, %Y") if i.date else ""
        lk = f"/public/idea/{i.share_token}" if i.share_token else "#"
        cards += f'<div class="cd"><div style="display:flex;gap:10px"><span style="font-size:22px">💀</span><div style="flex:1"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px"><a href="{lk}" style="font-weight:700;color:var(--tx)">{i.concept or "Untitled"}</a><span class="bg bg-s">SKIPPED</span></div><div style="font-size:12px;color:var(--mt);margin:4px 0">{(reason or "")[:120]}</div><div class="bar"><div class="bar-f" style="width:{i.score}%;background:var(--rd)"></div></div><div class="meta">{i.score}/100 · {i.category or "Other"} · {ds}</div></div></div></div>'

    return HTMLResponse(f"""{_html_head("Idea Graveyard",f"{total} skipped ideas")}
<body><div class="ctr">{_nav("graveyard")}
<h1>💀 Idea Graveyard</h1><p class="sub">{total} ideas that didn't make it</p>
<div class="sr"><div class="st"><div class="sn">{total}</div><div class="sl">Skipped</div></div></div>
{cards or '<div class="cd" style="text-align:center;padding:30px;color:var(--mt)">No skipped ideas yet.</div>'}
</div></body></html>""")


@app.get("/public/leaderboard", response_class=HTMLResponse)
async def leaderboard(db: Session = Depends(get_db)):
    ideas = db.query(IdeaDB).filter(IdeaDB.is_public == True, IdeaDB.score > 0).order_by(IdeaDB.score.desc()).limit(50).all()
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    avg = db.query(func.avg(IdeaDB.score)).filter(IdeaDB.is_public == True).scalar() or 0
    builds = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%BUILD%")).scalar() or 0

    rows = ""
    for rank, i in enumerate(ideas, 1):
        dec = i.final_decision or "MAYBE"
        bc = "bg-b" if "BUILD" in dec.upper() else "bg-s" if "SKIP" in dec.upper() or "KILL" in dec.upper() else "bg-m"
        sc = "var(--gn)" if i.score >= 70 else "var(--or)" if i.score >= 40 else "var(--rd)"
        lk = f"/public/idea/{i.share_token}" if i.share_token else "#"
        md = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
        rows += f'<div class="cd" style="display:flex;align-items:center;gap:14px"><div style="font-size:{20 if rank<=3 else 13}px;font-weight:800;min-width:36px;text-align:center">{md}</div><div style="flex:1"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px"><a href="{lk}" style="font-weight:700;color:var(--tx)">{i.concept or "Untitled"}</a><span class="bg {bc}">{dec}</span></div><div style="font-size:11px;color:var(--mt);margin-top:3px">{i.target_user or ""} · {i.category or "Other"}</div><div class="bar"><div class="bar-f" style="width:{i.score}%;background:{sc}"></div></div></div><div style="text-align:center;min-width:50px"><div style="font-size:22px;font-weight:800;color:{sc}">{i.score}</div><div class="meta">/100</div></div></div>'

    return HTMLResponse(f"""{_html_head("Leaderboard",f"Top {len(ideas)} ideas")}
<body><div class="ctr">{_nav("leaderboard")}
<h1>🏆 Leaderboard</h1><p class="sub">Top ideas by multi-AI score</p>
<div class="sr"><div class="st"><div class="sn">{total}</div><div class="sl">Validated</div></div>
<div class="st"><div class="sn">{round(avg)}</div><div class="sl">Avg Score</div></div>
<div class="st"><div class="sn">{builds}</div><div class="sl">Worth Building</div></div></div>
{rows or '<div class="cd" style="text-align:center;padding:30px;color:var(--mt)">No ideas yet.</div>'}
</div></body></html>""")


@app.get("/public/idea/{share_token}", response_class=HTMLResponse)
async def public_idea(share_token: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.share_token == share_token).first()
    if not idea:
        raise HTTPException(404, "Idea not found")
    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    dec = idea.final_decision or "MAYBE"
    bc = "bg-b" if "BUILD" in dec.upper() else "bg-s" if "SKIP" in dec.upper() or "KILL" in dec.upper() else "bg-m"
    sc = "var(--gn)" if idea.score >= 70 else "var(--or)" if idea.score >= 40 else "var(--rd)"
    emo = "🚀" if "BUILD" in dec.upper() else "💀" if "SKIP" in dec.upper() or "KILL" in dec.upper() else "🧪"
    ds = idea.date.strftime("%B %d, %Y") if idea.date else ""

    gates = ""
    for ql, r in [("Can you build it fast?", idea.g1r), ("Will people pay?", idea.g2r), ("Is it urgent?", idea.g3r)]:
        rs = str(r) if r else "N/A"
        ok = rs.upper().startswith("YES")
        parts = rs.split("\u2014", 1)
        reason = parts[1].strip() if len(parts) > 1 else rs
        c = "var(--gn)" if ok else "var(--rd)"
        gates += f'<div style="background:var(--bg);border:1px solid {c};border-radius:10px;padding:14px;text-align:center"><div class="meta">{ql}</div><div style="font-size:20px;font-weight:800;color:{c};margin:4px 0">{"YES" if ok else "NO"}</div><div style="font-size:10px;color:var(--mt)">{reason[:100]}</div></div>'

    srcs = []
    if idea.ai_response and isinstance(idea.ai_response, dict):
        srcs = idea.ai_response.get("ai_sources", [])
    chips = " ".join(f'<span style="background:var(--sf);border:1px solid var(--bd);padding:2px 8px;border-radius:12px;font-family:var(--mn);font-size:9px;color:var(--ac)">{s.upper()}</span>' for s in srcs)

    return HTMLResponse(f"""{_html_head(f"{idea.concept} — {idea.score}/100", idea.value_promise or "")}
<body><div class="ctr">{_nav("")}
<div style="text-align:center;margin-bottom:24px"><div style="font-size:44px">{emo}</div>
<h1 style="color:var(--tx)">{idea.concept or "Untitled"}</h1>
<div style="margin:10px 0"><span class="bg {bc}" style="font-size:12px;padding:5px 14px">{dec}</span></div>
<div class="meta">{ds} · {idea.category or "Other"} · {idea.view_count or 0} views</div>
<div style="margin-top:8px">{chips}</div></div>
<div class="cd" style="text-align:center"><div style="font-size:52px;font-weight:800;color:{sc}">{idea.score}</div><div class="meta">SCORE / 100</div>
<div class="bar" style="max-width:260px;margin:6px auto;height:8px"><div class="bar-f" style="width:{idea.score}%;background:{sc};height:100%"></div></div></div>
<div class="cd"><div class="meta" style="margin-bottom:10px">ABOUT THIS IDEA</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
<div><div class="meta">WHO NEEDS THIS</div><div style="margin-top:3px;font-size:14px">{idea.target_user or "N/A"}</div></div>
<div><div class="meta">BIGGEST PROBLEM</div><div style="margin-top:3px;font-size:14px">{idea.core_pain or "N/A"}</div></div>
<div><div class="meta">WHAT THEY GET</div><div style="margin-top:3px;font-size:14px">{idea.value_promise or "N/A"}</div></div>
<div><div class="meta">PRICE POINT</div><div style="margin-top:3px;font-size:14px">{idea.price or "N/A"}</div></div></div></div>
<div class="cd"><div class="meta" style="margin-bottom:10px">3 KEY QUESTIONS</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">{gates}</div></div>
<div class="cd" style="text-align:center"><div class="meta" style="margin-bottom:10px">SHARE</div>
<a class="btn" href="/api/idea/{idea.id}/pdf" target="_blank" style="margin:4px">Download PDF</a>
<a class="btn" href="/" style="margin:4px;background:0 0;border:1px solid var(--ac);color:var(--ac)">Validate Your Idea</a></div>
</div></body></html>""")


# ═════════════════════════════════════════════════════
#  TRENDS
# ═════════════════════════════════════════════════════
@app.get("/api/trends")
async def trends(db: Session = Depends(get_db)):
    cats = db.query(IdeaDB.category, func.count(IdeaDB.id), func.avg(IdeaDB.score)).group_by(IdeaDB.category).all()
    decs = db.query(IdeaDB.final_decision, func.count(IdeaDB.id)).group_by(IdeaDB.final_decision).all()
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    return {
        "categories": [{"name": c[0], "count": c[1], "avg_score": round(c[2] or 0)} for c in cats if c[0]],
        "decisions": [{"decision": d[0], "count": d[1]} for d in decs if d[0]],
        "total_ideas": total,
    }


# ═════════════════════════════════════════════════════
#  USER SESSION & STATUS
# ═════════════════════════════════════════════════════
@app.get("/api/user/status")
async def user_status(request: Request, response: Response, db: Session = Depends(get_db)):
    sess = _get_or_create_session(request, db)
    remaining = max(0, FREE_TIER_LIMIT - sess.validations_count) if not sess.is_pro else 999
    response.set_cookie("session_id", sess.session_id, max_age=86400 * 365, httponly=True, samesite="lax")
    return {
        "is_pro": sess.is_pro,
        "validations_this_month": sess.validations_count,
        "validations_limit": FREE_TIER_LIMIT if not sess.is_pro else 999,
        "validations_remaining": remaining,
        "referral_code": sess.referral_code,
        "referral_credits": sess.referral_credits,
        "is_first_session": sess.validations_count == 0,
    }


# ═════════════════════════════════════════════════════
#  REFERRAL SYSTEM
# ═════════════════════════════════════════════════════
@app.post("/api/referral/apply")
async def apply_referral(data: ReferralInput, request: Request, response: Response,
                          db: Session = Depends(get_db)):
    if not data.code:
        raise HTTPException(400, "Referral code required")
    # Find the referrer
    referrer = db.query(UserSessionDB).filter(
        UserSessionDB.referral_code == data.code.upper()
    ).first()
    if not referrer:
        raise HTTPException(404, "Referral code not found")
    sess = _get_or_create_session(request, db)
    if sess.referred_by:
        raise HTTPException(400, "You have already applied a referral code")
    if sess.session_id == referrer.session_id:
        raise HTTPException(400, "You cannot use your own referral code")
    # Grant credits to both
    sess.referred_by = data.code.upper()
    sess.referral_credits += 1
    referrer.referral_credits += 1
    db.commit()
    response.set_cookie("session_id", sess.session_id, max_age=86400 * 365, httponly=True, samesite="lax")
    return {"status": "applied", "credits_granted": 1, "referrer_credited": True}


# ═════════════════════════════════════════════════════
#  STRIPE CHECKOUT
# ═════════════════════════════════════════════════════
_PRODUCT_PRICES = {
    "pro_monthly": {"price": STRIPE_PRICE_PRO_MONTHLY, "amount": 2900, "label": "Pro Monthly"},
    "single_report": {"price": None, "amount": 900, "label": "Single Premium Report"},
    "api_monthly": {"price": STRIPE_PRICE_API_MONTHLY, "amount": 4900, "label": "API Access Monthly"},
}

@app.post("/api/checkout/create-session")
async def create_checkout_session(data: CheckoutInput, request: Request, db: Session = Depends(get_db)):
    if not STRIPE_ENABLED or not _stripe_module:
        raise HTTPException(503, "Payment processing not configured. Contact the admin.")
    product = _PRODUCT_PRICES.get(data.product_type)
    if not product:
        raise HTTPException(400, f"Unknown product type: {data.product_type}")
    sess = _get_or_create_session(request, db)
    try:
        success_url = f"{BASE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}&type={data.product_type}"
        cancel_url = f"{BASE_URL}/checkout/cancel"
        if data.product_type == "single_report":
            # One-time payment
            checkout = _stripe_module.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{"price_data": {
                    "currency": "usd",
                    "product_data": {"name": product["label"]},
                    "unit_amount": product["amount"],
                }, "quantity": 1}],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"session_id": sess.session_id, "product_type": data.product_type,
                           "idea_id": data.idea_id or ""},
            )
        else:
            # Subscription
            if not product["price"]:
                raise HTTPException(503, f"Price ID for {data.product_type} not configured")
            checkout = _stripe_module.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{"price": product["price"], "quantity": 1}],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"session_id": sess.session_id, "product_type": data.product_type},
            )
        return {"url": checkout.url, "session_id": checkout.id}
    except Exception as e:
        raise HTTPException(503, f"Payment error: {e}")


@app.get("/checkout/success", response_class=HTMLResponse)
async def checkout_success(request: Request, db: Session = Depends(get_db),
                            type: str = Query("pro_monthly")):
    sess = _get_or_create_session(request, db)
    # Mark as pro
    sess.is_pro = True
    db.commit()
    label = _PRODUCT_PRICES.get(type, {}).get("label", "your plan")
    return HTMLResponse(f"""{_html_head("Payment Successful", "Welcome to Idea Factory Pro")}
<body><div class="ctr" style="text-align:center;padding-top:60px">
<div style="font-size:52px">🎉</div>
<h1 style="color:var(--ac);margin-top:16px">Payment Successful!</h1>
<p style="color:var(--mt);font-family:var(--mn);margin-top:8px">You now have access to {label}</p>
<a class="btn" href="/" style="display:inline-block;margin-top:24px">Start Validating Ideas →</a>
</div></body></html>""")


@app.get("/checkout/cancel", response_class=HTMLResponse)
async def checkout_cancel():
    return HTMLResponse(f"""{_html_head("Payment Cancelled", "No charge was made")}
<body><div class="ctr" style="text-align:center;padding-top:60px">
<div style="font-size:52px">😕</div>
<h1 style="margin-top:16px">Payment Cancelled</h1>
<p style="color:var(--mt);font-family:var(--mn);margin-top:8px">No charge was made. You can try again anytime.</p>
<a class="btn" href="/" style="display:inline-block;margin-top:24px">Back to Idea Factory</a>
</div></body></html>""")


@app.post("/api/checkout/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    if not payload:
        raise HTTPException(400, "Empty webhook body")
    sig = request.headers.get("stripe-signature", "")
    if not STRIPE_ENABLED or not _stripe_module:
        raise HTTPException(503, "Stripe not configured")
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = _stripe_module.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {e}")

    if event.get("type") in ("checkout.session.completed", "invoice.payment_succeeded"):
        obj = event.get("data", {}).get("object", {})
        meta = obj.get("metadata", {})
        sid = meta.get("session_id")
        if sid:
            sess = db.query(UserSessionDB).filter(UserSessionDB.session_id == sid).first()
            if sess:
                sess.is_pro = True
                sess.stripe_customer_id = obj.get("customer", "")
                db.commit()
    return {"status": "ok"}


# ═════════════════════════════════════════════════════
#  ADMIN — EMAILS & DIGEST
# ═════════════════════════════════════════════════════
@app.get("/api/emails")
async def list_emails(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    emails = db.query(EmailCaptureDB).order_by(EmailCaptureDB.captured_at.desc()).limit(500).all()
    return [{"id": e.id, "email": e.email, "source": e.source,
             "captured_at": e.captured_at.isoformat() if e.captured_at else None,
             "idea_id": e.idea_id, "tags": e.tags} for e in emails]


@app.get("/api/admin/daily-digest")
async def daily_digest(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ideas_today = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= today).scalar() or 0
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    builds = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%BUILD%")).scalar() or 0
    pro_users = db.query(func.count(UserSessionDB.session_id)).filter(UserSessionDB.is_pro == True).scalar() or 0
    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "three_numbers": {
            "ideas_today": ideas_today,
            "total_ideas": total,
            "pro_users": pro_users,
        },
        "builds": builds,
        "mrr": pro_users * 29,
        "summary": f"{ideas_today} ideas validated today. {builds} marked BUILD. {pro_users} pro users (${pro_users * 29}/mo MRR).",
    }


# ═════════════════════════════════════════════════════
#  CRON ENDPOINTS
# ═════════════════════════════════════════════════════
@app.post("/api/cron/weekly-summary")
async def weekly_summary(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    week_start = datetime.utcnow() - timedelta(days=7)
    ideas_week = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= week_start).scalar() or 0
    builds = db.query(func.count(IdeaDB.id)).filter(
        IdeaDB.final_decision.ilike("%BUILD%"), IdeaDB.date >= week_start).scalar() or 0
    avg = db.query(func.avg(IdeaDB.score)).filter(IdeaDB.date >= week_start).scalar() or 0
    return {
        "week": ideas_week, "builds": builds, "avg_score": round(avg),
        "summary": f"Week: {ideas_week} ideas, {builds} BUILD-worthy, avg score {round(avg)}"
    }


@app.post("/api/cron/generate-ideas")
async def generate_ideas(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Auto-generate trending startup ideas using Claude."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    prompt = """Generate 5 trending startup ideas based on current market opportunities.
Focus on AI, sustainability, remote work, health tech, and fintech.
Return JSON: {"ideas": ["idea 1", "idea 2", "idea 3", "idea 4", "idea 5"]}
Return ONLY valid JSON."""
    try:
        raw = await _call_claude(prompt, 500)
        data = parse_json_response(raw)
        return {"generated": data.get("ideas", []), "count": len(data.get("ideas", []))}
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {e}")


@app.post("/api/cron/ready-to-post")
async def ready_to_post(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Return ideas with content ready to post (high score + content generated)."""
    ideas = db.query(IdeaDB).filter(
        IdeaDB.score >= 70,
        IdeaDB.x_post.isnot(None),
    ).order_by(IdeaDB.score.desc()).limit(10).all()
    return {
        "ready": [{"id": i.id, "concept": i.concept, "score": i.score,
                   "tweet": i.x_post, "reddit": i.reddit} for i in ideas],
        "count": len(ideas)
    }


# ═════════════════════════════════════════════════════
#  API ACCESS (v1 key-based)
# ═════════════════════════════════════════════════════
@app.post("/api/v1/validate")
async def api_validate(request: Request, api_user: dict = Depends(_check_api_key)):
    """Programmatic API access for validated API key holders."""
    body = await request.json()
    idea_text = (body.get("idea") or body.get("raw_idea") or "").strip()
    if not idea_text:
        raise HTTPException(400, "idea field required")
    # Simplified sync analysis for API users
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "AI backend not configured")
    research, sentiment = await asyncio.gather(
        research_with_perplexity(idea_text),
        scan_with_grok(idea_text),
    )
    analysis = await analyze_with_claude(idea_text, research, sentiment)
    business = await model_with_gpt(idea_text, research, sentiment)
    idea_id = str(uuid.uuid4())[:8]
    share_token = secrets.token_urlsafe(12)
    score = calculate_score(analysis)
    result = combine_results(idea_text, analysis, research, sentiment, business,
                             idea_id, share_token, score)
    db = SessionLocal()
    try:
        db.add(IdeaDB(
            id=idea_id, raw_idea=idea_text,
            concept=analysis.get("concept", ""),
            target_user=analysis.get("target_user", ""),
            core_pain=analysis.get("core_pain", ""),
            value_promise=analysis.get("value_promise", ""),
            g1=analysis.get("gate1", {}).get("question", ""),
            g1r=f"{analysis.get('gate1', {}).get('answer', '')} — {analysis.get('gate1', {}).get('reasoning', '')}",
            g2=analysis.get("gate2", {}).get("question", ""),
            g2r=f"{analysis.get('gate2', {}).get('answer', '')} — {analysis.get('gate2', {}).get('reasoning', '')}",
            g3=analysis.get("gate3", {}).get("question", ""),
            g3r=f"{analysis.get('gate3', {}).get('answer', '')} — {analysis.get('gate3', {}).get('reasoning', '')}",
            reddit=analysis.get("reddit_post", ""),
            x_post=analysis.get("x_post", ""),
            offer=analysis.get("offer", ""),
            price=analysis.get("price", ""),
            cta=analysis.get("cta", ""),
            final_decision=analysis.get("final_decision", "MAYBE"),
            score=score, ai_response=result,
            is_public=True, share_token=share_token,
            category=analysis.get("category", "Other"),
            regional_scores=analysis.get("regional_scores"),
            timing_analysis=analysis.get("timing_analysis"),
            moat_analysis=analysis.get("moat_analysis"),
            perplexity_research=research, grok_sentiment=sentiment, gpt_business=business,
        ))
        db.commit()
    finally:
        db.close()
    return result


# ═════════════════════════════════════════════════════
#  BRAINSTORMING (ludo.ai inspired)
# ═════════════════════════════════════════════════════
@app.get("/api/brainstorm")
async def brainstorm(
    seed: str = Query(..., description="A topic, problem, or industry to brainstorm around"),
    style: str = Query("diverse", description="diverse, adjacent, disruptive"),
    db: Session = Depends(get_db),
):
    """Generate a set of related startup ideas from a seed concept."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "AI backend not configured")
    style_desc = {
        "diverse": "a variety of different approaches across multiple business models",
        "adjacent": "ideas adjacent to the seed that share the same customer or problem",
        "disruptive": "bold, contrarian takes that flip the existing market on its head",
    }.get(style, "diverse set of ideas")
    prompt = f"""You are a startup idea generator. Generate 6 startup ideas based on this seed.
Generate {style_desc}.

SEED: {seed}

Return ONLY this JSON (no markdown):
{{
  "theme": "1-sentence description of the opportunity space",
  "ideas": [
    {{
      "title": "Short catchy name",
      "tagline": "One-line description (max 15 words)",
      "target": "Who it's for",
      "pain": "Pain it solves",
      "model": "How it makes money",
      "difficulty": "Easy / Medium / Hard to build",
      "score_estimate": 75
    }}
  ],
  "market_signals": ["signal 1", "signal 2", "signal 3"],
  "best_opportunity": "Which idea seems strongest and why (1-2 sentences)"
}}"""
    try:
        raw = await _call_claude(prompt, 2000)
        data = parse_json_response(raw)
        return {"seed": seed, "style": style, **data}
    except Exception as e:
        raise HTTPException(500, f"Brainstorm failed: {e}")


# ═════════════════════════════════════════════════════
#  MARKET INSIGHT
# ═════════════════════════════════════════════════════
@app.get("/api/market-insight")
async def market_insight(
    category: str = Query(..., description="Category to analyze (e.g. SaaS, Marketplace, AI Tool)"),
    db: Session = Depends(get_db),
):
    """Get market intelligence for a category from existing validated ideas."""
    ideas = db.query(IdeaDB).filter(
        IdeaDB.category.ilike(f"%{category}%"), IdeaDB.score > 0
    ).order_by(IdeaDB.score.desc()).limit(50).all()

    total = len(ideas)
    if not total:
        return {"category": category, "total_ideas": 0, "message": "No validated ideas in this category yet"}

    avg_score = round(sum(i.score for i in ideas) / total)
    builds = sum(1 for i in ideas if i.final_decision and "BUILD" in i.final_decision.upper())
    top_ideas = [{"concept": i.concept, "score": i.score, "verdict": i.final_decision}
                 for i in ideas[:5]]

    # Regional demand aggregation
    region_totals: dict = {}
    region_counts: dict = {}
    for idea in ideas:
        regions = idea.regional_scores or []
        if isinstance(regions, list):
            for r in regions:
                name = r.get("region", "")
                demand = r.get("demand", 0)
                if name:
                    region_totals[name] = region_totals.get(name, 0) + demand
                    region_counts[name] = region_counts.get(name, 0) + 1
    regional_avg = [
        {"region": r, "avg_demand": round(region_totals[r] / region_counts[r])}
        for r in region_totals
    ]
    regional_avg.sort(key=lambda x: x["avg_demand"], reverse=True)

    return {
        "category": category,
        "total_ideas": total,
        "avg_score": avg_score,
        "build_rate": round(builds / total * 100),
        "top_ideas": top_ideas,
        "regional_demand": regional_avg,
        "insight": f"{category} has {total} validated ideas with avg score {avg_score}. {builds} ({round(builds/total*100)}%) are BUILD-worthy.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
