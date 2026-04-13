"""
Idea Factory Backend v3.0
FastAPI server with FULL monetization, Stripe payments, premium features,
automation, and operator dashboard.

STACK: FastAPI + SQLite + Stripe + Claude API
"""
from fastapi import FastAPI, HTTPException, Depends, Query, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
import os
import json
import uuid
import secrets
import io
import hashlib
import hmac
import time

import anthropic
from dotenv import load_dotenv
load_dotenv()

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./idea_factory.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-me-in-production")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Pricing
FREE_VALIDATIONS_PER_MONTH = 3
PRICE_SINGLE_REPORT = 900          # $9 in cents
PRICE_PRO_MONTHLY = 2900           # $29/month
PRICE_API_MONTHLY = 4900           # $49/month

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ═══════════════════════════════════════════════════════
# DATABASE MODELS
# ═══════════════════════════════════════════════════════
class IdeaDB(Base):
    __tablename__ = "ideas"
    id = Column(String, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    pain_who = Column(String)
    pain_quotes = Column(Text)
    pain_freq = Column(String)
    pain_buyers = Column(String)
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
    countdown_start = Column(DateTime, nullable=True)
    final_decision = Column(String, nullable=True)
    repo_url = Column(String, nullable=True)
    ai_response = Column(JSON, nullable=True)
    email = Column(String, nullable=True)
    is_public = Column(Boolean, default=True)
    score = Column(Integer, default=0)
    share_token = Column(String, unique=True, index=True, nullable=True)
    twitter_thread = Column(Text, nullable=True)
    view_count = Column(Integer, default=0)
    category = Column(String, nullable=True)
    # v3 fields
    user_id = Column(String, nullable=True, index=True)
    is_premium_report = Column(Boolean, default=False)
    blueprint = Column(JSON, nullable=True)
    landing_page_html = Column(Text, nullable=True)
    revenue_sim = Column(JSON, nullable=True)
    mvp_plan = Column(JSON, nullable=True)
    distribution_plan = Column(JSON, nullable=True)
    # v4 market intelligence
    regional_scores = Column(JSON, nullable=True)
    timing_analysis = Column(JSON, nullable=True)
    moat_analysis = Column(JSON, nullable=True)


class EmailCaptureDB(Base):
    __tablename__ = "email_captures"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, index=True)
    idea_id = Column(String, nullable=True)
    source = Column(String, default="validation")
    captured_at = Column(DateTime, default=datetime.utcnow)
    tags = Column(String, nullable=True)


class StatsDB(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True, index=True)
    validated = Column(Integer, default=0)
    built = Column(Integer, default=0)
    killed = Column(Integer, default=0)
    week = Column(Integer, default=0)
    week_start = Column(DateTime, default=datetime.utcnow)


class UserDB(Base):
    """Tracks users by session token (cookie-based, no passwords)"""
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=True, index=True)
    session_token = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_pro = Column(Boolean, default=False)
    pro_expires = Column(DateTime, nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    total_validations = Column(Integer, default=0)
    validations_this_month = Column(Integer, default=0)
    month_reset = Column(DateTime, default=datetime.utcnow)
    referral_code = Column(String, unique=True, nullable=True, index=True)
    referral_credits = Column(Integer, default=0)
    referred_by = Column(String, nullable=True)


class PurchaseDB(Base):
    """Tracks all purchases"""
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    idea_id = Column(String, nullable=True)
    stripe_session_id = Column(String, nullable=True, unique=True)
    stripe_payment_intent = Column(String, nullable=True)
    product_type = Column(String)  # single_report, pro_monthly, api_monthly
    amount_cents = Column(Integer)
    status = Column(String, default="pending")  # pending, completed, failed, refunded
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class APIKeyDB(Base):
    """API keys for validation-as-a-service"""
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    key_hash = Column(String, unique=True, index=True)
    key_prefix = Column(String)  # first 8 chars for display
    name = Column(String, default="Default")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    calls_this_month = Column(Integer, default=0)
    calls_limit = Column(Integer, default=100)
    is_active = Column(Boolean, default=True)


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
    email: Optional[str] = None

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
    regional_scores: Optional[list] = None
    timing_analysis: Optional[dict] = None
    moat_analysis: Optional[dict] = None

class SignalUpdate(BaseModel):
    idea_id: str
    signal_type: str

class EmailCaptureInput(BaseModel):
    email: str
    source: str = "validation"
    idea_id: Optional[str] = None
    tags: Optional[str] = None

class CheckoutRequest(BaseModel):
    product_type: str  # single_report, pro_monthly, api_monthly
    idea_id: Optional[str] = None


# ═══════════════════════════════════════════════════════
# DEPENDENCIES
# ═══════════════════════════════════════════════════════
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_user(request: Request, db: Session) -> UserDB:
    """Get user from session cookie or create new one"""
    session_token = request.cookies.get("if_session")
    user = None
    if session_token:
        user = db.query(UserDB).filter(UserDB.session_token == session_token).first()
    if not user:
        session_token = secrets.token_urlsafe(32)
        user = UserDB(session_token=session_token)
        db.add(user)
        db.commit()
        db.refresh(user)
    # Reset monthly counter if needed
    now = datetime.utcnow()
    if user.month_reset and user.month_reset.month != now.month:
        user.validations_this_month = 0
        user.month_reset = now
        db.commit()
    return user


def check_admin(x_admin_secret: str = Header(None)):
    """Verify admin secret for protected endpoints"""
    if not x_admin_secret or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    return True


# ═══════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════
app = FastAPI(
    title="Idea Factory API",
    version="3.0.0",
    description="AI-powered idea validation with monetization"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[BASE_URL, "http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════
# CLAUDE API
# ═══════════════════════════════════════════════════════
def get_claude_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)


def call_claude(prompt: str, max_tokens: int = 2000) -> str:
    client = get_claude_client()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def parse_json_response(text: str) -> dict:
    """Safely parse JSON from Claude response"""
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1])
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[\s\S]*\}', clean)
        if match:
            return json.loads(match.group())
        raise HTTPException(status_code=500, detail="Failed to parse AI response")


def analyze_idea_with_claude(idea_text: str, pain: PainInput) -> dict:
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
  "regional_scores": [
    {{"region": "North America", "demand": 85, "reasoning": "Why this region", "subreddits": ["r/example"], "post_time": "9am EST"}},
    {{"region": "Europe", "demand": 60, "reasoning": "Why this region", "subreddits": ["r/example"], "post_time": "10am CET"}},
    {{"region": "Asia-Pacific", "demand": 40, "reasoning": "Why this region", "subreddits": [], "post_time": "10am JST"}}
  ],
  "timing_analysis": {{
    "readiness": "NOW or 3_MONTHS or 6_MONTHS",
    "reasoning": "Why now or why wait",
    "trend_direction": "RISING or STABLE or DECLINING",
    "trigger_event": "What recent event makes this timely (or empty)"
  }},
  "moat_analysis": {{
    "defensibility": "LOW or MEDIUM or HIGH",
    "copy_time_days": 30,
    "moat_type": "Speed, Network, Data, Brand, or None",
    "reasoning": "Why this moat level"
  }},
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

    return parse_json_response(call_claude(prompt, 3000))


def calculate_score(analysis: dict) -> int:
    score = 0
    if analysis.get("gate1", {}).get("answer", "").upper().startswith("YES"):
        score += 25
    if analysis.get("gate2", {}).get("answer", "").upper().startswith("YES"):
        score += 25
    if analysis.get("gate3", {}).get("answer", "").upper().startswith("YES"):
        score += 15
    confidences = []
    for gate_key in ["gate1", "gate2", "gate3"]:
        gate = analysis.get(gate_key, {})
        conf = gate.get("confidence", 50)
        if isinstance(conf, (int, float)):
            confidences.append(conf)
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        score += int((avg_conf / 100) * 15)
    # Regional demand bonus (up to 10 points)
    regions = analysis.get("regional_scores", [])
    if regions:
        top_demand = max((r.get("demand", 0) for r in regions), default=0)
        score += int((top_demand / 100) * 10)
    # Timing bonus (up to 5 points)
    timing = analysis.get("timing_analysis", {})
    if timing.get("readiness") == "NOW":
        score += 5
    elif timing.get("readiness") == "3_MONTHS":
        score += 2
    # Moat bonus (up to 5 points)
    moat = analysis.get("moat_analysis", {})
    if moat.get("defensibility") == "HIGH":
        score += 5
    elif moat.get("defensibility") == "MEDIUM":
        score += 3
    return min(score, 100)


def generate_twitter_thread(idea: IdeaDB) -> str:
    prompt = f"""Generate a viral 5-tweet Twitter/X thread about this validated startup idea.

IDEA: {idea.concept}
TARGET: {idea.target_user}
PAIN: {idea.core_pain}
VALUE: {idea.value_promise}
DECISION: {idea.final_decision}
OFFER: {idea.offer}
PRICE: {idea.price}

Format as a numbered thread (1/5, 2/5, etc). Each tweet max 280 chars.
Return ONLY the thread text, no other commentary."""

    return call_claude(prompt, 1500)


# ═══════════════════════════════════════════════════════
# STRIPE INTEGRATION
# ═══════════════════════════════════════════════════════
def get_stripe():
    """Lazy import and configure stripe"""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


@app.post("/api/checkout/create-session")
async def create_checkout_session(
    req: CheckoutRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session"""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payments are being set up. Please try again shortly.")

    stripe = get_stripe()
    user = get_or_create_user(request, db)

    success_url = f"{BASE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{BASE_URL}/checkout/cancel"

    if req.product_type == "single_report":
        if not req.idea_id:
            raise HTTPException(status_code=400, detail="idea_id required for single report")
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Premium Validation Report",
                        "description": "Full AI blueprint, landing page, revenue simulation, and distribution plan",
                    },
                    "unit_amount": PRICE_SINGLE_REPORT,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": user.id,
                "idea_id": req.idea_id,
                "product_type": "single_report",
            },
        )
    elif req.product_type == "pro_monthly":
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Idea Factory Pro",
                        "description": "Unlimited validations + all premium features",
                    },
                    "unit_amount": PRICE_PRO_MONTHLY,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": user.id,
                "product_type": "pro_monthly",
            },
        )
    elif req.product_type == "api_monthly":
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Idea Factory API Access",
                        "description": "100 validations/month via API",
                    },
                    "unit_amount": PRICE_API_MONTHLY,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": user.id,
                "product_type": "api_monthly",
            },
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid product_type")

    # Record purchase
    purchase = PurchaseDB(
        user_id=user.id,
        idea_id=req.idea_id,
        stripe_session_id=session.id,
        product_type=req.product_type,
        amount_cents=PRICE_SINGLE_REPORT if req.product_type == "single_report"
            else PRICE_PRO_MONTHLY if req.product_type == "pro_monthly"
            else PRICE_API_MONTHLY,
        status="pending",
    )
    db.add(purchase)
    db.commit()

    response = JSONResponse(content={"checkout_url": session.url, "session_id": session.id})
    response.set_cookie("if_session", user.session_token, httponly=True, samesite="lax", max_age=86400*365)
    return response


@app.post("/api/checkout/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhooks — idempotent and retry-safe"""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    stripe = get_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except Exception as e:
        if "SignatureVerification" in type(e).__name__:
            raise HTTPException(status_code=400, detail="Invalid signature")
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session["id"]
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        product_type = metadata.get("product_type")
        idea_id = metadata.get("idea_id")

        # Idempotency: check if already processed
        purchase = db.query(PurchaseDB).filter(
            PurchaseDB.stripe_session_id == session_id
        ).first()

        if purchase and purchase.status == "completed":
            return {"status": "already_processed"}

        if not purchase:
            purchase = PurchaseDB(
                user_id=user_id,
                idea_id=idea_id,
                stripe_session_id=session_id,
                stripe_payment_intent=session.get("payment_intent"),
                product_type=product_type,
                amount_cents=session.get("amount_total", 0),
                status="completed",
                completed_at=datetime.utcnow(),
            )
            db.add(purchase)
        else:
            purchase.status = "completed"
            purchase.completed_at = datetime.utcnow()
            purchase.stripe_payment_intent = session.get("payment_intent")

        # Update user status
        if user_id:
            user = db.query(UserDB).filter(UserDB.id == user_id).first()
            if user:
                if product_type == "pro_monthly":
                    user.is_pro = True
                    user.pro_expires = datetime.utcnow() + timedelta(days=35)
                elif product_type == "api_monthly":
                    user.is_pro = True
                    user.pro_expires = datetime.utcnow() + timedelta(days=35)
                    # Create API key
                    raw_key = f"if_live_{secrets.token_urlsafe(32)}"
                    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
                    api_key = APIKeyDB(
                        user_id=user.id,
                        key_hash=key_hash,
                        key_prefix=raw_key[:12],
                        calls_limit=100,
                    )
                    db.add(api_key)
                    # Store raw key temporarily so success page can show it
                    purchase.stripe_payment_intent = (purchase.stripe_payment_intent or "") + f"|APIKEY:{raw_key}"
                elif product_type == "single_report" and idea_id:
                    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
                    if idea:
                        idea.is_premium_report = True

        db.commit()

    elif event["type"] == "payment_intent.payment_failed":
        pi = event["data"]["object"]
        # Find purchase by payment intent
        purchase = db.query(PurchaseDB).filter(
            PurchaseDB.stripe_payment_intent == pi["id"]
        ).first()
        if purchase:
            purchase.status = "failed"
            db.commit()

    return {"status": "ok"}


@app.get("/checkout/success", response_class=HTMLResponse)
async def checkout_success(session_id: str = "", db: Session = Depends(get_db)):
    """Checkout success page"""
    purchase_info = ""
    auto_refresh = ""
    if session_id:
        purchase = db.query(PurchaseDB).filter(
            PurchaseDB.stripe_session_id == session_id
        ).first()
        if purchase and purchase.status == "completed":
            if purchase.product_type == "single_report":
                purchase_info = f'<p style="color:#00e87a;font-size:18px;font-weight:700;">✓ Premium report unlocked!</p><p style="color:#777;margin:12px 0;">Your full build blueprint, revenue simulation, and distribution plan are ready.</p><a class="btn" href="/">View Your Report →</a>'
            elif purchase.product_type == "pro_monthly":
                purchase_info = '<p style="color:#00e87a;font-size:18px;font-weight:700;">✓ Pro subscription active!</p><p style="color:#777;margin:12px 0;">Unlimited validations + all premium features are now unlocked.</p><a class="btn" href="/">Start Validating →</a>'
            elif purchase.product_type == "api_monthly":
                api_key_part = ""
                if purchase.stripe_payment_intent and "|APIKEY:" in purchase.stripe_payment_intent:
                    api_key_part = purchase.stripe_payment_intent.split("|APIKEY:")[1]
                    purchase_info = f'<p style="color:#00e87a;font-size:18px;font-weight:700;">✓ API access activated!</p><p style="font-family:monospace;background:#111;padding:12px;border-radius:8px;word-break:break-all;margin:16px 0;">Your API Key: {api_key_part}</p><p style="color:#ff3b3b;font-size:12px;">⚠ Save this key now — it won\'t be shown again.</p><a class="btn" href="/" style="margin-top:16px;">Go to Dashboard →</a>'
                else:
                    purchase_info = '<p style="color:#00e87a;font-size:18px;font-weight:700;">✓ API access activated!</p><a class="btn" href="/">Go to Dashboard →</a>'
            auto_refresh = '<meta http-equiv="refresh" content="5;url=/">'
        else:
            purchase_info = '<div style="margin:20px 0;"><div class="spinner"></div></div><p style="color:#ff9f1c;font-size:16px;">Confirming your payment...</p><p style="color:#777;font-size:13px;margin-top:8px;">This usually takes a few seconds. The page will refresh automatically.</p><a class="btn" href="/" style="margin-top:20px;">Go to Dashboard</a>'
            auto_refresh = f'<meta http-equiv="refresh" content="3;url=/checkout/success?session_id={session_id}">'
    else:
        purchase_info = '<p style="color:#00e87a;font-size:18px;font-weight:700;">✓ Payment successful!</p><a class="btn" href="/">Go to Dashboard →</a>'
        auto_refresh = '<meta http-equiv="refresh" content="4;url=/">'

    return HTMLResponse(content=f"""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Payment Successful — Idea Factory</title>
{auto_refresh}
<style>
body {{ background:#080808; color:#efefef; font-family:system-ui; display:flex; justify-content:center; align-items:center; min-height:100vh; }}
.box {{ text-align:center; max-width:500px; padding:40px; }}
h1 {{ color:#c8ff00; font-size:28px; margin-bottom:16px; }}
.btn {{ display:inline-block; background:#c8ff00; color:#080808; padding:14px 28px; border-radius:8px; text-decoration:none; font-weight:700; margin-top:20px; }}
.btn:hover {{ opacity:0.9; }}
.spinner {{ width:32px; height:32px; border:3px solid #1f1f1f; border-top:3px solid #c8ff00; border-radius:50%; animation:spin 1s linear infinite; margin:0 auto; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style></head><body><div class="box">
<h1>✓ Payment Successful</h1>
{purchase_info}
</div></body></html>""")


@app.get("/checkout/cancel", response_class=HTMLResponse)
async def checkout_cancel():
    return HTMLResponse(content="""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Checkout Cancelled — Idea Factory</title>
<style>
body { background:#080808; color:#efefef; font-family:system-ui; display:flex; justify-content:center; align-items:center; min-height:100vh; }
.box { text-align:center; max-width:500px; padding:40px; }
h1 { color:#ff9f1c; font-size:28px; margin-bottom:16px; }
.btn { display:inline-block; background:#c8ff00; color:#080808; padding:14px 28px; border-radius:8px; text-decoration:none; font-weight:700; margin-top:12px; }
.btn:hover { opacity:0.9; }
.btn-outline { display:inline-block; border:1px solid #2a2a2a; color:#777; padding:12px 24px; border-radius:8px; text-decoration:none; font-size:13px; margin-top:10px; }
.btn-outline:hover { border-color:#c8ff00; color:#c8ff00; }
p { color:#777; margin:12px 0; font-size:14px; }
</style></head><body><div class="box">
<h1>No worries — nothing was charged</h1>
<p>Your idea is still saved. You can upgrade anytime to unlock premium reports.</p>
<a class="btn" href="/">← Back to Your Results</a>
<br>
<a class="btn-outline" href="/">Try a different plan</a>
<p style="font-size:11px;color:#4a4a4a;margin-top:24px;">Questions? Reach out anytime.</p>
</div></body></html>""")


# ═══════════════════════════════════════════════════════
# USER STATUS
# ═══════════════════════════════════════════════════════
@app.get("/api/user/status")
async def user_status(request: Request, db: Session = Depends(get_db)):
    """Get current user's status — free tier limits, pro status"""
    user = get_or_create_user(request, db)
    now = datetime.utcnow()
    is_pro_active = user.is_pro and user.pro_expires and user.pro_expires > now

    response = JSONResponse(content={
        "user_id": user.id,
        "is_pro": is_pro_active,
        "pro_expires": user.pro_expires.isoformat() if user.pro_expires else None,
        "validations_this_month": user.validations_this_month,
        "validations_limit": 999999 if is_pro_active else FREE_VALIDATIONS_PER_MONTH,
        "validations_remaining": 999999 if is_pro_active else max(0, FREE_VALIDATIONS_PER_MONTH - user.validations_this_month),
        "total_validations": user.total_validations,
        "referral_code": user.referral_code,
        "referral_credits": user.referral_credits or 0,
        "is_first_session": user.total_validations == 0,
    })
    response.set_cookie("if_session", user.session_token, httponly=True, samesite="lax", max_age=86400*365)
    return response


@app.post("/api/referral/apply")
async def apply_referral(request: Request, db: Session = Depends(get_db)):
    """Apply a referral code — gives the new user +1 free validation"""
    body = await request.json()
    code = body.get("code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Missing referral code")

    user = get_or_create_user(request, db)
    if user.referred_by:
        return {"status": "already_referred", "message": "You already used a referral code"}

    referrer = db.query(UserDB).filter(UserDB.referral_code == code).first()
    if not referrer or referrer.id == user.id:
        raise HTTPException(status_code=404, detail="Invalid referral code")

    user.referred_by = referrer.id
    referrer.referral_credits = (referrer.referral_credits or 0) + 1
    db.commit()

    response = JSONResponse(content={"status": "ok", "message": "Referral applied! Your friend gets +1 free validation too."})
    response.set_cookie("if_session", user.session_token, httponly=True, samesite="lax", max_age=86400*365)
    return response


# ═══════════════════════════════════════════════════════
# CORE ENDPOINTS (with usage limits)
# ═══════════════════════════════════════════════════════
@app.get("/")
async def root(request: Request):
    """Serve the main app page"""
    # Try to serve frontend/app.html
    app_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.html")
    if os.path.exists(app_path):
        with open(app_path, "r") as f:
            return HTMLResponse(content=f.read())
    return {"status": "Idea Factory API running", "version": "3.0.0"}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "3.0.0"}


@app.post("/api/analyze", response_model=IdeaResponse)
async def analyze_idea(idea_input: IdeaInput, request: Request, db: Session = Depends(get_db)):
    """Analyze idea with free tier limits"""
    user = get_or_create_user(request, db)
    now = datetime.utcnow()
    is_pro = user.is_pro and user.pro_expires and user.pro_expires > now

    # Check free tier limit (referral credits give extra validations)
    effective_limit = FREE_VALIDATIONS_PER_MONTH + (user.referral_credits or 0)
    if not is_pro and user.validations_this_month >= effective_limit:
        raise HTTPException(
            status_code=402,
            detail=json.dumps({
                "error": "free_limit_reached",
                "message": f"Free tier limit reached ({effective_limit}/month). Upgrade to Pro for unlimited validations.",
                "validations_used": user.validations_this_month,
                "limit": effective_limit,
                "upgrade_url": f"{BASE_URL}/api/checkout/create-session",
            })
        )

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
        user_id=user.id,
        regional_scores=analysis.get("regional_scores"),
        timing_analysis=analysis.get("timing_analysis"),
        moat_analysis=analysis.get("moat_analysis"),
    )
    db.add(db_idea)

    if idea_input.email:
        if not user.email:
            user.email = idea_input.email
        email_record = EmailCaptureDB(
            email=idea_input.email,
            idea_id=idea_id,
            source="validation",
            tags=analysis.get("category", ""),
        )
        db.add(email_record)

    # Update usage
    user.validations_this_month += 1
    user.total_validations += 1

    # Generate referral code if user doesn't have one
    if not user.referral_code:
        user.referral_code = secrets.token_urlsafe(6)

    stats = db.query(StatsDB).first()
    if not stats:
        stats = StatsDB(validated=1, week=1)
        db.add(stats)
    else:
        stats.validated += 1
        stats.week += 1

    db.commit()
    db.refresh(db_idea)

    # Determine if user can see premium intel (pro or first validation gets teaser)
    is_first_validation = user.total_validations == 1

    response_data = IdeaResponse(
        id=db_idea.id,
        concept=db_idea.concept,
        target_user=db_idea.target_user,
        core_pain=db_idea.core_pain,
        value_promise=db_idea.value_promise,
        g1=db_idea.g1, g1r=db_idea.g1r,
        g2=db_idea.g2, g2r=db_idea.g2r,
        g3=db_idea.g3, g3r=db_idea.g3r,
        reddit=db_idea.reddit,
        x_post=db_idea.x_post,
        offer=db_idea.offer,
        price=db_idea.price,
        cta=db_idea.cta,
        final_decision=db_idea.final_decision,
        score=db_idea.score,
        share_url=f"{BASE_URL}/public/idea/{share_token}",
        category=db_idea.category,
        regional_scores=db_idea.regional_scores,
        timing_analysis=db_idea.timing_analysis,
        moat_analysis=db_idea.moat_analysis,
    )

    resp_dict = response_data.model_dump()
    resp_dict["is_first_validation"] = is_first_validation
    resp_dict["referral_code"] = user.referral_code
    resp_dict["referral_credits"] = user.referral_credits

    response = JSONResponse(content=resp_dict)
    response.set_cookie("if_session", user.session_token, httponly=True, samesite="lax", max_age=86400*365)
    return response


@app.post("/api/signal")
async def log_signal(signal: SignalUpdate, db: Session = Depends(get_db)):
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
async def get_ideas(request: Request, db: Session = Depends(get_db)):
    user = get_or_create_user(request, db)
    ideas = db.query(IdeaDB).filter(IdeaDB.user_id == user.id).order_by(IdeaDB.date.desc()).all()
    return ideas


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    stats = db.query(StatsDB).first()
    total_ideas = db.query(func.count(IdeaDB.id)).scalar() or 0
    total_emails = db.query(func.count(EmailCaptureDB.id)).scalar() or 0
    avg_score = db.query(func.avg(IdeaDB.score)).scalar() or 0
    # Trust signals
    today = datetime.utcnow().date()
    ideas_today = db.query(func.count(IdeaDB.id)).filter(
        func.date(IdeaDB.date) == today
    ).scalar() or 0
    top_score = db.query(func.max(IdeaDB.score)).scalar() or 0
    total_upgrades = db.query(func.count(PurchaseDB.id)).filter(
        PurchaseDB.status == "completed"
    ).scalar() or 0

    base = {
        "validated": stats.validated if stats else 0,
        "built": stats.built if stats else 0,
        "killed": stats.killed if stats else 0,
        "week": stats.week if stats else 0,
        "total_ideas": total_ideas,
        "total_emails": total_emails,
        "avg_score": round(avg_score),
        "ideas_today": ideas_today,
        "top_score": top_score,
        "total_upgrades": total_upgrades,
    }
    return base


@app.post("/api/decision/{idea_id}")
async def finalize_decision(idea_id: str, decision: str, db: Session = Depends(get_db)):
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


@app.post("/api/email/capture")
async def capture_email(data: EmailCaptureInput, db: Session = Depends(get_db)):
    record = EmailCaptureDB(email=data.email, idea_id=data.idea_id, source=data.source, tags=data.tags)
    db.add(record)
    db.commit()
    return {"status": "captured", "email": data.email}


@app.get("/api/emails")
async def get_emails(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    emails = db.query(EmailCaptureDB).order_by(EmailCaptureDB.captured_at.desc()).all()
    return [{"email": e.email, "idea_id": e.idea_id, "source": e.source,
             "captured_at": e.captured_at.isoformat() if e.captured_at else None, "tags": e.tags} for e in emails]


# ═══════════════════════════════════════════════════════
# PREMIUM FEATURES (GATED)
# ═══════════════════════════════════════════════════════
def require_premium(idea: IdeaDB, user: UserDB):
    """Check if user has access to premium features for this idea"""
    now = datetime.utcnow()
    is_pro = user.is_pro and user.pro_expires and user.pro_expires > now
    if is_pro:
        return True
    if idea.is_premium_report:
        return True
    return False


@app.get("/api/idea/{idea_id}/premium-report")
async def get_premium_report(idea_id: str, request: Request, db: Session = Depends(get_db)):
    """Premium AI report: deeper analysis, competitive landscape, monetization strategy"""
    user = get_or_create_user(request, db)
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    if not require_premium(idea, user):
        raise HTTPException(status_code=402, detail=json.dumps({
            "error": "premium_required",
            "message": "Premium report requires a purchase. $9 one-time or $29/mo Pro.",
            "checkout_url": f"{BASE_URL}/api/checkout/create-session",
        }))

    # Generate or return cached
    if idea.blueprint and idea.revenue_sim:
        return {
            "idea_id": idea_id,
            "blueprint": idea.blueprint,
            "revenue_sim": idea.revenue_sim,
            "mvp_plan": idea.mvp_plan,
            "distribution_plan": idea.distribution_plan,
            "landing_page_html": idea.landing_page_html,
        }

    # Generate all premium content
    prompt = f"""You are an elite startup advisor. Generate a COMPLETE premium report for this validated idea.

IDEA: {idea.concept}
TARGET USER: {idea.target_user}
CORE PAIN: {idea.core_pain}
VALUE PROMISE: {idea.value_promise}
VALIDATION SCORE: {idea.score}/100
DECISION: {idea.final_decision}
OFFER: {idea.offer}
PRICE: {idea.price}

Return ONLY this JSON (no markdown):
{{
  "blueprint": {{
    "product_name": "Suggested product name",
    "tagline": "10-word tagline",
    "tech_stack": ["recommended", "tech", "stack"],
    "mvp_features": ["feature 1", "feature 2", "feature 3", "feature 4", "feature 5"],
    "day1_actions": ["action 1", "action 2", "action 3"],
    "week1_milestones": ["milestone 1", "milestone 2", "milestone 3"],
    "pricing_model": "Recommended pricing strategy",
    "competitive_advantage": "What makes this defensible",
    "risk_factors": ["risk 1", "risk 2"],
    "mitigation": ["how to mitigate risk 1", "how to mitigate risk 2"]
  }},
  "revenue_sim": {{
    "month1": {{"users": 10, "revenue": 290, "costs": 50}},
    "month3": {{"users": 50, "revenue": 1450, "costs": 150}},
    "month6": {{"users": 200, "revenue": 5800, "costs": 400}},
    "month12": {{"users": 800, "revenue": 23200, "costs": 1200}},
    "break_even_month": 2,
    "annual_revenue_potential": 278400,
    "assumptions": "List key assumptions"
  }},
  "mvp_plan": {{
    "total_hours": 40,
    "phases": [
      {{"name": "Phase 1: Core", "hours": 16, "tasks": ["task1", "task2", "task3"]}},
      {{"name": "Phase 2: Payment", "hours": 8, "tasks": ["task1", "task2"]}},
      {{"name": "Phase 3: Launch", "hours": 16, "tasks": ["task1", "task2", "task3"]}}
    ],
    "tools_needed": ["tool 1", "tool 2", "tool 3"],
    "no_code_alternative": "If applicable, a no-code way to build this"
  }},
  "distribution_plan": {{
    "channels": [
      {{"name": "Channel name", "strategy": "How to use it", "expected_cac": 5, "priority": "HIGH"}},
      {{"name": "Channel 2", "strategy": "Strategy", "expected_cac": 10, "priority": "MEDIUM"}},
      {{"name": "Channel 3", "strategy": "Strategy", "expected_cac": 0, "priority": "HIGH"}}
    ],
    "launch_sequence": ["Step 1", "Step 2", "Step 3", "Step 4"],
    "content_ideas": ["content 1", "content 2", "content 3"],
    "partnerships": "Potential partnership opportunities"
  }}
}}"""

    result = parse_json_response(call_claude(prompt, 3000))

    idea.blueprint = result.get("blueprint")
    idea.revenue_sim = result.get("revenue_sim")
    idea.mvp_plan = result.get("mvp_plan")
    idea.distribution_plan = result.get("distribution_plan")
    db.commit()

    return {
        "idea_id": idea_id,
        "blueprint": idea.blueprint,
        "revenue_sim": idea.revenue_sim,
        "mvp_plan": idea.mvp_plan,
        "distribution_plan": idea.distribution_plan,
    }


@app.get("/api/idea/{idea_id}/landing-page")
async def generate_landing_page(idea_id: str, request: Request, db: Session = Depends(get_db)):
    """Generate a complete landing page HTML for the idea"""
    user = get_or_create_user(request, db)
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    if not require_premium(idea, user):
        raise HTTPException(status_code=402, detail=json.dumps({
            "error": "premium_required",
            "message": "Landing page generator requires Pro. $9 one-time or $29/mo.",
        }))

    if idea.landing_page_html:
        return HTMLResponse(content=idea.landing_page_html)

    prompt = f"""Generate a COMPLETE, production-ready landing page HTML file for this product.
The page must be a SINGLE self-contained HTML file with embedded CSS and JS.
Make it visually stunning with a dark theme, modern design, and clear CTA.

PRODUCT: {idea.concept}
TARGET USER: {idea.target_user}
PAIN: {idea.core_pain}
VALUE: {idea.value_promise}
OFFER: {idea.offer}
PRICE: {idea.price}
CTA: {idea.cta}

Requirements:
- Hero section with headline, subheadline, CTA button
- Pain section (3 pain points)
- Solution section  
- Pricing section with the suggested price
- Email capture form (action="#" for now)
- Social proof placeholder
- FAQ section (3 questions)
- Footer
- Mobile responsive
- Dark theme (#080808 background, #c8ff00 accent)
- Google Fonts (Syne + JetBrains Mono)

Return ONLY the complete HTML. No explanation, no markdown fences."""

    html = call_claude(prompt, 4000)
    # Clean markdown fences if present
    if html.startswith("```"):
        lines = html.split("\n")
        html = "\n".join(lines[1:-1])

    idea.landing_page_html = html
    db.commit()

    return HTMLResponse(content=html)


@app.get("/api/idea/{idea_id}/twitter-thread")
async def get_twitter_thread(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    if not idea.twitter_thread:
        idea.twitter_thread = generate_twitter_thread(idea)
        db.commit()
    return {"idea_id": idea_id, "thread": idea.twitter_thread, "concept": idea.concept}


# ═══════════════════════════════════════════════════════
# PDF REPORT
# ═══════════════════════════════════════════════════════
@app.get("/api/idea/{idea_id}/pdf")
async def generate_pdf_report(idea_id: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    def safe(text):
        """Strip non-latin-1 chars (emojis etc.) for PDF compatibility"""
        if not text:
            return "N/A"
        return str(text).encode("latin-1", "ignore").decode("latin-1")

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
    pdf.cell(0, 10, "Validation Report", ln=True, align="C")
    pdf.ln(30)
    pdf.set_text_color(239, 239, 239)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 10, safe(idea.concept or "Untitled Idea"), align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 8, safe(f"ID: {idea.id}  |  Score: {idea.score}/100  |  Decision: {idea.final_decision}"), ln=True, align="C")

    # Summary
    pdf.add_page()
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Executive Summary", ln=True)
    pdf.ln(8)
    for label, value in [("Concept", idea.concept), ("Target User", idea.target_user),
                         ("Core Pain", idea.core_pain), ("Value Promise", idea.value_promise),
                         ("Category", idea.category or "N/A"), ("Score", f"{idea.score}/100")]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(45, 8, label.upper())
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 8, safe(str(value) if value else "N/A"))
        pdf.ln(2)

    # Gates
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "3-Gate Evaluation", ln=True)
    pdf.ln(8)
    for gate_name, gate_result in [("Gate 1", idea.g1r), ("Gate 2", idea.g2r), ("Gate 3", idea.g3r)]:
        result_str = str(gate_result) if gate_result else "N/A"
        is_pass = result_str.upper().startswith("YES")
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, gate_name, ln=True)
        pdf.set_text_color(0, 160, 80) if is_pass else pdf.set_text_color(220, 50, 50)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(20, 7, "PASS" if is_pass else "FAIL")
        pdf.set_text_color(80, 80, 80)
        pdf.set_font("Helvetica", "", 10)
        parts = result_str.split("\u2014", 1)
        pdf.multi_cell(0, 7, safe(parts[1].strip() if len(parts) > 1 else ""))
        pdf.ln(4)

    # Pre-sell
    pdf.add_page()
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Pre-Sell Content", ln=True)
    pdf.ln(8)
    for label, value in [("Reddit Post", idea.reddit), ("X/Twitter", idea.x_post),
                         ("Offer", idea.offer), ("Price", idea.price), ("CTA", idea.cta)]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, label.upper(), ln=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 7, safe(str(value) if value else "N/A"))
        pdf.ln(4)

    # Premium sections if available
    if idea.blueprint:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 12, "Build Blueprint (Premium)", ln=True)
        pdf.ln(8)
        bp = idea.blueprint
        for label, value in [("Product Name", bp.get("product_name")),
                             ("Tagline", bp.get("tagline")),
                             ("Tech Stack", ", ".join(bp.get("tech_stack", []))),
                             ("Pricing Model", bp.get("pricing_model")),
                             ("Competitive Advantage", bp.get("competitive_advantage"))]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 8, label.upper(), ln=True)
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 7, safe(str(value) if value else "N/A"))
            pdf.ln(2)

        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "MVP FEATURES", ln=True)
        pdf.set_font("Helvetica", "", 11)
        for feat in bp.get("mvp_features", []):
            pdf.cell(0, 7, safe(f"  - {feat}"), ln=True)

    if idea.revenue_sim:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 12, "Revenue Simulation (Premium)", ln=True)
        pdf.ln(8)
        rs = idea.revenue_sim
        for period in ["month1", "month3", "month6", "month12"]:
            data = rs.get(period, {})
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, period.upper().replace("MONTH", "MONTH "), ln=True)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, f"  Users: {data.get('users', 0)}  |  Revenue: ${data.get('revenue', 0)}  |  Costs: ${data.get('costs', 0)}", ln=True)
            pdf.ln(2)

    pdf_bytes = pdf.output()
    buffer = io.BytesIO(pdf_bytes)
    buffer.seek(0)
    safe_name = (idea.concept or "idea").replace(" ", "_")[:30]
    filename = f"validation_report_{idea.id}_{safe_name}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ═══════════════════════════════════════════════════════
# VALIDATION-AS-A-SERVICE API (with API key auth)
# ═══════════════════════════════════════════════════════
@app.post("/api/v1/validate")
async def validate_api(idea_input: IdeaInput, request: Request,
                       x_api_key: str = Header(None), db: Session = Depends(get_db)):
    """API endpoint with key-based auth and rate limiting"""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    api_key = db.query(APIKeyDB).filter(APIKeyDB.key_hash == key_hash, APIKeyDB.is_active == True).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Rate limit check
    now = datetime.utcnow()
    if api_key.last_used and api_key.last_used.month != now.month:
        api_key.calls_this_month = 0

    if api_key.calls_this_month >= api_key.calls_limit:
        raise HTTPException(status_code=429, detail=f"Monthly limit reached ({api_key.calls_limit} calls)")

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
        is_public=True,
        score=score,
        share_token=share_token,
        category=analysis.get("category", "Other"),
        user_id=api_key.user_id,
    )
    db.add(db_idea)

    api_key.calls_this_month += 1
    api_key.last_used = now
    db.commit()

    return {
        "id": idea_id,
        "concept": analysis["concept"],
        "target_user": analysis["target_user"],
        "core_pain": analysis["core_pain"],
        "value_promise": analysis["value_promise"],
        "score": score,
        "final_decision": analysis["final_decision"],
        "category": analysis.get("category"),
        "share_url": f"{BASE_URL}/public/idea/{share_token}",
        "gates": {
            "gate1": analysis["gate1"],
            "gate2": analysis["gate2"],
            "gate3": analysis["gate3"],
        },
        "presell": {
            "reddit": analysis["reddit_post"],
            "x_post": analysis["x_post"],
            "offer": analysis["offer"],
            "price": analysis["price"],
            "cta": analysis["cta"],
        }
    }


# ═══════════════════════════════════════════════════════
# OPERATOR DASHBOARD (Admin only)
# ═══════════════════════════════════════════════════════
@app.get("/api/admin/dashboard")
async def admin_dashboard(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Full operator dashboard data"""
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    total_ideas = db.query(func.count(IdeaDB.id)).scalar() or 0
    ideas_this_month = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= thirty_days_ago).scalar() or 0
    ideas_this_week = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= seven_days_ago).scalar() or 0

    total_users = db.query(func.count(UserDB.id)).scalar() or 0
    pro_users = db.query(func.count(UserDB.id)).filter(UserDB.is_pro == True).scalar() or 0

    total_revenue = db.query(func.sum(PurchaseDB.amount_cents)).filter(
        PurchaseDB.status == "completed"
    ).scalar() or 0

    revenue_this_month = db.query(func.sum(PurchaseDB.amount_cents)).filter(
        PurchaseDB.status == "completed",
        PurchaseDB.completed_at >= thirty_days_ago,
    ).scalar() or 0

    total_emails = db.query(func.count(EmailCaptureDB.id)).scalar() or 0
    emails_this_month = db.query(func.count(EmailCaptureDB.id)).filter(
        EmailCaptureDB.captured_at >= thirty_days_ago
    ).scalar() or 0

    avg_score = db.query(func.avg(IdeaDB.score)).scalar() or 0

    recent_purchases = db.query(PurchaseDB).order_by(PurchaseDB.created_at.desc()).limit(10).all()

    top_ideas = db.query(IdeaDB).order_by(IdeaDB.score.desc()).limit(5).all()

    # API usage
    api_calls = db.query(func.sum(APIKeyDB.calls_this_month)).scalar() or 0

    return {
        "overview": {
            "total_ideas": total_ideas,
            "ideas_this_month": ideas_this_month,
            "ideas_this_week": ideas_this_week,
            "total_users": total_users,
            "pro_users": pro_users,
            "total_emails": total_emails,
            "emails_this_month": emails_this_month,
            "avg_score": round(avg_score),
            "api_calls_this_month": api_calls,
        },
        "revenue": {
            "total_cents": total_revenue,
            "total_dollars": round(total_revenue / 100, 2),
            "this_month_cents": revenue_this_month,
            "this_month_dollars": round(revenue_this_month / 100, 2),
        },
        "recent_purchases": [
            {
                "id": p.id,
                "product_type": p.product_type,
                "amount": round(p.amount_cents / 100, 2),
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in recent_purchases
        ],
        "top_ideas": [
            {"id": i.id, "concept": i.concept, "score": i.score, "decision": i.final_decision}
            for i in top_ideas
        ],
        "next_actions": _get_next_actions(total_ideas, pro_users, total_revenue, total_emails),
    }


def _get_next_actions(ideas: int, pro: int, revenue_cents: int, emails: int) -> list:
    """Smart operator guidance"""
    actions = []
    if ideas == 0:
        actions.append({"action": "Submit your first idea to test the system", "priority": "HIGH"})
    if emails < 10:
        actions.append({"action": "Share graveyard/leaderboard links to capture emails", "priority": "HIGH"})
    if pro == 0:
        actions.append({"action": "Test the Stripe checkout flow end-to-end", "priority": "HIGH"})
    if revenue_cents == 0:
        actions.append({"action": "Post a validation result on Twitter/Reddit to drive traffic", "priority": "HIGH"})
    if ideas > 5 and revenue_cents == 0:
        actions.append({"action": "Enable the landing page generator for top-scoring ideas", "priority": "MEDIUM"})
    if emails >= 10:
        actions.append({"action": "Send a newsletter about top ideas to captured emails", "priority": "MEDIUM"})
    if not actions:
        actions.append({"action": "Review top ideas and share premium reports on social", "priority": "MEDIUM"})
        actions.append({"action": "Check API usage and consider pricing adjustments", "priority": "LOW"})
    return actions


# ═══════════════════════════════════════════════════════
# AUTOMATION ENDPOINTS (cron-triggered)
# ═══════════════════════════════════════════════════════
@app.post("/api/cron/auto-rank")
async def auto_rank_ideas(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Auto-rank all ideas and assign BUILD/TEST/KILL based on score + signals"""
    ideas = db.query(IdeaDB).filter(IdeaDB.score > 0).all()
    updated = 0
    for idea in ideas:
        signal_score = (idea.pay or 0) * 10 + (idea.rep or 0) * 3 + (idea.clk or 0) * 1
        total = idea.score + min(signal_score, 30)  # cap signal bonus at 30

        if total >= 80 and (idea.pay or 0) >= 1:
            new_decision = "BUILD"
        elif total >= 50:
            new_decision = "TEST FIRST"
        else:
            new_decision = "KILL"

        if idea.final_decision != new_decision:
            idea.final_decision = new_decision
            updated += 1

    db.commit()
    return {"status": "ok", "ideas_checked": len(ideas), "decisions_updated": updated}


@app.post("/api/cron/weekly-summary")
async def weekly_summary(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Generate weekly operator summary"""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    ideas_this_week = db.query(func.count(IdeaDB.id)).filter(IdeaDB.date >= week_ago).scalar() or 0
    revenue_this_week = db.query(func.sum(PurchaseDB.amount_cents)).filter(
        PurchaseDB.status == "completed",
        PurchaseDB.completed_at >= week_ago,
    ).scalar() or 0
    emails_this_week = db.query(func.count(EmailCaptureDB.id)).filter(
        EmailCaptureDB.captured_at >= week_ago
    ).scalar() or 0
    top_idea = db.query(IdeaDB).filter(IdeaDB.date >= week_ago).order_by(IdeaDB.score.desc()).first()

    return {
        "period": f"{week_ago.strftime('%b %d')} — {now.strftime('%b %d, %Y')}",
        "ideas_validated": ideas_this_week,
        "revenue_dollars": round(revenue_this_week / 100, 2),
        "emails_captured": emails_this_week,
        "top_idea": {
            "concept": top_idea.concept if top_idea else "None",
            "score": top_idea.score if top_idea else 0,
            "decision": top_idea.final_decision if top_idea else "N/A",
        } if top_idea else None,
    }


@app.post("/api/cron/generate-ideas")
async def auto_generate_ideas(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Auto-generate trending ideas based on existing validation data"""
    # Get top categories and patterns
    top_cats = db.query(IdeaDB.category, func.avg(IdeaDB.score)).group_by(
        IdeaDB.category
    ).order_by(func.avg(IdeaDB.score).desc()).limit(3).all()

    cat_str = ", ".join([f"{c[0]} (avg score: {round(c[1])})" for c in top_cats if c[0]])

    prompt = f"""Based on these high-scoring startup categories: {cat_str or "SaaS, Tool, API"}

Generate 5 new startup ideas that would score well on these validation criteria:
- Can it be built in 7 days?
- Can it charge $10+ on day 1?
- Is the pain severe enough people would switch NOW?

Return ONLY this JSON:
{{
  "ideas": [
    {{
      "raw_idea": "Clear 2-sentence description",
      "pain_who": "Who has this pain",
      "pain_quotes": "2 example complaints",
      "pain_freq": "How often they feel this",
      "pain_buyers": "3 specific buyer types"
    }}
  ]
}}"""

    result = parse_json_response(call_claude(prompt, 2000))
    return {"generated_ideas": result.get("ideas", []), "based_on_categories": cat_str}


@app.post("/api/cron/auto-validate")
async def auto_validate_generated(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Generate 1 idea from trends, validate it, and store it — fully automated"""
    # Get top categories
    top_cats = db.query(IdeaDB.category, func.avg(IdeaDB.score)).group_by(
        IdeaDB.category
    ).order_by(func.avg(IdeaDB.score).desc()).limit(3).all()
    cat_str = ", ".join([f"{c[0]} (avg score: {round(c[1])})" for c in top_cats if c[0]])

    gen_prompt = f"""Based on these high-scoring startup categories: {cat_str or "SaaS, Tool, API"}

Generate 1 startup idea with REAL pain evidence. The idea must:
- Be buildable in 7 days
- Have people willing to pay $10+ on day 1
- Solve pain that happens weekly or more often

Return ONLY this JSON:
{{
  "raw_idea": "Clear 2-sentence description of what to build and why",
  "pain_who": "Specific audience (not generic)",
  "pain_quotes": "2 realistic complaints from this audience, each 30+ chars",
  "pain_freq": "How often this pain occurs",
  "pain_buyers": "3 specific real buyer types or communities"
}}"""

    idea_data = parse_json_response(call_claude(gen_prompt, 1000))
    pain = PainInput(
        pain_who=idea_data["pain_who"],
        pain_quotes=idea_data["pain_quotes"],
        pain_freq=idea_data["pain_freq"],
        pain_buyers=idea_data["pain_buyers"],
    )

    analysis = analyze_idea_with_claude(idea_data["raw_idea"], pain)
    idea_id = str(uuid.uuid4())[:8]
    share_token = secrets.token_urlsafe(12)
    score = calculate_score(analysis)

    db_idea = IdeaDB(
        id=idea_id,
        pain_who=pain.pain_who,
        pain_quotes=pain.pain_quotes,
        pain_freq=pain.pain_freq,
        pain_buyers=pain.pain_buyers,
        raw_idea=idea_data["raw_idea"],
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
        is_public=True,
        score=score,
        share_token=share_token,
        category=analysis.get("category", "Other"),
    )
    db.add(db_idea)

    stats = db.query(StatsDB).first()
    if stats:
        stats.validated += 1
        stats.week += 1
    else:
        db.add(StatsDB(validated=1, week=1))
    db.commit()

    return {
        "status": "ok",
        "idea_id": idea_id,
        "concept": analysis["concept"],
        "score": score,
        "decision": analysis["final_decision"],
        "share_url": f"{BASE_URL}/public/idea/{share_token}",
    }


@app.post("/api/cron/ready-to-post")
async def generate_post_content(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """Generate ready-to-paste social posts for the best unposted idea today"""
    # Find today's highest-scoring idea (or highest unposted)
    today = datetime.utcnow().date()
    idea = db.query(IdeaDB).filter(
        func.date(IdeaDB.date) == today, IdeaDB.score > 0
    ).order_by(IdeaDB.score.desc()).first()

    if not idea:
        idea = db.query(IdeaDB).filter(
            IdeaDB.score > 0, IdeaDB.view_count == 0
        ).order_by(IdeaDB.score.desc()).first()

    if not idea:
        return {"status": "no_ideas", "message": "No unposted ideas found. Run /api/cron/auto-validate first."}

    share_url = f"{BASE_URL}/public/idea/{idea.share_token}" if idea.share_token else BASE_URL

    prompt = f"""Generate 2 social media posts for this validated startup idea. These must be ready-to-paste — no placeholders.

IDEA: {idea.concept}
SCORE: {idea.score}/100
DECISION: {idea.final_decision}
TARGET: {idea.target_user}
PAIN: {idea.core_pain}
REDDIT POST (generated): {idea.reddit}
X POST (generated): {idea.x_post}
SHARE LINK: {share_url}

Generate EXACTLY this JSON:
{{
  "post_a": {{
    "platform": "reddit",
    "subreddit": "r/specific_subreddit_name",
    "title": "Reddit post title (max 100 chars, curiosity-driven)",
    "body": "Full Reddit post body (200-300 chars). Must include the share link naturally. Lead with pain, show the validation result, end with a question to drive comments."
  }},
  "post_b": {{
    "platform": "x",
    "tweet": "Single tweet (max 280 chars). Hook + result + link. Must feel natural, not promotional.",
    "thread": "Optional 3-tweet thread version. Each tweet separated by \\n\\n. First tweet is the hook, last tweet has the link."
  }},
  "linkedin": {{
    "post": "LinkedIn version (300-500 chars). Professional tone, insight-driven, includes link."
  }},
  "engagement_replies": [
    "Ready reply for 'how does this work?' comments",
    "Ready reply for 'is this real?' comments",
    "Ready reply for 'I have a similar idea' comments"
  ]
}}"""

    result = parse_json_response(call_claude(prompt, 2000))
    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    return {
        "status": "ok",
        "idea_id": idea.id,
        "concept": idea.concept,
        "score": idea.score,
        "decision": idea.final_decision,
        "share_url": share_url,
        "posts": result,
    }


@app.get("/api/admin/daily-digest")
async def daily_digest(admin: bool = Depends(check_admin), db: Session = Depends(get_db)):
    """3-number daily digest: clicks, replies (signals), payments"""
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    # Clicks = view_count changes (ideas viewed today)
    ideas_viewed_today = db.query(func.count(IdeaDB.id)).filter(
        IdeaDB.view_count > 0,
        func.date(IdeaDB.date) == today,
    ).scalar() or 0

    # Total signal activity today (pay + rep + clk across all ideas)
    today_ideas = db.query(IdeaDB).filter(func.date(IdeaDB.date) == today).all()
    total_signals = sum((i.pay or 0) + (i.rep or 0) + (i.clk or 0) for i in today_ideas)

    # Payments today
    payments_today = db.query(func.count(PurchaseDB.id)).filter(
        PurchaseDB.status == "completed",
        func.date(PurchaseDB.completed_at) == today,
    ).scalar() or 0
    revenue_today = db.query(func.sum(PurchaseDB.amount_cents)).filter(
        PurchaseDB.status == "completed",
        func.date(PurchaseDB.completed_at) == today,
    ).scalar() or 0

    # Payments yesterday (for comparison)
    payments_yesterday = db.query(func.count(PurchaseDB.id)).filter(
        PurchaseDB.status == "completed",
        func.date(PurchaseDB.completed_at) == yesterday,
    ).scalar() or 0

    # New users today
    new_users_today = db.query(func.count(UserDB.id)).filter(
        func.date(UserDB.created_at) == today,
    ).scalar() or 0

    # Emails captured today
    emails_today = db.query(func.count(EmailCaptureDB.id)).filter(
        func.date(EmailCaptureDB.captured_at) == today,
    ).scalar() or 0

    # Best idea today
    best_today = db.query(IdeaDB).filter(
        func.date(IdeaDB.date) == today
    ).order_by(IdeaDB.score.desc()).first()

    return {
        "date": today.isoformat(),
        "three_numbers": {
            "clicks": ideas_viewed_today,
            "signals": total_signals,
            "payments": payments_today,
        },
        "revenue_today_dollars": round((revenue_today or 0) / 100, 2),
        "new_users": new_users_today,
        "emails_captured": emails_today,
        "payments_vs_yesterday": "up" if payments_today > payments_yesterday else "same" if payments_today == payments_yesterday else "down",
        "best_idea_today": {
            "concept": best_today.concept,
            "score": best_today.score,
            "share_url": f"{BASE_URL}/public/idea/{best_today.share_token}" if best_today.share_token else None,
        } if best_today else None,
    }


# ═══════════════════════════════════════════════════════
# PUBLIC PAGES
# ═══════════════════════════════════════════════════════

def _html_head(title: str, description: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#080808; --surface:#0f0f0f; --border:#1f1f1f; --text:#efefef; --text-muted:#6a6a6a;
  --accent:#c8ff00; --green:#00e87a; --red:#ff3b3b; --orange:#ff9f1c; --blue:#4ea8de;
  --font:'Syne',sans-serif; --mono:'JetBrains Mono',monospace; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:var(--font); min-height:100vh; }}
.container {{ max-width:1100px; margin:0 auto; padding:30px 20px; }}
h1 {{ font-size:36px; font-weight:800; color:var(--accent); margin-bottom:8px; }}
.subtitle {{ font-family:var(--mono); font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.2em; margin-bottom:30px; }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:22px; margin-bottom:16px; transition:border-color 0.2s; }}
.card:hover {{ border-color:var(--accent); }}
.badge {{ display:inline-block; padding:3px 10px; border-radius:20px; font-family:var(--mono); font-size:10px; text-transform:uppercase; }}
.badge-kill {{ background:rgba(255,59,59,0.15); color:var(--red); }}
.badge-build {{ background:rgba(0,232,122,0.15); color:var(--green); }}
.badge-test {{ background:rgba(200,255,0,0.15); color:var(--accent); }}
.score-bar {{ height:6px; background:var(--border); border-radius:3px; margin:8px 0; overflow:hidden; }}
.score-fill {{ height:100%; border-radius:3px; }}
.meta {{ font-family:var(--mono); font-size:11px; color:var(--text-muted); }}
.btn {{ display:inline-block; background:var(--accent); color:var(--bg); padding:10px 20px; border-radius:8px; font-family:var(--mono); font-size:11px; font-weight:600; text-transform:uppercase; cursor:pointer; border:none; text-decoration:none; }}
.btn:hover {{ opacity:0.9; }}
.share-btn {{ background:transparent; border:1px solid var(--border); color:var(--text-muted); padding:6px 12px; border-radius:6px; font-family:var(--mono); font-size:10px; cursor:pointer; text-decoration:none; display:inline-block; margin:4px; }}
.share-btn:hover {{ border-color:var(--accent); color:var(--accent); }}
.cta-bar {{ background:var(--surface); border:1px solid var(--accent); border-radius:14px; padding:20px; text-align:center; margin:30px 0; }}
.cta-bar h3 {{ color:var(--accent); margin-bottom:8px; }}
.email-form {{ display:flex; gap:10px; justify-content:center; margin-top:12px; max-width:500px; margin-left:auto; margin-right:auto; }}
.email-form input {{ flex:1; padding:10px 14px; background:var(--bg); border:1px solid var(--border); color:var(--text); border-radius:8px; font-family:var(--mono); font-size:12px; outline:none; }}
.nav {{ display:flex; gap:20px; margin-bottom:30px; padding-bottom:16px; border-bottom:1px solid var(--border); align-items:center; flex-wrap:wrap; }}
.nav a {{ font-family:var(--mono); font-size:12px; text-transform:uppercase; letter-spacing:0.1em; color:var(--text-muted); text-decoration:none; }}
.nav a:hover,.nav a.active {{ color:var(--accent); }}
.nav-brand {{ font-weight:800; font-size:18px; color:var(--accent) !important; margin-right:auto; }}
.stats-row {{ display:flex; gap:16px; margin-bottom:30px; flex-wrap:wrap; }}
.stat-box {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:16px 20px; flex:1; min-width:120px; text-align:center; }}
.stat-num {{ font-size:28px; font-weight:800; color:var(--accent); }}
.stat-label {{ font-family:var(--mono); font-size:10px; color:var(--text-muted); text-transform:uppercase; margin-top:4px; }}
.filter-bar {{ display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap; }}
.filter-btn {{ background:var(--surface); border:1px solid var(--border); color:var(--text-muted); padding:6px 14px; border-radius:20px; font-family:var(--mono); font-size:11px; cursor:pointer; }}
.filter-btn.active {{ border-color:var(--accent); color:var(--accent); background:rgba(200,255,0,0.08); }}
a {{ color:var(--accent); text-decoration:none; }}
@media(max-width:600px) {{ .stats-row {{ gap:8px; }} .stat-box {{ min-width:80px; padding:10px; }} }}
</style></head>"""


def _nav_html(active: str = "") -> str:
    return f"""<nav class="nav">
  <a href="/" class="nav-brand">IDEA FACTORY</a>
  <a href="/public/graveyard" class="{'active' if active == 'graveyard' else ''}">Graveyard</a>
  <a href="/public/leaderboard" class="{'active' if active == 'leaderboard' else ''}">Leaderboard</a>
</nav>"""


@app.get("/public/graveyard", response_class=HTMLResponse)
async def public_graveyard(category: Optional[str] = None, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    per_page = 20
    query = db.query(IdeaDB).filter(IdeaDB.is_public == True, IdeaDB.final_decision.ilike("%KILL%"))
    if category:
        query = query.filter(IdeaDB.category == category)
    total = query.count()
    ideas = query.order_by(IdeaDB.date.desc()).offset((page - 1) * per_page).limit(per_page).all()
    categories = db.query(IdeaDB.category, func.count(IdeaDB.id)).filter(
        IdeaDB.is_public == True, IdeaDB.final_decision.ilike("%KILL%")
    ).group_by(IdeaDB.category).all()
    killed_count = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%KILL%")).scalar() or 0

    idea_cards = ""
    for idea in ideas:
        kill_reason = ""
        if idea.ai_response and isinstance(idea.ai_response, dict):
            kill_reason = idea.ai_response.get("kill_reason", "")
        if not kill_reason:
            kill_reason = "Failed validation gates"
        date_str = idea.date.strftime("%b %d, %Y") if idea.date else ""
        share_url = f"/public/idea/{idea.share_token}" if idea.share_token else "#"
        idea_cards += f"""<div class="card"><div style="display:flex;align-items:start;gap:12px;">
          <span style="font-size:28px;">💀</span><div style="flex:1;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <a href="{share_url}" style="font-size:17px;font-weight:700;color:var(--text);">{idea.concept or 'Untitled'}</a>
            <span class="badge badge-kill">KILLED</span></div>
          <div style="font-size:13px;color:var(--text-muted);margin:6px 0;">{kill_reason}</div>
          <div class="score-bar"><div class="score-fill" style="width:{idea.score}%;background:var(--red);"></div></div>
          <div class="meta">Score: {idea.score}/100 · {idea.category or 'Other'} · {date_str}</div>
          </div></div></div>"""

    cat_filters = '<button class="filter-btn active" onclick="location.href=\'/public/graveyard\'">All</button>'
    for cat_name, cat_count in categories:
        if cat_name:
            cat_filters += f'<button class="filter-btn" onclick="location.href=\'/public/graveyard?category={cat_name}\'">{cat_name} ({cat_count})</button>'

    html = f"""{_html_head("Idea Graveyard — Startup Ideas That Failed AI Validation",
        f"{killed_count} startup ideas killed by AI validation.")}
<body><div class="container">{_nav_html("graveyard")}
<h1>💀 Idea Graveyard</h1><p class="subtitle">{killed_count} ideas killed by AI — learn from them</p>
<div class="stats-row"><div class="stat-box"><div class="stat-num">{killed_count}</div><div class="stat-label">Killed</div></div>
<div class="stat-box"><div class="stat-num">{len(categories)}</div><div class="stat-label">Categories</div></div></div>
<div class="filter-bar">{cat_filters}</div>
{idea_cards if idea_cards else '<div class="card" style="text-align:center;padding:40px;"><p style="color:var(--text-muted);">No killed ideas yet.</p></div>'}
<div class="cta-bar"><h3>Got an idea? Find out if it's worth building.</h3>
<p style="color:var(--text-muted);font-size:13px;">AI validation in 30 seconds. Free.</p>
<div class="email-form"><input type="email" id="gEmail" placeholder="your@email.com">
<button class="btn" onclick="captureEmail('gEmail','graveyard')">Get Started</button></div>
<div id="graveyardMsg" style="font-family:var(--mono);font-size:11px;color:var(--green);margin-top:8px;"></div></div>
</div>
<script>
async function captureEmail(inputId, source) {{
  const email = document.getElementById(inputId).value.trim();
  if (!email || !email.includes('@')) {{ alert('Enter a valid email'); return; }}
  try {{ await fetch('/api/email/capture', {{ method:'POST', headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{email, source}}) }}); document.getElementById(inputId).value='';
    document.getElementById(source+'Msg').textContent='✓ You\\'re on the list!';
  }} catch(e) {{ alert('Error. Try again.'); }}
}}
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/public/leaderboard", response_class=HTMLResponse)
async def public_leaderboard(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(IdeaDB).filter(IdeaDB.is_public == True, IdeaDB.score > 0)
    if category:
        query = query.filter(IdeaDB.category == category)
    ideas = query.order_by(IdeaDB.score.desc()).limit(50).all()
    total = db.query(func.count(IdeaDB.id)).filter(IdeaDB.is_public == True).scalar() or 0
    avg_score = db.query(func.avg(IdeaDB.score)).filter(IdeaDB.is_public == True).scalar() or 0
    build_count = db.query(func.count(IdeaDB.id)).filter(IdeaDB.final_decision.ilike("%BUILD%")).scalar() or 0

    idea_rows = ""
    for rank, idea in enumerate(ideas, 1):
        decision = idea.final_decision or "PENDING"
        badge_class = "badge-build" if "BUILD" in decision.upper() else "badge-kill" if "KILL" in decision.upper() else "badge-test"
        score_color = "var(--green)" if idea.score >= 70 else "var(--orange)" if idea.score >= 40 else "var(--red)"
        share_url = f"/public/idea/{idea.share_token}" if idea.share_token else "#"
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
        idea_rows += f"""<div class="card" style="display:flex;align-items:center;gap:16px;">
          <div style="font-size:{22 if rank<=3 else 14}px;font-weight:800;min-width:40px;text-align:center;">{medal}</div>
          <div style="flex:1;"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <a href="{share_url}" style="font-size:16px;font-weight:700;color:var(--text);">{idea.concept or 'Untitled'}</a>
            <span class="badge {badge_class}">{decision}</span></div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">{idea.target_user or ''} · {idea.category or 'Other'}</div>
          <div class="score-bar"><div class="score-fill" style="width:{idea.score}%;background:{score_color};"></div></div></div>
          <div style="text-align:center;min-width:60px;"><div style="font-size:24px;font-weight:800;color:{score_color};">{idea.score}</div><div class="meta">/100</div></div></div>"""

    html = f"""{_html_head("Idea Leaderboard — Top AI-Validated Startup Ideas",
        f"Top {len(ideas)} ideas ranked by AI score.")}
<body><div class="container">{_nav_html("leaderboard")}
<h1>🏆 Idea Leaderboard</h1><p class="subtitle">Top validated ideas ranked by AI score</p>
<div class="stats-row"><div class="stat-box"><div class="stat-num">{total}</div><div class="stat-label">Validated</div></div>
<div class="stat-box"><div class="stat-num">{round(avg_score)}</div><div class="stat-label">Avg Score</div></div>
<div class="stat-box"><div class="stat-num">{build_count}</div><div class="stat-label">Worth Building</div></div></div>
{idea_rows if idea_rows else '<div class="card" style="text-align:center;padding:40px;"><p style="color:var(--text-muted);">No ideas validated yet.</p></div>'}
<div class="cta-bar"><h3>Think your idea can top the board?</h3>
<p style="color:var(--text-muted);font-size:13px;">Get your AI validation score now.</p>
<div class="email-form"><input type="email" id="lEmail" placeholder="your@email.com">
<button class="btn" onclick="captureEmail('lEmail','leaderboard')">Get Started</button></div>
<div id="leaderboardMsg" style="font-family:var(--mono);font-size:11px;color:var(--green);margin-top:8px;"></div></div>
</div>
<script>
async function captureEmail(inputId, source) {{
  const email = document.getElementById(inputId).value.trim();
  if (!email || !email.includes('@')) {{ alert('Enter a valid email'); return; }}
  try {{ await fetch('/api/email/capture', {{ method:'POST', headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{email, source}}) }}); document.getElementById(inputId).value='';
    document.getElementById(source+'Msg').textContent='✓ You\\'re on the list!';
  }} catch(e) {{ alert('Error.'); }}
}}
</script></body></html>"""
    return HTMLResponse(content=html)


@app.get("/public/idea/{share_token}", response_class=HTMLResponse)
async def public_idea_page(share_token: str, db: Session = Depends(get_db)):
    idea = db.query(IdeaDB).filter(IdeaDB.share_token == share_token).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    idea.view_count = (idea.view_count or 0) + 1
    db.commit()

    decision = idea.final_decision or "PENDING"
    badge_class = "badge-build" if "BUILD" in decision.upper() else "badge-kill" if "KILL" in decision.upper() else "badge-test"
    score_color = "var(--green)" if idea.score >= 70 else "var(--orange)" if idea.score >= 40 else "var(--red)"
    emoji = "🚀" if "BUILD" in decision.upper() else "💀" if "KILL" in decision.upper() else "🧪"

    gates_html = ""
    for gn, (q, r) in enumerate([(idea.g1, idea.g1r), (idea.g2, idea.g2r), (idea.g3, idea.g3r)], 1):
        rs = str(r) if r else "N/A"
        ip = rs.upper().startswith("YES")
        parts = rs.split("\u2014", 1)
        reason = parts[1].strip() if len(parts) > 1 else ""
        gates_html += f"""<div style="background:var(--bg);border:1px solid {'var(--green)' if ip else 'var(--red)'};border-radius:10px;padding:16px;text-align:center;">
          <div class="meta">GATE {gn}</div>
          <div style="font-size:22px;font-weight:800;color:{'var(--green)' if ip else 'var(--red)'};margin:6px 0;">{'PASS' if ip else 'FAIL'}</div>
          <div style="font-size:11px;color:var(--text-muted);">{reason}</div></div>"""

    share_url = f"{BASE_URL}/public/idea/{share_token}"
    tweet = f"AI validated this startup idea: {idea.concept} — Score: {idea.score}/100"
    date_str = idea.date.strftime("%B %d, %Y") if idea.date else ""

    html = f"""{_html_head(f"{idea.concept or 'Idea'} — Score: {idea.score}/100",
        f"AI-validated: {idea.value_promise or idea.concept}. Score: {idea.score}/100.")}
<body><div class="container">{_nav_html("")}
<div style="text-align:center;margin-bottom:30px;">
<div style="font-size:48px;">{emoji}</div>
<h1 style="font-size:28px;color:var(--text);">{idea.concept or 'Untitled'}</h1>
<div style="margin:12px 0;"><span class="badge {badge_class}" style="font-size:13px;padding:6px 16px;">{decision}</span></div>
<div class="meta">{date_str} · {idea.category or 'Other'} · {idea.view_count or 0} views</div></div>
<div class="card" style="text-align:center;">
<div style="font-size:56px;font-weight:800;color:{score_color};">{idea.score}</div>
<div class="meta">VALIDATION SCORE / 100</div>
<div class="score-bar" style="max-width:300px;margin:8px auto;height:10px;"><div class="score-fill" style="width:{idea.score}%;background:{score_color};height:100%;"></div></div></div>
<div class="card"><div class="meta" style="margin-bottom:12px;">ANALYSIS</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
<div><div class="meta">TARGET USER</div><div style="margin-top:4px;">{idea.target_user or 'N/A'}</div></div>
<div><div class="meta">CORE PAIN</div><div style="margin-top:4px;">{idea.core_pain or 'N/A'}</div></div>
<div><div class="meta">VALUE PROMISE</div><div style="margin-top:4px;">{idea.value_promise or 'N/A'}</div></div>
<div><div class="meta">PRICE POINT</div><div style="margin-top:4px;">{idea.price or 'N/A'}</div></div></div></div>
<div class="card"><div class="meta" style="margin-bottom:12px;">3-GATE EVALUATION</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">{gates_html}</div></div>
<div class="card" style="text-align:center;"><div class="meta" style="margin-bottom:12px;">SHARE</div>
<div><a class="share-btn" href="https://twitter.com/intent/tweet?text={tweet}&url={share_url}" target="_blank">Share on X</a>
<a class="share-btn" href="https://www.linkedin.com/shareArticle?mini=true&url={share_url}" target="_blank">LinkedIn</a>
<a class="share-btn" href="/api/idea/{idea.id}/pdf" target="_blank" style="border-color:var(--accent);color:var(--accent);">PDF Report</a></div></div>
<div class="cta-bar"><h3>Validate your own idea in 30 seconds</h3>
<p style="color:var(--text-muted);font-size:13px;">Free AI validation. No signup required.</p>
<a class="btn" href="/">Validate My Idea →</a></div>
</div></body></html>"""
    return HTMLResponse(content=html)


# ═══════════════════════════════════════════════════════
# TRENDS
# ═══════════════════════════════════════════════════════
@app.get("/api/trends")
async def get_trends(db: Session = Depends(get_db)):
    categories = db.query(IdeaDB.category, func.count(IdeaDB.id), func.avg(IdeaDB.score)).group_by(IdeaDB.category).all()
    decisions = db.query(IdeaDB.final_decision, func.count(IdeaDB.id)).group_by(IdeaDB.final_decision).all()
    total = db.query(func.count(IdeaDB.id)).scalar() or 0
    high = db.query(func.count(IdeaDB.id)).filter(IdeaDB.score >= 70).scalar() or 0
    mid = db.query(func.count(IdeaDB.id)).filter(IdeaDB.score >= 40, IdeaDB.score < 70).scalar() or 0
    low = db.query(func.count(IdeaDB.id)).filter(IdeaDB.score < 40).scalar() or 0
    return {
        "categories": [{"name": c[0], "count": c[1], "avg_score": round(c[2] or 0)} for c in categories if c[0]],
        "decisions": [{"decision": d[0], "count": d[1]} for d in decisions if d[0]],
        "score_distribution": {"high": high, "mid": mid, "low": low},
        "total_ideas": total,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
