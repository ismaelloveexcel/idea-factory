"""
Idea Factory Backend v2.0
FastAPI server with monetization, viral growth, and auto-content features
"""
from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import Optional, List
import os
import json
import uuid
import secrets
import io

import anthropic

# ═══════════════════════════════════════════════════════
# DATABASE SETUP
# ═══════════════════════════════════════════════════════
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./idea_factory.db")
# Handle Railway postgres URL format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ═══════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════
class IdeaDB(Base):
    __tablename__ = "ideas"

    id = Column(String, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)

    # Pain validation
    pain_who = Column(String)
    pain_quotes = Column(Text)
    pain_freq = Column(String)
    pain_buyers = Column(String)

    # Raw idea
    raw_idea = Column(Text)

    # Analysis outputs
    concept = Column(String)
    target_user = Column(String)
    core_pain = Column(String)
    value_promise = Column(String)

    # Gate scores
    g1 = Column(String)   # Gate 1 question
    g1r = Column(String)  # Gate 1 result
    g2 = Column(String)
    g2r = Column(String)
    g3 = Column(String)
    g3r = Column(String)

    # Pre-sell content
    reddit = Column(Text)
    x_post = Column(Text)
    offer = Column(String)
    price = Column(String)
    cta = Column(String)

    # Signal tracking
    pay = Column(Integer, default=0)
    rep = Column(Integer, default=0)
    clk = Column(Integer, default=0)
    countdown_start = Column(DateTime, nullable=True)

    # Final decision
    final_decision = Column(String, nullable=True)
    repo_url = Column(String, nullable=True)

    # Full AI response
    ai_response = Column(JSON, nullable=True)

    # === NEW v2 FIELDS ===
    email = Column(String, nullable=True)               # Submitter email
    is_public = Column(Boolean, default=True)            # Show on public pages
    score = Column(Integer, default=0)                   # 0-100 validation score
    share_token = Column(String, unique=True, index=True, nullable=True)  # Shareable link
    twitter_thread = Column(Text, nullable=True)         # Generated thread
    view_count = Column(Integer, default=0)              # Public page views
    category = Column(String, nullable=True)             # Auto-categorized


class EmailCaptureDB(Base):
    __tablename__ = "email_captures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, index=True)
    idea_id = Column(String, nullable=True)
    source = Column(String, default="validation")  # validation, graveyard, leaderboard, newsletter
    captured_at = Column(DateTime, default=datetime.utcnow)
    tags = Column(String, nullable=True)  # comma-separated tags


class StatsDB(Base):
    __tablename__ = "stats"

    id = Column(Integer, primary_key=True, index=True)
    validated = Column(Integer, default=0)
    built = Column(Integer, default=0)
    killed = Column(Integer, default=0)
    week = Column(Integer, default=0)
    week_start = Column(DateTime, default=datetime.utcnow)


# Create tables
Base.metadata.create_all(bind=engine)

# ═══════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════
class PainInput(BaseModel):
    pain_who: str
    pain_quotes: str
    pain_freq: str
    pain_buyers: str

class IdeaInput(BaseModel):
    raw_idea: str
    pain: PainInput
    email: Optional[str] = None  # Optional email capture

class IdeaResponse(BaseModel):
    id: str
    concept: str
    target_user: str
    core_pain: str
    value_promise: str
    g1: str
    g1r: str
    g2: str
    g2r: str
    g3: str
    g3r: str
    reddit: str
    x_post: str
    offer: str
    price: str
    cta: str
    final_decision: str
    score: int = 0
    share_url: str = ""
    category: Optional[str] = None

class SignalUpdate(BaseModel):
    idea_id: str
    signal_type: str

class EmailCaptureInput(BaseModel):
    email: str
    source: str = "validation"
    idea_id: Optional[str] = None
    tags: Optional[str] = None

# ═══════════════════════════════════════════════════════
# DEPENDENCY
# ═══════════════════════════════════════════════════════
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ═══════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════
app = FastAPI(
    title="Idea Factory API",
    version="2.0.0",
    description="AI-powered idea validation with monetization & viral growth"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════
# CLAUDE API INTEGRATION
# ═══════════════════════════════════════════════════════
def get_claude_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)


def analyze_idea_with_claude(idea_text: str, pain: PainInput) -> dict:
    """Send idea to Claude for analysis with enhanced scoring"""
    client = get_claude_client()

    prompt = f"""You are an idea validation expert. Analyze this startup idea using the pain-first framework.

PAIN CONTEXT:
- Who has this pain: {pain.pain_who}
- Direct quotes: {pain.pain_quotes}
- Frequency: {pain.pain_freq}
- Willing to pay: {pain.pain_buyers}

IDEA:
{idea_text}

Provide analysis in this EXACT JSON format (no markdown, no backticks):
{{
  "concept": "One-sentence concept in 10 words max",
  "target_user": "Specific user persona",
  "core_pain": "The #1 pain this solves in 15 words max",
  "value_promise": "What they get in 15 words max",
  "category": "One of: SaaS, Marketplace, Tool, Service, Content, Hardware, Community, API, Plugin, Other",
  "gate1": {{
    "question": "Can you build v1 in <7 days?",
    "answer": "YES or NO",
    "reasoning": "Brief explanation",
    "confidence": 85
  }},
  "gate2": {{
    "question": "Can you charge >$10 on day 1?",
    "answer": "YES or NO",
    "reasoning": "Brief explanation",
    "confidence": 80
  }},
  "gate3": {{
    "question": "Is pain severe enough they'll switch NOW?",
    "answer": "YES or NO",
    "reasoning": "Brief explanation",
    "confidence": 75
  }},
  "pain_score": 72,
  "market_score": 65,
  "execution_score": 80,
  "reddit_post": "Reddit post (250 chars max) to test demand - conversational, pain-focused",
  "x_post": "X/Twitter post (280 chars max) with hook + offer",
  "offer": "Clear 1-sentence offer",
  "price": "Suggested price point",
  "cta": "Call-to-action",
  "final_decision": "KILL or TEST FIRST or BUILD (based on gates)",
  "kill_reason": "If KILL, one-sentence reason. If not KILL, empty string.",
  "one_line_pitch": "A punchy 1-line pitch for this idea for social sharing"
}}

Return ONLY valid JSON, no other text."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])

    return json.loads(response_text)


def generate_twitter_thread(idea: IdeaDB) -> str:
    """Generate a viral Twitter thread from a validated idea"""
    client = get_claude_client()

    prompt = f"""Generate a viral 5-tweet Twitter/X thread about this validated startup idea.

IDEA: {idea.concept}
TARGET: {idea.target_user}
PAIN: {idea.core_pain}
VALUE: {idea.value_promise}
DECISION: {idea.final_decision}
OFFER: {idea.offer}
PRICE: {idea.price}

Format as a numbered thread (1/5, 2/5, etc). Each tweet max 280 chars.
- Tweet 1: Hook with a bold claim or question about the pain
- Tweet 2: The pain in vivid detail (use the quotes if available)
- Tweet 3: The solution/idea
- Tweet 4: Why this works (validation data)
- Tweet 5: CTA with the offer

Return ONLY the thread text, no other commentary."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def calculate_score(analysis: dict) -> int:
    """Calculate a 0-100 validation score from analysis results"""
    score = 0

    # Gate results (30 points each for gates 1 & 2, 20 for gate 3)
    if analysis.get("gate1", {}).get("answer", "").upper().startswith("YES"):
        score += 30
    if analysis.get("gate2", {}).get("answer", "").upper().startswith("YES"):
        score += 30
    if analysis.get("gate3", {}).get("answer", "").upper().startswith("YES"):
        score += 20

    # Confidence bonus (up to 20 points)
    confidences = []
    for gate_key in ["gate1", "gate2", "gate3"]:
        gate = analysis.get(gate_key, {})
        conf = gate.get("confidence", 50)
        if isinstance(conf, (int, float)):
            confidences.append(conf)
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        score += int((avg_conf / 100) * 20)

    return min(score, 100)


# ═══════════════════════════════════════════════════════
# CORE ENDPOINTS
# ═══════════════════════════════════════════════════════
@app.get("/")
def read_root():
    return {"status": "Idea Factory API running", "version": "2.0.0"}


@app.post("/api/analyze", response_model=IdeaResponse)
async def analyze_idea(idea_input: IdeaInput, db: Session = Depends(get_db)):
    """Analyze idea, score it, capture email, generate share link"""

    analysis = analyze_idea_with_claude(idea_input.raw_idea, idea_input.pain)

    idea_id = str(uuid.uuid4())[:8]
    share_token = secrets.token_urlsafe(12)
    score = calculate_score(analysis)

    db_idea = IdeaDB(
        id=idea_id,
        pain_who=idea_input.pain.pain_who,
        pain_quotes=idea_input.pain.pain_quotes,
        pain_freq=idea_input.pain.pain_freq,
        pain_buyers=idea_input.pain.pain_buyers,
        raw_idea=idea_input.raw_idea,
        concept=analysis["concept"],
        target_user=analysis["target_user"],
        core_pain=analysis["core_pain"],
        value_promise=analysis["value_promise"],
        g1=analysis["gate1"]["question"],
        g1r=f"{analysis['gate1']['answer']} — {analysis['gate1']['reasoning']}",
        g2=analysis["gate2"]["question"],
        g2r=f"{analysis['gate2']['answer']} — {analysis['gate2']['reasoning']}",
        g3=analysis["gate3"]["question"],
        g3r=f"{analysis['gate3']['answer']} — {analysis['gate3']['reasoning']}",
        reddit=analysis["reddit_post"],
        x_post=analysis["x_post"],
        offer=analysis["offer"],
        price=analysis["price"],
        cta=analysis["cta"],
        final_decision=analysis["final_decision"],
        ai_response=analysis,
        email=idea_input.email,
        is_public=True,
        score=score,
        share_token=share_token,
        category=analysis.get("category", "Other"),
    )

    db.add(db_idea)

    # Auto-capture email if provided
    if idea_input.email:
        email_record = EmailCaptureDB(
            email=idea_input.email,
            idea_id=idea_id,
            source="validation",
            tags=analysis.get("category", ""),
        )
        db.add(email_record)

    # Update stats
    stats = db.query(StatsDB).first()
    if not stats:
        stats = StatsDB(validated=1, week=1)
        db.add(stats)
    else:
        stats.validated += 1
        stats.week += 1
    db.commit()
    db.refresh(db_idea)

    base_url = os.getenv("BASE_URL", "http://localhost:8000")

    return IdeaResponse(
        id=db_idea.id,
        concept=db_idea.concept,
        target_user=db_idea.target_user,
        core_pain=db_idea.core_pain,
        value_promise=db_idea.value_promise,
        g1=db_idea.g1,
        g1r=db_idea.g1r,
        g2=db_idea.g2,
        g2r=db_idea.g2r,
        g3=db_idea.g3,
        g3r=db_idea.g3r,
        reddit=db_idea.reddit,
        x_post=db_idea.x_post,
        offer=db_idea.offer,
        price=db_idea.price,
        cta=db_idea.cta,
        final_decision=db_idea.final_decision,
        score=db_idea.score,
        share_url=f"{base_url}/public/idea/{share_token}",
        category=db_idea.category,
    )


@app.post("/api/signal")
async def log_signal(signal: SignalUpdate, db: Session = Depends(get_db)):
    """Log a demand signal"""
    idea = db.query(IdeaDB).filter(IdeaDB.id == signal.idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    if signal.signal_type == "pay":
        idea.pay += 1
    elif signal.signal_type == "rep":
        idea.rep += 1
    elif signal.signal_type == "clk":
        idea.clk += 1

    db.commit()
    return {"status": "success", "pay": idea.pay, "rep": idea.rep, "clk": idea.clk}


@app.get("/api/ideas")
async def get_ideas(db: Session = Depends(get_db)):
    """Get all ideas"""
    ideas = db.query(IdeaDB).order_by(IdeaDB.date.desc()).all()
    return ideas


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get validation stats"""
    stats = db.query(StatsDB).first()
    total_ideas = db.query(func.count(IdeaDB.id)).scalar() or 0
    total_emails = db.query(func.count(EmailCaptureDB.id)).scalar() or 0
    avg_score = db.query(func.avg(IdeaDB.score)).scalar() or 0

    if not stats:
        return {"validated": 0, "built": 0, "killed": 0, "week": 0,
                "total_ideas": total_ideas, "total_emails": total_emails, "avg_score": round(avg_score)}

    return {
        "validated": stats.validated,
        "built": stats.built,
        "killed": stats.killed,
        "week": stats.week,
        "total_ideas": total_ideas,
        "total_emails": total_emails,
        "avg_score": round(avg_score),
    }


@app.post("/api/decision/{idea_id}")
async def finalize_decision(idea_id: str, decision: str, db: Session = Depends(get_db)):
    """Finalize decision and update stats"""
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    idea.final_decision = decision

    stats = db.query(StatsDB).first()
    if stats:
        if decision == "KILL":
            stats.killed += 1
        elif decision == "BUILD":
            stats.built += 1

    db.commit()
    return {"status": "success", "decision": decision}


# ═══════════════════════════════════════════════════════
# EMAIL CAPTURE
# ═══════════════════════════════════════════════════════
@app.post("/api/email/capture")
async def capture_email(data: EmailCaptureInput, db: Session = Depends(get_db)):
    """Capture email from any source"""
    record = EmailCaptureDB(
        email=data.email,
        idea_id=data.idea_id,
        source=data.source,
        tags=data.tags,
    )
    db.add(record)
    db.commit()
    return {"status": "captured", "email": data.email}


@app.get("/api/emails")
async def get_emails(db: Session = Depends(get_db)):
    """Get all captured emails (admin)"""
    emails = db.query(EmailCaptureDB).order_by(EmailCaptureDB.captured_at.desc()).all()
    return [
        {
            "email": e.email,
            "idea_id": e.idea_id,
            "source": e.source,
            "captured_at": e.captured_at.isoformat() if e.captured_at else None,
            "tags": e.tags,
        }
        for e in emails
    ]


# ═══════════════════════════════════════════════════════
# TWITTER THREAD GENERATOR
# ═══════════════════════════════════════════════════════
@app.get("/api/idea/{idea_id}/twitter-thread")
async def get_twitter_thread(idea_id: str, db: Session = Depends(get_db)):
    """Generate or return cached Twitter thread"""
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    if not idea.twitter_thread:
        idea.twitter_thread = generate_twitter_thread(idea)
        db.commit()

    return {"idea_id": idea_id, "thread": idea.twitter_thread, "concept": idea.concept}


# ═══════════════════════════════════════════════════════
# PDF VALIDATION REPORT
# ═══════════════════════════════════════════════════════
@app.get("/api/idea/{idea_id}/pdf")
async def generate_pdf_report(idea_id: str, db: Session = Depends(get_db)):
    """Generate a professional PDF validation report"""
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    # Increment view count
    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    try:
        from fpdf import FPDF
    except ImportError:
        raise HTTPException(status_code=500, detail="PDF library not installed. Run: pip install fpdf2")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # --- Cover Page ---
    pdf.add_page()
    pdf.set_fill_color(8, 8, 8)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(200, 255, 0)
    pdf.set_font("Helvetica", "B", 32)
    pdf.ln(60)
    pdf.cell(0, 15, "IDEA FACTORY", ln=True, align="C")
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 10, "Validation Report", ln=True, align="C")
    pdf.ln(30)
    pdf.set_text_color(239, 239, 239)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 10, idea.concept or "Untitled Idea", align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, f"ID: {idea.id}  |  Score: {idea.score}/100  |  Decision: {idea.final_decision}", ln=True, align="C")
    date_str = idea.date.strftime("%B %d, %Y") if idea.date else "N/A"
    pdf.cell(0, 8, f"Generated: {date_str}", ln=True, align="C")

    # --- Executive Summary ---
    pdf.add_page()
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Executive Summary", ln=True)
    pdf.ln(4)
    pdf.set_draw_color(200, 255, 0)
    pdf.line(10, pdf.get_y(), 70, pdf.get_y())
    pdf.ln(8)

    pdf.set_font("Helvetica", "", 11)
    summary_items = [
        ("Concept", idea.concept),
        ("Target User", idea.target_user),
        ("Core Pain", idea.core_pain),
        ("Value Promise", idea.value_promise),
        ("Category", idea.category or "N/A"),
        ("Validation Score", f"{idea.score}/100"),
    ]
    for label, value in summary_items:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 8, label.upper())
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 8, str(value) if value else "N/A")
        pdf.ln(2)

    # --- Score Visualization ---
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, f"Validation Score: {idea.score}/100", ln=True)
    pdf.ln(2)

    # Score bar
    bar_width = 170
    bar_height = 12
    x_start = 20
    y_start = pdf.get_y()
    pdf.set_fill_color(230, 230, 230)
    pdf.rect(x_start, y_start, bar_width, bar_height, "F")
    score_width = (idea.score / 100) * bar_width
    if idea.score >= 70:
        pdf.set_fill_color(0, 200, 100)
    elif idea.score >= 40:
        pdf.set_fill_color(255, 200, 0)
    else:
        pdf.set_fill_color(255, 80, 80)
    pdf.rect(x_start, y_start, score_width, bar_height, "F")
    pdf.ln(bar_height + 8)

    # --- 3-Gate Evaluation ---
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "3-Gate Evaluation", ln=True)
    pdf.ln(4)
    pdf.set_draw_color(200, 255, 0)
    pdf.line(10, pdf.get_y(), 70, pdf.get_y())
    pdf.ln(8)

    gates = [
        ("Gate 1: Build in 7 Days?", idea.g1r),
        ("Gate 2: Charge $10+ Day 1?", idea.g2r),
        ("Gate 3: Pain Severe Enough?", idea.g3r),
    ]
    for gate_name, gate_result in gates:
        result_str = str(gate_result) if gate_result else "N/A"
        is_pass = result_str.upper().startswith("YES")

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, gate_name, ln=True)

        if is_pass:
            pdf.set_text_color(0, 160, 80)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(20, 7, "PASS")
        else:
            pdf.set_text_color(220, 50, 50)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(20, 7, "FAIL")

        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "", 10)
        parts = result_str.split("—", 1)
        reasoning = parts[1].strip() if len(parts) > 1 else ""
        pdf.multi_cell(0, 7, reasoning)
        pdf.ln(6)

    # --- Decision ---
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 18)
    decision = idea.final_decision or "PENDING"
    if "BUILD" in decision.upper():
        pdf.set_text_color(0, 180, 80)
    elif "KILL" in decision.upper():
        pdf.set_text_color(220, 50, 50)
    else:
        pdf.set_text_color(200, 180, 0)
    pdf.cell(0, 12, f"DECISION: {decision}", ln=True, align="C")

    # --- Pain Analysis ---
    pdf.add_page()
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Pain Analysis", ln=True)
    pdf.ln(4)
    pdf.set_draw_color(200, 255, 0)
    pdf.line(10, pdf.get_y(), 70, pdf.get_y())
    pdf.ln(8)

    pain_items = [
        ("Who Feels This Pain", idea.pain_who),
        ("Frequency", idea.pain_freq),
        ("Potential Buyers", idea.pain_buyers),
    ]
    for label, value in pain_items:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, label.upper(), ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 7, str(value) if value else "N/A")
        pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, "DIRECT PAIN QUOTES", ln=True)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 7, str(idea.pain_quotes) if idea.pain_quotes else "N/A")
    pdf.ln(8)

    # --- Pre-Sell Content ---
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, "Pre-Sell Content (Ready to Post)", ln=True)
    pdf.ln(4)
    pdf.set_draw_color(200, 255, 0)
    pdf.line(10, pdf.get_y(), 70, pdf.get_y())
    pdf.ln(8)

    content_items = [
        ("Reddit Post", idea.reddit),
        ("X / Twitter Post", idea.x_post),
        ("Offer", idea.offer),
        ("Price Point", idea.price),
        ("Call to Action", idea.cta),
    ]
    for label, value in content_items:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, label.upper(), ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 7, str(value) if value else "N/A")
        pdf.ln(4)

    # --- Signal Tracking ---
    if idea.pay or idea.rep or idea.clk:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 12, "Demand Signals", ln=True)
        pdf.ln(4)
        pdf.set_draw_color(200, 255, 0)
        pdf.line(10, pdf.get_y(), 70, pdf.get_y())
        pdf.ln(8)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, f"Payments: {idea.pay}  |  Replies: {idea.rep}  |  Clicks: {idea.clk}", ln=True)

    # --- Footer ---
    pdf.add_page()
    pdf.ln(80)
    pdf.set_text_color(150, 150, 150)
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 8, "Generated by Idea Factory — AI-Powered Idea Validation", ln=True, align="C")
    pdf.cell(0, 8, "ideafactory.dev", ln=True, align="C")

    # Output
    pdf_bytes = pdf.output()
    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)

    safe_name = (idea.concept or "idea").replace(" ", "_")[:30]
    filename = f"validation_report_{idea.id}_{safe_name}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════
# PUBLIC PAGES (SEO GOLDMINES)
# ═══════════════════════════════════════════════════════

# -- Shared HTML template parts --
def _html_head(title: str, description: str, og_image: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
{f'<meta property="og:image" content="{og_image}">' if og_image else ''}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #080808; --surface: #0f0f0f; --border: #1f1f1f;
  --text: #efefef; --text-muted: #6a6a6a; --accent: #c8ff00;
  --green: #00e87a; --red: #ff3b3b; --orange: #ff9f1c; --blue: #4ea8de;
  --font: 'Syne', sans-serif; --mono: 'JetBrains Mono', monospace;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: var(--font); min-height: 100vh; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 30px 20px; }}
h1 {{ font-size: 36px; font-weight: 800; color: var(--accent); margin-bottom: 8px; }}
.subtitle {{ font-family: var(--mono); font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.2em; margin-bottom: 30px; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 22px; margin-bottom: 16px; transition: border-color 0.2s; }}
.card:hover {{ border-color: var(--accent); }}
.badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-family: var(--mono); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }}
.badge-kill {{ background: rgba(255,59,59,0.15); color: var(--red); border: 1px solid rgba(255,59,59,0.3); }}
.badge-build {{ background: rgba(0,232,122,0.15); color: var(--green); border: 1px solid rgba(0,232,122,0.3); }}
.badge-test {{ background: rgba(200,255,0,0.15); color: var(--accent); border: 1px solid rgba(200,255,0,0.3); }}
.score-bar {{ height: 6px; background: var(--border); border-radius: 3px; margin: 8px 0; overflow: hidden; }}
.score-fill {{ height: 100%; border-radius: 3px; transition: width 0.5s; }}
.meta {{ font-family: var(--mono); font-size: 11px; color: var(--text-muted); }}
.cta-bar {{ background: var(--surface); border: 1px solid var(--accent); border-radius: 14px; padding: 20px; text-align: center; margin: 30px 0; }}
.cta-bar h3 {{ color: var(--accent); margin-bottom: 8px; }}
.email-form {{ display: flex; gap: 10px; justify-content: center; margin-top: 12px; max-width: 500px; margin-left: auto; margin-right: auto; }}
.email-form input {{ flex: 1; padding: 10px 14px; background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 8px; font-family: var(--mono); font-size: 12px; outline: none; }}
.email-form input:focus {{ border-color: var(--accent); }}
.btn {{ background: var(--accent); color: var(--bg); border: none; padding: 10px 20px; border-radius: 8px; font-family: var(--mono); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em; cursor: pointer; white-space: nowrap; }}
.btn:hover {{ opacity: 0.9; }}
.share-btn {{ background: transparent; border: 1px solid var(--border); color: var(--text-muted); padding: 6px 12px; border-radius: 6px; font-family: var(--mono); font-size: 10px; cursor: pointer; text-decoration: none; display: inline-block; margin: 4px 4px 4px 0; }}
.share-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
.stats-row {{ display: flex; gap: 16px; margin-bottom: 30px; flex-wrap: wrap; }}
.stat-box {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; flex: 1; min-width: 120px; text-align: center; }}
.stat-num {{ font-size: 28px; font-weight: 800; color: var(--accent); }}
.stat-label {{ font-family: var(--mono); font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; margin-top: 4px; }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.filter-bar {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }}
.filter-btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--text-muted); padding: 6px 14px; border-radius: 20px; font-family: var(--mono); font-size: 11px; cursor: pointer; }}
.filter-btn.active {{ border-color: var(--accent); color: var(--accent); background: rgba(200,255,0,0.08); }}
.tombstone {{ font-size: 28px; margin-right: 12px; }}
.nav {{ display: flex; gap: 20px; margin-bottom: 30px; padding-bottom: 16px; border-bottom: 1px solid var(--border); align-items: center; flex-wrap: wrap; }}
.nav a {{ font-family: var(--mono); font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-muted); }}
.nav a:hover, .nav a.active {{ color: var(--accent); text-decoration: none; }}
.nav-brand {{ font-weight: 800; font-size: 18px; color: var(--accent) !important; margin-right: auto; }}
</style>
</head>"""


def _nav_html(active: str = "") -> str:
    return f"""<nav class="nav">
  <a href="/public/graveyard" class="nav-brand">IDEA FACTORY</a>
  <a href="/public/graveyard" class="{'active' if active == 'graveyard' else ''}">Graveyard</a>
  <a href="/public/leaderboard" class="{'active' if active == 'leaderboard' else ''}">Leaderboard</a>
</nav>"""


@app.get("/public/graveyard", response_class=HTMLResponse)
async def public_graveyard(
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """Public Idea Graveyard — SEO-optimized killed ideas page"""
    per_page = 20
    query = db.query(IdeaDB).filter(
        IdeaDB.is_public == True,
        IdeaDB.final_decision.ilike("%KILL%"),
    )
    if category:
        query = query.filter(IdeaDB.category == category)

    total = query.count()
    ideas = query.order_by(IdeaDB.date.desc()).offset((page - 1) * per_page).limit(per_page).all()

    categories = db.query(IdeaDB.category, func.count(IdeaDB.id)).filter(
        IdeaDB.is_public == True,
        IdeaDB.final_decision.ilike("%KILL%"),
    ).group_by(IdeaDB.category).all()

    killed_count = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%KILL%")).scalar() or 0

    idea_cards = ""
    for idea in ideas:
        kill_reason = ""
        if idea.ai_response and isinstance(idea.ai_response, dict):
            kill_reason = idea.ai_response.get("kill_reason", "")
        if not kill_reason:
            failed_gates = []
            if idea.g1r and not str(idea.g1r).upper().startswith("YES"):
                failed_gates.append("Can't build in 7 days")
            if idea.g2r and not str(idea.g2r).upper().startswith("YES"):
                failed_gates.append("Can't charge $10+ day 1")
            if idea.g3r and not str(idea.g3r).upper().startswith("YES"):
                failed_gates.append("Pain not severe enough")
            kill_reason = ". ".join(failed_gates) if failed_gates else "Failed validation gates"

        date_str = idea.date.strftime("%b %d, %Y") if idea.date else ""
        share_url = f"/public/idea/{idea.share_token}" if idea.share_token else "#"

        idea_cards += f"""
        <div class="card">
          <div style="display:flex; align-items:start; gap:12px;">
            <span class="tombstone">💀</span>
            <div style="flex:1;">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                <a href="{share_url}" style="font-size:17px; font-weight:700; color:var(--text);">{idea.concept or 'Untitled'}</a>
                <span class="badge badge-kill">KILLED</span>
              </div>
              <div style="font-size:13px; color:var(--text-muted); margin:6px 0; line-height:1.5;">
                {kill_reason}
              </div>
              <div class="score-bar"><div class="score-fill" style="width:{idea.score}%; background:var(--red);"></div></div>
              <div class="meta" style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-top:6px;">
                <span>Score: {idea.score}/100 · {idea.category or 'Other'} · {date_str}</span>
                <span>
                  <a class="share-btn" href="https://twitter.com/intent/tweet?text=This%20idea%20got%20killed%20by%20AI%20validation%3A%20{idea.concept or ''}%20%E2%80%94%20Score%3A%20{idea.score}%2F100&url=" target="_blank">Share on X</a>
                </span>
              </div>
            </div>
          </div>
        </div>"""

    cat_filters = '<button class="filter-btn active" onclick="location.href=\'/public/graveyard\'">All</button>'
    for cat_name, cat_count in categories:
        if cat_name:
            is_active = "active" if category == cat_name else ""
            cat_filters += f'<button class="filter-btn {is_active}" onclick="location.href=\'/public/graveyard?category={cat_name}\'">{cat_name} ({cat_count})</button>'

    # Pagination
    pagination = ""
    total_pages = max(1, (total + per_page - 1) // per_page)
    if total_pages > 1:
        pagination = '<div style="display:flex; gap:8px; justify-content:center; margin:30px 0;">'
        if page > 1:
            pagination += f'<a class="btn" href="/public/graveyard?page={page-1}{"&category="+category if category else ""}">← Prev</a>'
        pagination += f'<span class="meta" style="padding:10px;">Page {page} of {total_pages}</span>'
        if page < total_pages:
            pagination += f'<a class="btn" href="/public/graveyard?page={page+1}{"&category="+category if category else ""}">Next →</a>'
        pagination += '</div>'

    html = f"""{_html_head(
        "Idea Graveyard — Startup Ideas That Failed AI Validation",
        f"{killed_count} startup ideas killed by AI validation. Learn from others' mistakes before you build."
    )}
<body>
<div class="container">
  {_nav_html("graveyard")}

  <h1>💀 Idea Graveyard</h1>
  <p class="subtitle">{killed_count} ideas killed by AI validation — so you don't have to waste time on them</p>

  <div class="stats-row">
    <div class="stat-box"><div class="stat-num">{killed_count}</div><div class="stat-label">Ideas Killed</div></div>
    <div class="stat-box"><div class="stat-num">{len(categories)}</div><div class="stat-label">Categories</div></div>
    <div class="stat-box"><div class="stat-num">{total}</div><div class="stat-label">{"In " + category if category else "Total"}</div></div>
  </div>

  <div class="filter-bar">{cat_filters}</div>

  {idea_cards if idea_cards else '<div class="card" style="text-align:center;padding:40px;"><p style="color:var(--text-muted);">No killed ideas yet. Submit your first idea to get started!</p></div>'}

  {pagination}

  <div class="cta-bar">
    <h3>Got an idea? Find out if it's worth building.</h3>
    <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">Get AI validation in 30 seconds — before you waste months building the wrong thing.</p>
    <div class="email-form">
      <input type="email" id="graveyardEmail" placeholder="your@email.com">
      <button class="btn" onclick="captureEmail('graveyardEmail','graveyard')">Get Early Access</button>
    </div>
    <div id="graveyardMsg" style="font-family:var(--mono); font-size:11px; color:var(--green); margin-top:8px;"></div>
  </div>
</div>

<script>
async function captureEmail(inputId, source) {{
  const email = document.getElementById(inputId).value.trim();
  if (!email || !email.includes('@')) {{ alert('Please enter a valid email'); return; }}
  try {{
    await fetch('/api/email/capture', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ email, source }})
    }});
    document.getElementById(inputId).value = '';
    document.getElementById(source + 'Msg').textContent = '✓ You\\'re on the list!';
  }} catch(e) {{ alert('Something went wrong. Try again.'); }}
}}
</script>
</body></html>"""

    return HTMLResponse(content=html)


@app.get("/public/leaderboard", response_class=HTMLResponse)
async def public_leaderboard(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Public Idea Leaderboard — highest-scoring validated ideas"""
    query = db.query(IdeaDB).filter(IdeaDB.is_public == True, IdeaDB.score > 0)
    if category:
        query = query.filter(IdeaDB.category == category)

    ideas = query.order_by(IdeaDB.score.desc()).limit(50).all()
    total = db.query(func.count(IdeaDB.id)).filter(IdeaDB.is_public == True).scalar() or 0
    avg_score = db.query(func.avg(IdeaDB.score)).filter(IdeaDB.is_public == True).scalar() or 0
    build_count = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%BUILD%")).scalar() or 0

    categories = db.query(IdeaDB.category, func.count(IdeaDB.id)).filter(
        IdeaDB.is_public == True, IdeaDB.score > 0
    ).group_by(IdeaDB.category).all()

    idea_rows = ""
    for rank, idea in enumerate(ideas, 1):
        decision = idea.final_decision or "PENDING"
        if "BUILD" in decision.upper():
            badge_class = "badge-build"
        elif "KILL" in decision.upper():
            badge_class = "badge-kill"
        else:
            badge_class = "badge-test"

        if idea.score >= 70:
            score_color = "var(--green)"
        elif idea.score >= 40:
            score_color = "var(--orange)"
        else:
            score_color = "var(--red)"

        share_url = f"/public/idea/{idea.share_token}" if idea.share_token else "#"
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"

        idea_rows += f"""
        <div class="card" style="display:flex; align-items:center; gap:16px;">
          <div style="font-size:{22 if rank <= 3 else 14}px; font-weight:800; min-width:40px; text-align:center; color:{'var(--accent)' if rank <= 3 else 'var(--text-muted)'};">{medal}</div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
              <a href="{share_url}" style="font-size:16px; font-weight:700; color:var(--text);">{idea.concept or 'Untitled'}</a>
              <span class="badge {badge_class}">{decision}</span>
            </div>
            <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">{idea.target_user or ''} · {idea.category or 'Other'}</div>
            <div class="score-bar"><div class="score-fill" style="width:{idea.score}%; background:{score_color};"></div></div>
          </div>
          <div style="text-align:center; min-width:60px;">
            <div style="font-size:24px; font-weight:800; color:{score_color};">{idea.score}</div>
            <div class="meta">/100</div>
          </div>
        </div>"""

    cat_filters = '<button class="filter-btn active" onclick="location.href=\'/public/leaderboard\'">All</button>'
    for cat_name, cat_count in categories:
        if cat_name:
            is_active = "active" if category == cat_name else ""
            cat_filters += f'<button class="filter-btn {is_active}" onclick="location.href=\'/public/leaderboard?category={cat_name}\'">{cat_name} ({cat_count})</button>'

    html = f"""{_html_head(
        "Idea Leaderboard — Top AI-Validated Startup Ideas",
        f"Top {len(ideas)} startup ideas ranked by AI validation score. See what's worth building."
    )}
<body>
<div class="container">
  {_nav_html("leaderboard")}

  <h1>🏆 Idea Leaderboard</h1>
  <p class="subtitle">Top validated ideas ranked by AI score — updated in real time</p>

  <div class="stats-row">
    <div class="stat-box"><div class="stat-num">{total}</div><div class="stat-label">Ideas Validated</div></div>
    <div class="stat-box"><div class="stat-num">{round(avg_score)}</div><div class="stat-label">Avg Score</div></div>
    <div class="stat-box"><div class="stat-num">{build_count}</div><div class="stat-label">Worth Building</div></div>
  </div>

  <div class="filter-bar">{cat_filters}</div>

  {idea_rows if idea_rows else '<div class="card" style="text-align:center;padding:40px;"><p style="color:var(--text-muted);">No ideas validated yet. Be the first!</p></div>'}

  <div class="cta-bar">
    <h3>Think your idea can top the leaderboard?</h3>
    <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">Submit your idea for AI validation and see how it ranks.</p>
    <div class="email-form">
      <input type="email" id="leaderboardEmail" placeholder="your@email.com">
      <button class="btn" onclick="captureEmail('leaderboardEmail','leaderboard')">Get Early Access</button>
    </div>
    <div id="leaderboardMsg" style="font-family:var(--mono); font-size:11px; color:var(--green); margin-top:8px;"></div>
  </div>
</div>

<script>
async function captureEmail(inputId, source) {{
  const email = document.getElementById(inputId).value.trim();
  if (!email || !email.includes('@')) {{ alert('Please enter a valid email'); return; }}
  try {{
    await fetch('/api/email/capture', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ email, source }})
    }});
    document.getElementById(inputId).value = '';
    document.getElementById(source + 'Msg').textContent = '✓ You\\'re on the list!';
  }} catch(e) {{ alert('Something went wrong. Try again.'); }}
}}
</script>
</body></html>"""

    return HTMLResponse(content=html)


@app.get("/public/idea/{share_token}", response_class=HTMLResponse)
async def public_idea_page(share_token: str, db: Session = Depends(get_db)):
    """Individual shared idea page with OG tags for social sharing"""
    idea = db.query(IdeaDB).filter(IdeaDB.share_token == share_token).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    # Track views
    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    decision = idea.final_decision or "PENDING"
    if "BUILD" in decision.upper():
        badge_class, decision_color, decision_emoji = "badge-build", "var(--green)", "🚀"
    elif "KILL" in decision.upper():
        badge_class, decision_color, decision_emoji = "badge-kill", "var(--red)", "💀"
    else:
        badge_class, decision_color, decision_emoji = "badge-test", "var(--accent)", "🧪"

    if idea.score >= 70:
        score_color = "var(--green)"
    elif idea.score >= 40:
        score_color = "var(--orange)"
    else:
        score_color = "var(--red)"

    gates_html = ""
    for gate_num, (q, r) in enumerate([(idea.g1, idea.g1r), (idea.g2, idea.g2r), (idea.g3, idea.g3r)], 1):
        result_str = str(r) if r else "N/A"
        is_pass = result_str.upper().startswith("YES")
        parts = result_str.split("—", 1)
        reasoning = parts[1].strip() if len(parts) > 1 else ""
        gates_html += f"""
        <div style="background:var(--bg); border:1px solid {'var(--green)' if is_pass else 'var(--red)'}; border-radius:10px; padding:16px; text-align:center;">
          <div class="meta">GATE {gate_num}</div>
          <div style="font-size:22px; font-weight:800; color:{'var(--green)' if is_pass else 'var(--red)'}; margin:6px 0;">{'PASS' if is_pass else 'FAIL'}</div>
          <div style="font-size:12px; color:var(--text-muted);">{q or ''}</div>
          <div style="font-size:11px; color:var(--text-muted); margin-top:6px;">{reasoning}</div>
        </div>"""

    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    share_full_url = f"{base_url}/public/idea/{share_token}"
    tweet_text = f"I just validated a startup idea with AI and got a {idea.score}/100 score: {idea.concept}"

    date_str = idea.date.strftime("%B %d, %Y") if idea.date else ""

    html = f"""{_html_head(
        f"{idea.concept or 'Idea'} — Validation Score: {idea.score}/100",
        f"AI-validated startup idea: {idea.value_promise or idea.concept}. Score: {idea.score}/100. Decision: {decision}."
    )}
<body>
<div class="container">
  {_nav_html("")}

  <div style="text-align:center; margin-bottom:30px;">
    <div style="font-size:48px; margin-bottom:8px;">{decision_emoji}</div>
    <h1 style="font-size:28px; color:var(--text);">{idea.concept or 'Untitled'}</h1>
    <div style="margin:12px 0;"><span class="badge {badge_class}" style="font-size:13px; padding:6px 16px;">{decision}</span></div>
    <div class="meta">{date_str} · {idea.category or 'Other'} · {idea.view_count or 0} views</div>
  </div>

  <!-- Score -->
  <div class="card" style="text-align:center;">
    <div style="font-size:56px; font-weight:800; color:{score_color};">{idea.score}</div>
    <div class="meta" style="margin-bottom:8px;">VALIDATION SCORE / 100</div>
    <div class="score-bar" style="max-width:300px; margin:0 auto; height:10px;"><div class="score-fill" style="width:{idea.score}%; background:{score_color}; height:100%;"></div></div>
  </div>

  <!-- Analysis -->
  <div class="card">
    <div class="meta" style="margin-bottom:12px;">ANALYSIS</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
      <div><div class="meta">TARGET USER</div><div style="margin-top:4px;">{idea.target_user or 'N/A'}</div></div>
      <div><div class="meta">CORE PAIN</div><div style="margin-top:4px;">{idea.core_pain or 'N/A'}</div></div>
      <div><div class="meta">VALUE PROMISE</div><div style="margin-top:4px;">{idea.value_promise or 'N/A'}</div></div>
      <div><div class="meta">PRICE POINT</div><div style="margin-top:4px;">{idea.price or 'N/A'}</div></div>
    </div>
  </div>

  <!-- Gates -->
  <div class="card">
    <div class="meta" style="margin-bottom:12px;">3-GATE EVALUATION</div>
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px;">
      {gates_html}
    </div>
  </div>

  <!-- Pre-sell Content -->
  <div class="card">
    <div class="meta" style="margin-bottom:12px;">PRE-SELL CONTENT</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
      <div style="background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:14px;">
        <div class="meta">REDDIT POST</div>
        <div style="font-family:var(--mono); font-size:12px; margin-top:6px; line-height:1.5;">{idea.reddit or 'N/A'}</div>
      </div>
      <div style="background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:14px;">
        <div class="meta">X / TWITTER</div>
        <div style="font-family:var(--mono); font-size:12px; margin-top:6px; line-height:1.5;">{idea.x_post or 'N/A'}</div>
      </div>
    </div>
  </div>

  <!-- Share + Download -->
  <div class="card" style="text-align:center;">
    <div class="meta" style="margin-bottom:12px;">SHARE THIS VALIDATION</div>
    <div style="display:flex; gap:8px; justify-content:center; flex-wrap:wrap;">
      <a class="share-btn" href="https://twitter.com/intent/tweet?text={tweet_text}&url={share_full_url}" target="_blank">Share on X</a>
      <a class="share-btn" href="https://www.linkedin.com/shareArticle?mini=true&url={share_full_url}&title={idea.concept or ''}" target="_blank">Share on LinkedIn</a>
      <a class="share-btn" href="https://www.reddit.com/submit?url={share_full_url}&title=AI+Validation+Score:+{idea.score}/100+-+{idea.concept or ''}" target="_blank">Share on Reddit</a>
      <a class="share-btn" onclick="navigator.clipboard.writeText('{share_full_url}');this.textContent='Copied!';setTimeout(()=>this.textContent='Copy Link',2000);" style="cursor:pointer;">Copy Link</a>
      <a class="share-btn" href="/api/idea/{idea.id}/pdf" target="_blank" style="border-color:var(--accent); color:var(--accent);">Download PDF Report</a>
    </div>
  </div>

  <div class="cta-bar">
    <h3>Validate your own idea in 30 seconds</h3>
    <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">Get an AI validation score before you waste months building.</p>
    <div class="email-form">
      <input type="email" id="ideaEmail" placeholder="your@email.com">
      <button class="btn" onclick="captureEmail('ideaEmail','shared_idea')">Get Early Access</button>
    </div>
    <div id="shared_ideaMsg" style="font-family:var(--mono); font-size:11px; color:var(--green); margin-top:8px;"></div>
  </div>
</div>

<script>
async function captureEmail(inputId, source) {{
  const email = document.getElementById(inputId).value.trim();
  if (!email || !email.includes('@')) {{ alert('Please enter a valid email'); return; }}
  try {{
    await fetch('/api/email/capture', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ email, source, idea_id: '{idea.id}' }})
    }});
    document.getElementById(inputId).value = '';
    document.getElementById(source + 'Msg').textContent = '✓ You\\'re on the list!';
  }} catch(e) {{ alert('Something went wrong. Try again.'); }}
}}
</script>
</body></html>"""

    return HTMLResponse(content=html)


# ═══════════════════════════════════════════════════════
# MARKET TRENDS (aggregated data endpoint)
# ═══════════════════════════════════════════════════════
@app.get("/api/trends")
async def get_trends(db: Session = Depends(get_db)):
    """Aggregated trend data from all validations"""
    # Category distribution
    categories = db.query(
        IdeaDB.category, func.count(IdeaDB.id), func.avg(IdeaDB.score)
    ).group_by(IdeaDB.category).all()

    # Decision distribution
    decisions = db.query(
        IdeaDB.final_decision, func.count(IdeaDB.id)
    ).group_by(IdeaDB.final_decision).all()

    # Score distribution
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    high_score = db.query(func.count(IdeaDB.id)).filter(IdeaDB.score >= 70).scalar() or 0
    mid_score = db.query(func.count(IdeaDB.id)).filter(IdeaDB.score >= 40, IdeaDB.score < 70).scalar() or 0
    low_score = db.query(func.count(IdeaDB.id)).filter(IdeaDB.score < 40).scalar() or 0

    return {
        "categories": [{"name": c[0], "count": c[1], "avg_score": round(c[2] or 0)} for c in categories if c[0]],
        "decisions": [{"decision": d[0], "count": d[1]} for d in decisions if d[0]],
        "score_distribution": {"high": high_score, "mid": mid_score, "low": low_score},
        "total_ideas": total,
    }


# ═══════════════════════════════════════════════════════
# VALIDATION-AS-A-SERVICE API
# ═══════════════════════════════════════════════════════
@app.post("/api/v1/validate")
async def validate_api(idea_input: IdeaInput, db: Session = Depends(get_db)):
    """Public API endpoint for validation-as-a-service.
    Same as /api/analyze but designed for external integrations."""
    return await analyze_idea(idea_input, db)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
