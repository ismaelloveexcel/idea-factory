"""
Idea Factory v4.0 — Multi-AI Idea Validator
Personal tool. Type an idea → 4 AIs research & score it.

Pipeline:
  Step 1 (parallel): Perplexity (web search) + Grok (X sentiment)
  Step 2 (parallel): Claude (deep analysis) + GPT-4o (business model)
  Step 3: Combine → Score → Save

STACK: FastAPI + SQLite + Anthropic + OpenAI + Perplexity + Grok
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
from typing import Optional

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Query, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Boolean, Text, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from kill_rules import apply_kill_rules
from scoring import calculate_deterministic_score
from decision_engine import compute_final_decision

load_dotenv()


# ─── CONFIG ───────────────────────────────────────────
_DEFAULT_DB_DIR = "/app/data" if os.path.isdir("/app") else "."
os.makedirs(_DEFAULT_DB_DIR, exist_ok=True)
_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "idea_factory.db")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DB_PATH}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-me-in-production")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Phase 11: Admin security — fail on default secret in production
_ENV_MODE = os.getenv("ENV", os.getenv("RAILWAY_ENVIRONMENT", "dev")).lower()
if _ENV_MODE != "dev" and ADMIN_SECRET == "change-me-in-production":
    raise RuntimeError(
        "ADMIN_SECRET must be changed from default in production. "
        "Set ADMIN_SECRET env var to a secure value."
    )

# AI API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")

# SSE heartbeat interval (seconds)
SSE_HEARTBEAT_INTERVAL = 12

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Phase 10: SQLite WAL mode for better concurrency
if "sqlite" in DATABASE_URL:
    with engine.connect() as _conn:
        _conn.execute(text("PRAGMA journal_mode=WAL"))
        _conn.commit()

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


Base.metadata.create_all(bind=engine)

# Safe migration: add new columns to existing DBs
_MIGRATE = [("perplexity_research", "TEXT"), ("grok_sentiment", "TEXT"), ("gpt_business", "TEXT")]
with engine.connect() as _conn:
    for _col, _type in _MIGRATE:
        try:
            _conn.execute(text(f"ALTER TABLE ideas ADD COLUMN {_col} {_type}"))
            _conn.commit()
        except Exception:
            pass


# ─── PYDANTIC MODELS ─────────────────────────────────
class OperatorConstraints(BaseModel):
    available_hours: int | float
    skills: list[str] = []
    audience_size: int | float = 0
    channels: list[str] = []
    cash_available: int | float = 0
    reachable_people: list[str] = []

    @field_validator("reachable_people")
    @classmethod
    def reachable_people_not_empty(cls, v):
        if not v:
            raise ValueError("reachable_people must not be empty")
        return v

    @field_validator("channels")
    @classmethod
    def channels_not_empty(cls, v):
        if not v:
            raise ValueError("channels must not be empty")
        return v

    @field_validator("available_hours")
    @classmethod
    def available_hours_positive(cls, v):
        if v < 1:
            raise ValueError("available_hours must be at least 1")
        return v


class IdeaInput(BaseModel):
    idea: str
    mode: str = "validate"  # validate, trendy, wild
    constraints: OperatorConstraints

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


# ─── SSE HELPER ───────────────────────────────────────
def sse(event_type: str, data: dict) -> str:
    data["type"] = event_type
    return f"data: {json.dumps(data)}\n\n"


# ─── JSON PARSER ─────────────────────────────────────
def parse_json_response(raw: str) -> dict:
    """Parse JSON from AI response, stripping markdown fences and retrying."""
    clean = raw.strip()
    # Step 1: strip markdown fences
    if clean.startswith("```"):
        lines = clean.split("\n")
        if len(lines) >= 2:
            # Remove first line (```json or ```) and last line (```)
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            clean = "\n".join(lines[start:end]).strip()
        else:
            clean = clean.lstrip("`").strip()

    # Step 2: try json.loads
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Step 3: try to extract JSON object from the text
    match = re.search(r'\{[\s\S]*\}', clean)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Step 4: fallback minimal structure — DO NOT silently fail
    raise ValueError(f"Failed to parse AI response as JSON. Raw (first 500 chars): {raw[:500]}")


async def _parse_with_retry(raw: str, prompt_context: str = "") -> dict:
    """Try to parse JSON; if fails, retry with a strict prompt to Claude."""
    try:
        return parse_json_response(raw)
    except ValueError:
        # Retry with strict prompt
        if ANTHROPIC_API_KEY:
            retry_prompt = (
                "The following text was supposed to be valid JSON but failed to parse. "
                "Extract the JSON object and return ONLY valid JSON, nothing else:\n\n"
                f"{raw[:3000]}"
            )
            try:
                retry_raw = await _call_claude(retry_prompt, 3000)
                return parse_json_response(retry_raw)
            except Exception:
                pass

        # Final fallback: minimal structure
        return {
            "concept": "Parse error — manual review needed",
            "target_user": "Unknown",
            "core_pain": "Unknown",
            "value_promise": "Unknown",
            "category": "Other",
            "summary": "AI response could not be parsed. Please retry.",
            "gate1": {"question": "Can you build a basic version in 7 days?", "answer": "NO", "reasoning": "Parse failed", "evidence": ""},
            "gate2": {"question": "Will people pay $10+ on day one?", "answer": "NO", "reasoning": "Parse failed", "evidence": ""},
            "gate3": {"question": "Is the pain bad enough people will switch now?", "answer": "NO", "reasoning": "Parse failed", "evidence": ""},
            "pain_score": 0, "market_score": 0, "execution_score": 0,
            "distribution_score": 0, "feasibility_score": 0, "build_time_hours": 0,
            "regional_scores": [], "timing_analysis": {}, "moat_analysis": {},
            "next_steps": [], "reddit_post": "", "x_post": "",
            "offer": "", "price": "", "cta": "",
            "kill_reason": "AI response parse failure",
            "one_line_pitch": "",
        }


# ═════════════════════════════════════════════════════
#  AI CLIENTS
# ═════════════════════════════════════════════════════

async def _call_openai_api(base_url: str, api_key: str, model: str,
                            prompt: str, max_tokens: int = 2000) -> str:
    """Generic OpenAI-compatible API caller with timeout and retry."""
    timeout = httpx.Timeout(45.0)
    last_err = None
    for attempt in range(2):  # 1 initial + 1 retry
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
            last_err = e
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            raise
    raise last_err  # type: ignore[misc]


async def _call_claude(prompt: str, max_tokens: int = 3000) -> str:
    """Call Claude via Anthropic SDK (async) with timeout and retry."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    client = anthropic.AsyncAnthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=httpx.Timeout(45.0),
    )
    last_err = None
    for attempt in range(2):  # 1 initial + 1 retry
        try:
            msg = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            return msg.content[0].text.strip()
        except Exception as e:
            last_err = e
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            raise
    raise last_err  # type: ignore[misc]


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
                               sentiment: Optional[dict],
                               constraints: Optional[dict] = None) -> dict:
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

    constraints_block = ""
    if constraints:
        constraints_block = f"""
OPERATOR CONSTRAINTS:
- Available hours: {constraints.get('available_hours', 'unknown')}
- Skills: {json.dumps(constraints.get('skills', []))}
- Audience size: {constraints.get('audience_size', 'unknown')}
- Channels: {json.dumps(constraints.get('channels', []))}
- Cash available: {constraints.get('cash_available', 'unknown')}
- Reachable people: {json.dumps(constraints.get('reachable_people', []))}
"""

    prompt = f"""You are a startup validation expert. Analyze this idea using ALL the research data below.
Use simple, clear language anyone can understand. No jargon.

IMPORTANT: You are providing DATA and SCORES only. Do NOT make a final decision — that is computed separately.

IDEA: {idea}
{research_block}{sentiment_block}{constraints_block}

Return this EXACT JSON (no markdown, no backticks):
{{
  "concept": "What this is in one sentence (max 12 words)",
  "target_user": "Who exactly needs this — be specific",
  "core_pain": "The #1 problem this solves, in plain English",
  "value_promise": "What the user gets, in one sentence",
  "category": "SaaS, Marketplace, Tool, Service, Content, Hardware, Community, API, Plugin, or Other",
  "summary": "2-3 sentences explaining your analysis. Plain English.",
  "gate1": {{
    "question": "Can you build a basic version in 7 days?",
    "answer": "YES or NO",
    "reasoning": "Why, in 1-2 sentences",
    "evidence": "Specific evidence supporting this answer (links, data points, examples)"
  }},
  "gate2": {{
    "question": "Will people pay $10+ on day one?",
    "answer": "YES or NO",
    "reasoning": "Why, in 1-2 sentences",
    "evidence": "Specific evidence supporting this answer (links, data points, examples)"
  }},
  "gate3": {{
    "question": "Is the pain bad enough people will switch now?",
    "answer": "YES or NO",
    "reasoning": "Why, in 1-2 sentences",
    "evidence": "Specific evidence supporting this answer (links, data points, examples)"
  }},
  "pain_score": 72,
  "market_score": 65,
  "execution_score": 80,
  "distribution_score": 60,
  "feasibility_score": 70,
  "build_time_hours": 40,
  "who_needs_this": "Describe 2-3 types of people who need this most",
  "why_now": "What makes this the right time to build this",
  "competitors_analysis": "Brief analysis of competition (use research data if available)",
  "regional_scores": [
    {{"region": "North America", "demand": 85, "reasoning": "Why"}},
    {{"region": "Europe", "demand": 60, "reasoning": "Why"}},
    {{"region": "Asia-Pacific", "demand": 40, "reasoning": "Why"}}
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
  "one_line_pitch": "A catchy 1-line pitch for sharing"
}}

SCORING GUIDELINES:
- pain_score: How severe is the problem? (0-100)
- market_score: How big is the addressable market? (0-100)
- execution_score: How easy is it to build and launch? (0-100)
- distribution_score: How easy is it to reach customers? (0-100)
- feasibility_score: Given constraints and skills, how feasible? (0-100)
- build_time_hours: Realistic hours to build an MVP

Return ONLY valid JSON. Do NOT include a final_decision field."""
    raw = await _call_claude(prompt, 3500)
    return await _parse_with_retry(raw, "claude_analysis")


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
# Scoring is now handled by scoring.py (calculate_deterministic_score)
# Evidence enforcement is handled inline before scoring


def enforce_evidence(analysis: dict) -> dict:
    """Phase 4: If evidence is missing for a gate, downgrade to NO."""
    for gate_key in ("gate1", "gate2", "gate3"):
        gate = analysis.get(gate_key, {})
        evidence = (gate.get("evidence") or "").strip()
        if not evidence:
            gate["answer"] = "NO"
            gate["reasoning"] = ((gate.get("reasoning") or "") + " [Downgraded: no evidence provided]").strip()
            gate["evidence"] = ""
            analysis[gate_key] = gate
    return analysis


# ─── RESULT COMBINER ─────────────────────────────────
def combine_results(idea_text, analysis, research, sentiment, business,
                    idea_id, share_token, score, verdict, kill_reason=""):
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
        "verdict": verdict,
        "score": score,
        "summary": analysis.get("summary", ""),
        "category": analysis.get("category", "Other"),
        "scores": {
            "pain": analysis.get("pain_score", 0),
            "market": analysis.get("market_score", 0),
            "execution": analysis.get("execution_score", 0),
            "distribution": analysis.get("distribution_score", 0),
            "feasibility": analysis.get("feasibility_score", 0),
        },
        "gates": {
            "build_fast": analysis.get("gate1", {}),
            "will_pay": analysis.get("gate2", {}),
            "urgent_pain": analysis.get("gate3", {}),
        },
        "build_time_hours": analysis.get("build_time_hours", 0),
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
        "kill_reason": kill_reason,
    }


# ═════════════════════════════════════════════════════
#  APP
# ═════════════════════════════════════════════════════
app = FastAPI(title="Idea Factory", version="4.0.0",
              description="Multi-AI idea validation — personal tool")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[BASE_URL, "http://localhost:3000", "http://localhost:8000"],
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
async def analyze_idea(request: Request):
    """Multi-AI analysis streamed via Server-Sent Events."""
    body = await request.json()
    idea_text = body.get("idea", "").strip()
    mode = body.get("mode", "validate").strip().lower()
    if mode not in ("validate", "trendy", "wild"):
        mode = "validate"
    if not idea_text:
        raise HTTPException(400, "Tell me your idea — even a rough sentence works")

    # Phase 1: Validate constraints
    constraints_raw = body.get("constraints")
    if not constraints_raw or not isinstance(constraints_raw, dict):
        raise HTTPException(400, "constraints object is required")

    try:
        constraints_model = OperatorConstraints(**constraints_raw)
    except Exception as e:
        raise HTTPException(400, f"Invalid constraints: {e}")

    constraints = constraints_model.model_dump()

    async def stream():
        original_idea = idea_text
        heartbeat_interval = SSE_HEARTBEAT_INTERVAL
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()

        async def maybe_heartbeat():
            nonlocal last_heartbeat
            now = loop.time()
            if now - last_heartbeat >= heartbeat_interval:
                last_heartbeat = now
                return sse("heartbeat", {})
            return ""

        try:
            # ── Check disconnect ──────────────────────
            if await request.is_disconnected():
                return

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

            hb = await maybe_heartbeat()
            if hb:
                yield hb

            if await request.is_disconnected():
                return

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
                analyze_with_claude(working_idea, research, sentiment, constraints),
                model_with_gpt(working_idea, research, sentiment),
            )

            hb = await maybe_heartbeat()
            if hb:
                yield hb

            if await request.is_disconnected():
                return

            yield sse("step", {"ai": "claude", "status": "done",
                               "summary": "Analysis complete"})
            if business:
                yield sse("step", {"ai": "gpt", "status": "done",
                                   "summary": f"Year 1 potential: {business.get('year1_potential', 'calculated')}"})
            else:
                yield sse("step", {"ai": "gpt", "status": "skipped",
                                   "summary": "No API key — skipped"})

            # ── Phase 4: Enforce evidence ─────────────────
            analysis = enforce_evidence(analysis)

            # ── Phase 2: Apply kill rules (PRE-SCORING) ───
            kill_result = apply_kill_rules(analysis, constraints, research)

            # ── Phase 3: Deterministic scoring ────────────
            score = calculate_deterministic_score(analysis)

            # ── Phase 5: Final decision engine ────────────
            verdict = compute_final_decision(score, kill_result)
            kill_reason = kill_result["reason"] if kill_result else ""

            # ── Step 3: Combine & Save ───────────────────
            idea_id = str(uuid.uuid4())[:8]
            share_token = secrets.token_urlsafe(12)
            result = combine_results(working_idea, analysis, research, sentiment,
                                     business, idea_id, share_token, score,
                                     verdict, kill_reason)
            result["mode"] = mode
            result["constraints"] = constraints
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
                    final_decision=verdict,
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
                                      "Connection": "keep-alive",
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
    return {"validated": s.validated if s else 0, "built": s.built if s else 0,
            "killed": s.killed if s else 0, "week": s.week if s else 0,
            "total_ideas": total, "avg_score": round(avg), "top_score": top}


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
#  REMOVED: PDF, Premium Report, Landing Page, Twitter Thread
#  (Phase 6: Keep system focused on idea → decision)
# ═════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════
#  ADMIN
# ═════════════════════════════════════════════════════
@app.get("/api/admin/dashboard")
async def admin_dashboard(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    avg = db.query(func.avg(IdeaDB.score)).scalar() or 0
    builds = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%BUILD%")).scalar() or 0
    top = db.query(IdeaDB).order_by(IdeaDB.score.desc()).limit(5).all()
    return {"total_ideas": total, "avg_score": round(avg), "builds": builds,
            "top_ideas": [{"id": i.id, "concept": i.concept, "score": i.score} for i in top]}


@app.post("/api/cron/auto-rank")
async def auto_rank(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    ideas = db.query(IdeaDB).filter(IdeaDB.score > 0).all()
    updated = 0
    for i in ideas:
        # Use deterministic decision engine — no LLM decisions
        new = compute_final_decision(i.score, None)
        if i.final_decision != new:
            i.final_decision = new
            updated += 1
    db.commit()
    return {"checked": len(ideas), "updated": updated}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
