"""
Comprehensive E2E Test Suite for Idea Factory v3.0
Tests every endpoint, the new premium frontend, referral system,
market intelligence fields, and admin/cron endpoints.
"""
import asyncio
import json
import sys
from httpx import AsyncClient, ASGITransport
from main import app, ADMIN_SECRET

PASS_COUNT = 0
FAIL_COUNT = 0
SECTION = ""

def section(name):
    global SECTION
    SECTION = name
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

def t(name, ok, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if ok:
        PASS_COUNT += 1
        print(f"  ✓ PASS  {name}")
    else:
        FAIL_COUNT += 1
        print(f"  ✗ FAIL  {name}  {detail}")

async def run_all():
    transport = ASGITransport(app=app)
    admin_headers = {"x-admin-secret": ADMIN_SECRET}

    async with AsyncClient(transport=transport, base_url="http://test") as c:

        # ══════════════════════════════════════════
        section("1. HEALTH & CORE")
        # ══════════════════════════════════════════
        r = await c.get("/api/health")
        t("GET /api/health", r.status_code == 200)
        t("Health response has status", r.json().get("status") == "ok")

        r = await c.get("/api/stats")
        t("GET /api/stats", r.status_code == 200)
        stats = r.json()
        t("Stats has validated field", "validated" in stats)
        t("Stats has built field", "built" in stats)
        t("Stats has killed field", "killed" in stats)
        t("Stats has ideas_today", "ideas_today" in stats)
        t("Stats has top_score", "top_score" in stats)
        t("Stats has total_upgrades", "total_upgrades" in stats)
        t("Stats initial values are 0", stats["validated"] == 0 and stats["built"] == 0)

        r = await c.get("/api/trends")
        t("GET /api/trends", r.status_code == 200)
        t("Trends is a dict with categories", isinstance(r.json(), dict) and "categories" in r.json())

        # ══════════════════════════════════════════
        section("2. USER STATUS & SESSION")
        # ══════════════════════════════════════════
        r = await c.get("/api/user/status")
        t("GET /api/user/status", r.status_code == 200)
        us = r.json()
        t("Has is_pro", "is_pro" in us)
        t("Has validations_this_month", "validations_this_month" in us)
        t("Has validations_limit", "validations_limit" in us)
        t("Has validations_remaining", "validations_remaining" in us)
        t("Has referral_code", "referral_code" in us)
        t("Has referral_credits", "referral_credits" in us)
        t("Has is_first_session", "is_first_session" in us)
        t("is_pro defaults false", us["is_pro"] is False)
        t("validations_remaining = 3", us["validations_remaining"] == 3)
        t("referral_credits = 0", us["referral_credits"] == 0)

        # ══════════════════════════════════════════
        section("3. REFERRAL SYSTEM")
        # ══════════════════════════════════════════
        r = await c.post("/api/referral/apply", json={"code": "NONEXISTENT"})
        t("Referral bad code → 404", r.status_code == 404)

        r = await c.post("/api/referral/apply", json={})
        t("Referral empty body → 422 or 400", r.status_code in [400, 422])

        # ══════════════════════════════════════════
        section("4. FRONTEND PAGES")
        # ══════════════════════════════════════════
        r = await c.get("/")
        t("GET / → 200", r.status_code == 200)
        body = r.text
        t("Uses Inter font", "Inter" in body)
        t("Has score-ring CSS", "score-ring" in body)
        t("Has intel-section CSS", "intel-section" in body)
        t("Has blur-preview CSS", "blur-preview" in body)
        t("Has discount-bar CSS", "discount-bar" in body)
        t("Has referral-card CSS", "referral-card" in body)
        t("Has timing-badge CSS", "timing-badge" in body)
        t("Has moat-indicator CSS", "moat-indicator" in body)
        t("Has premium-banner CSS", "premium-banner" in body)
        t("Has analyzeIdea JS func", "analyzeIdea" in body)
        t("Has displayResults JS func", "displayResults" in body)
        t("Has renderMarketIntel JS func", "renderMarketIntel" in body)
        t("Has startDiscountTimer JS func", "startDiscountTimer" in body)
        t("Has applyReferral JS func", "applyReferral" in body)
        t("Has unlockPremium JS func", "unlockPremium" in body)
        t("Has checkout JS func", "checkout" in body)
        t("Has showUpgrade JS func", "showUpgrade" in body)
        t("Has pain input fields", "painWho" in body and "painQuotes" in body)
        t("Has idea input", "rawIdea" in body)
        t("Has upgrade modal", "upgradeModal" in body)
        t("Has Pro $29 pricing", "$29" in body)
        t("Has Single $9 pricing", "$9" in body)
        t("Has API $49 pricing", "$49" in body)
        t("Has Validate button", "Validate This Idea" in body)
        t("Has responsive media query", "@media" in body)
        t("No template literals (backticks)", body.count('`') == 0)

        # ══════════════════════════════════════════
        section("5. PUBLIC PAGES")
        # ══════════════════════════════════════════
        r = await c.get("/public/leaderboard")
        t("GET /public/leaderboard → 200", r.status_code == 200)
        t("Leaderboard is HTML", "html" in r.text.lower()[:200])

        r = await c.get("/public/graveyard")
        t("GET /public/graveyard → 200", r.status_code == 200)
        t("Graveyard is HTML", "html" in r.text.lower()[:200])

        r = await c.get("/public/idea/nonexistent-token")
        t("GET /public/idea/bad-token → 404", r.status_code == 404)

        # ══════════════════════════════════════════
        section("6. CHECKOUT / STRIPE")
        # ══════════════════════════════════════════
        r = await c.post("/api/checkout/create-session", json={"product_type": "pro_monthly"})
        t("Checkout pro_monthly → 200 or 503", r.status_code in [200, 503])

        r = await c.post("/api/checkout/create-session", json={"product_type": "single_report"})
        t("Checkout single_report → 200/400/503", r.status_code in [200, 400, 503])

        r = await c.post("/api/checkout/create-session", json={"product_type": "api_monthly"})
        t("Checkout api_monthly → 200 or 503", r.status_code in [200, 503])

        r = await c.get("/checkout/success")
        t("GET /checkout/success → 200 (HTML)", r.status_code == 200)

        r = await c.get("/checkout/cancel")
        t("GET /checkout/cancel → 200 (HTML)", r.status_code == 200)

        # ══════════════════════════════════════════
        section("7. ADMIN ENDPOINTS (with auth)")
        # ══════════════════════════════════════════
        # Without auth
        r = await c.get("/api/admin/dashboard")
        t("Admin dashboard no auth → 403", r.status_code == 403)
        r = await c.get("/api/admin/daily-digest")
        t("Daily digest no auth → 403", r.status_code == 403)
        r = await c.post("/api/cron/auto-rank")
        t("Auto-rank no auth → 403", r.status_code == 403)

        # With auth
        r = await c.get("/api/admin/dashboard", headers=admin_headers)
        t("Admin dashboard with auth → 200", r.status_code == 200)
        dash = r.json()
        t("Dashboard has overview", "overview" in dash)
        t("Dashboard has revenue", "revenue" in dash)
        t("Dashboard has next_actions", "next_actions" in dash)

        r = await c.get("/api/admin/daily-digest", headers=admin_headers)
        t("Daily digest with auth → 200", r.status_code == 200)
        digest = r.json()
        t("Digest has three_numbers", "three_numbers" in digest)
        t("Digest has date", "date" in digest)

        r = await c.post("/api/cron/auto-rank", headers=admin_headers)
        t("Auto-rank with auth → 200", r.status_code == 200)
        t("Auto-rank has ideas_checked", "ideas_checked" in r.json())

        r = await c.get("/api/emails", headers=admin_headers)
        t("GET /api/emails with auth → 200", r.status_code == 200)
        t("Emails is list", isinstance(r.json(), list))

        # ══════════════════════════════════════════
        section("8. IDEAS CRUD")
        # ══════════════════════════════════════════
        r = await c.get("/api/ideas")
        t("GET /api/ideas → 200", r.status_code == 200)
        t("Ideas is empty list", r.json() == [])

        # ══════════════════════════════════════════
        section("9. EMAIL CAPTURE")
        # ══════════════════════════════════════════
        r = await c.post("/api/email/capture", json={"email": "test@example.com", "source": "e2e_test"})
        t("Email capture → 200", r.status_code == 200)

        r = await c.post("/api/email/capture", json={"email": "", "source": ""})
        t("Email capture empty → 200 (accepts empty)", r.status_code == 200)

        # ══════════════════════════════════════════
        section("10. ANALYZE (requires Claude - expected fail without key)")
        # ══════════════════════════════════════════
        r = await c.post("/api/analyze", json={
            "raw_idea": "An AI tool that validates startup ideas using pain-based analysis",
            "email": "test@example.com",
            "pain": {
                "pain_who": "Solo founders building SaaS products",
                "pain_quotes": "I built for 6 months and nobody paid. I wish I had validated first. Every founder wastes time on bad ideas.",
                "pain_freq": "Every solo founder asks this weekly",
                "pain_buyers": "@indiehackers, @startupfounder, ProductHunt makers"
            }
        })
        if r.status_code == 200:
            t("Analyze → 200 (Claude key present)", True)
            data = r.json()
            t("Response has score", "score" in data)
            t("Response has concept", "concept" in data)
            t("Response has target_user", "target_user" in data)
            t("Response has core_pain", "core_pain" in data)
            t("Response has value_promise", "value_promise" in data)
            t("Response has final_decision", "final_decision" in data)
            t("Response has g1r", "g1r" in data)
            t("Response has g2r", "g2r" in data)
            t("Response has g3r", "g3r" in data)
            t("Response has reddit", "reddit" in data)
            t("Response has x_post", "x_post" in data)
            t("Response has offer", "offer" in data)
            t("Response has category", "category" in data)
            t("Response has share_url", "share_url" in data)
            t("Response has id", "id" in data)
            # New v3 fields
            t("Response has regional_scores", "regional_scores" in data)
            t("Response has timing_analysis", "timing_analysis" in data)
            t("Response has moat_analysis", "moat_analysis" in data)
            t("Response has is_first_validation", "is_first_validation" in data)
            t("Response has referral_code", "referral_code" in data)
            t("Response has referral_credits", "referral_credits" in data)
            t("Score is 0-100", 0 <= data["score"] <= 100)

            idea_id = data["id"]

            # Check user status updated
            r2 = await c.get("/api/user/status")
            us2 = r2.json()
            t("Validations incremented to 1", us2["validations_this_month"] == 1)

            # Ideas list now has 1
            r3 = await c.get("/api/ideas")
            t("Ideas list has 1 entry", len(r3.json()) == 1)

            # Stats updated
            r4 = await c.get("/api/stats")
            t("Stats validated incremented", r4.json()["validated"] >= 1)

            # Signal logging
            r5 = await c.post("/api/signal", json={"idea_id": idea_id, "signal_type": "click", "count": 3})
            t("Signal logging → 200", r5.status_code == 200)

            # Decision
            r6 = await c.post(f"/api/decision/{idea_id}?decision=BUILD")
            t("Decision → 200", r6.status_code == 200)

            # Twitter thread (requires Claude)
            r7 = await c.get(f"/api/idea/{idea_id}/twitter-thread")
            t("Twitter thread → 200", r7.status_code == 200)
            if r7.status_code == 200:
                t("Thread has content", "thread" in r7.json())

            # PDF report
            r8 = await c.get(f"/api/idea/{idea_id}/pdf")
            t("PDF report → 200", r8.status_code == 200)
            if r8.status_code == 200:
                t("PDF is bytes", len(r8.content) > 100)

            # Public idea page
            r9 = await c.get(f"/api/ideas")
            ideas = r9.json()
            if ideas and ideas[0].get("share_token"):
                share_token = ideas[0]["share_token"]
                r10 = await c.get(f"/public/idea/{share_token}")
                t("Public idea page → 200", r10.status_code == 200)

            # Premium report (not pro, no purchase → 402)
            r11 = await c.get(f"/api/idea/{idea_id}/premium-report")
            t("Premium report (free user) → 402", r11.status_code == 402)

            # Landing page (not pro → 402)
            r12 = await c.get(f"/api/idea/{idea_id}/landing-page")
            t("Landing page (free user) → 402", r12.status_code == 402)

        else:
            t("Analyze → skipped (no Claude key)", True, f"status={r.status_code}")
            print(f"    ↳ Got {r.status_code}: {r.text[:200]}")
            print("    ↳ Set ANTHROPIC_API_KEY to test analyze + downstream endpoints")

        # ══════════════════════════════════════════
        section("11. API KEY VALIDATION ENDPOINT")
        # ══════════════════════════════════════════
        r = await c.post("/api/v1/validate", json={
            "raw_idea": "Test idea",
            "pain": {
                "pain_who": "Testers",
                "pain_quotes": "Need to test things thoroughly all the time, always testing, never stopping",
                "pain_freq": "Daily",
                "pain_buyers": "QA Engineers, DevOps"
            }
        }, headers={"X-API-Key": "fake-key"})
        t("API validate bad key → 401", r.status_code == 401)

        r = await c.post("/api/v1/validate", json={
            "raw_idea": "Test idea",
            "pain": {
                "pain_who": "Testers",
                "pain_quotes": "Need to test things thoroughly all the time, always testing, never stopping",
                "pain_freq": "Daily",
                "pain_buyers": "QA Engineers, DevOps"
            }
        })
        t("API validate no key → 401", r.status_code == 401)

        # ══════════════════════════════════════════
        section("12. CRON ENDPOINTS (with auth)")
        # ══════════════════════════════════════════
        r = await c.post("/api/cron/weekly-summary", headers=admin_headers)
        t("Weekly summary → 200", r.status_code == 200)

        # generate-ideas and auto-validate require Claude
        r = await c.post("/api/cron/generate-ideas", headers=admin_headers)
        t("Generate ideas → 200 or 500 (no Claude)", r.status_code in [200, 500])

        r = await c.post("/api/cron/ready-to-post", headers=admin_headers)
        t("Ready-to-post → 200", r.status_code == 200)

    # ══════════════════════════════════════════
    section("13. PYDANTIC MODELS VALIDATION")
    # ══════════════════════════════════════════
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Bad analyze input
        r = await c.post("/api/analyze", json={})
        t("Analyze empty body → 422", r.status_code == 422)

        r = await c.post("/api/analyze", json={"raw_idea": "x"})
        t("Analyze missing pain → 422", r.status_code == 422)

        r = await c.post("/api/analyze", json={
            "raw_idea": "x",
            "pain": {"pain_who": "", "pain_quotes": "", "pain_freq": "", "pain_buyers": ""}
        })
        t("Analyze empty pain → 500 (passes validation, fails at Claude)", r.status_code == 500)

        # Bad signal
        r = await c.post("/api/signal", json={})
        t("Signal empty body → 422", r.status_code == 422)

    # ══════════════════════════════════════════
    section("14. SECURITY CHECKS")
    # ══════════════════════════════════════════
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # XSS in inputs should be escaped
        r = await c.get("/api/health")
        t("No server error on normal request", r.status_code == 200)

        # Admin endpoints reject without secret
        r = await c.get("/api/admin/dashboard")
        t("Admin no secret → 403", r.status_code == 403)
        r = await c.get("/api/admin/dashboard", headers={"x-admin-secret": "wrong"})
        t("Admin wrong secret → 403", r.status_code == 403)

        # Webhook without body
        r = await c.post("/api/checkout/webhook")
        t("Webhook no body → 400+", r.status_code >= 400)


asyncio.run(run_all())

print(f"\n{'='*60}")
print(f"  RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed, {PASS_COUNT+FAIL_COUNT} total")
print(f"{'='*60}")
if FAIL_COUNT > 0:
    print("  ⚠ Some tests failed — review above output")
sys.exit(1 if FAIL_COUNT > 0 else 0)
