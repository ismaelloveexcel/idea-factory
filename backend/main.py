"""
Idea Factory Backend
FastAPI server for idea validation and app generation
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import os
import anthropic

# ═══════════════════════════════════════════════════════
# DATABASE SETUP
# ═══════════════════════════════════════════════════════
SQLALCHEMY_DATABASE_URL = "sqlite:///./idea_factory.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
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
    pain_quotes = Column(String)
    pain_freq = Column(String)
    pain_buyers = Column(String)
    
    # Raw idea
    raw_idea = Column(String)
    
    # Analysis outputs
    concept = Column(String)
    target_user = Column(String)
    core_pain = Column(String)
    value_promise = Column(String)
    
    # Gate scores
    g1 = Column(String)  # Gate 1 question
    g1r = Column(String) # Gate 1 result
    g2 = Column(String)
    g2r = Column(String)
    g3 = Column(String)
    g3r = Column(String)
    
    # Pre-sell content
    reddit = Column(String)
    x_post = Column(String)
    offer = Column(String)
    price = Column(String)
    cta = Column(String)
    
    # Signal tracking
    pay = Column(Integer, default=0)
    rep = Column(Integer, default=0)
    clk = Column(Integer, default=0)
    countdown_start = Column(DateTime, nullable=True)
    
    # Final decision
    final_decision = Column(String, nullable=True)  # KILL, TEST FIRST, BUILD
    repo_url = Column(String, nullable=True)
    
    # Full AI response (for debugging)
    ai_response = Column(JSON, nullable=True)

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

class SignalUpdate(BaseModel):
    idea_id: str
    signal_type: str  # 'pay', 'rep', 'clk'

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
app = FastAPI(title="Idea Factory API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════
# CLAUDE API INTEGRATION
# ═══════════════════════════════════════════════════════
def get_claude_client():
    """Get Claude API client - requires ANTHROPIC_API_KEY env var"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)

def analyze_idea_with_claude(idea_text: str, pain: PainInput) -> dict:
    """Send idea to Claude for analysis"""
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
  "target_user": "Specific user persona (e.g., 'Solo founders validating SaaS ideas')",
  "core_pain": "The #1 pain this solves in 15 words max",
  "value_promise": "What they get in 15 words max",
  "gate1": {{
    "question": "Can you build v1 in <7 days?",
    "answer": "YES or NO",
    "reasoning": "Brief explanation"
  }},
  "gate2": {{
    "question": "Can you charge >$10 on day 1?",
    "answer": "YES or NO",
    "reasoning": "Brief explanation"
  }},
  "gate3": {{
    "question": "Is pain severe enough they'll switch NOW?",
    "answer": "YES or NO",
    "reasoning": "Brief explanation"
  }},
  "reddit_post": "Reddit post (250 chars max) to test demand - conversational, pain-focused",
  "x_post": "X/Twitter post (280 chars max) with hook + offer",
  "offer": "Clear 1-sentence offer",
  "price": "Suggested price point",
  "cta": "Call-to-action (e.g., 'DM me', 'Reply interested')",
  "final_decision": "KILL or TEST FIRST or BUILD (based on gates)"
}}

Return ONLY valid JSON, no other text."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    response_text = message.content[0].text.strip()
    
    # Clean potential markdown formatting
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])
    
    import json
    return json.loads(response_text)

# ═══════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════
@app.get("/")
def read_root():
    return {"status": "Idea Factory API running", "version": "1.0.0"}

@app.post("/api/analyze", response_model=IdeaResponse)
async def analyze_idea(idea_input: IdeaInput, db: Session = Depends(get_db)):
    """Analyze idea and return validation results"""
    
    # Call Claude API
    analysis = analyze_idea_with_claude(idea_input.raw_idea, idea_input.pain)
    
    # Generate unique ID
    import uuid
    idea_id = str(uuid.uuid4())[:8]
    
    # Save to database
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
        ai_response=analysis
    )
    
    db.add(db_idea)
    db.commit()
    db.refresh(db_idea)
    
    # Update stats
    stats = db.query(StatsDB).first()
    if not stats:
        stats = StatsDB(validated=1)
        db.add(stats)
    else:
        stats.validated += 1
    db.commit()
    
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
        final_decision=db_idea.final_decision
    )

@app.post("/api/signal")
async def log_signal(signal: SignalUpdate, db: Session = Depends(get_db)):
    """Log a demand signal (payment/reply/click)"""
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
    if not stats:
        return {"validated": 0, "built": 0, "killed": 0, "week": 0}
    return {
        "validated": stats.validated,
        "built": stats.built,
        "killed": stats.killed,
        "week": stats.week
    }

@app.post("/api/decision/{idea_id}")
async def finalize_decision(idea_id: str, decision: str, db: Session = Depends(get_db)):
    """Finalize decision (KILL/BUILD) and update stats"""
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    
    idea.final_decision = decision
    
    stats = db.query(StatsDB).first()
    if decision == "KILL":
        stats.killed += 1
    elif decision == "BUILD":
        stats.built += 1
    
    db.commit()
    return {"status": "success", "decision": decision}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
