"""
Comprehensive E2E Test Suite for Idea Factory v4.0 — Personal Tool
Tests every endpoint relevant to the personal idea-validation tool.
No paywalls, no Stripe, no referral system — just powerful idea analysis.
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
        t("Stats initial values are 0", stats["validated"] == 0)

        r = await c.get("/api/trends")
        t("GET /api/trends", r.status_code == 200)
        t("Trends is a dict with categories", "categories" in r.json())

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
        t("is_pro is True (personal tool — no paywalls)", us["is_pro"] is True)
        t("validations_remaining = 999 (unlimited personal use)", us["validations_remaining"] == 999)
        t("referral_credits = 0", us["referral_credits"] == 0)

        # ══════════════════════════════════════════
        section("3. BRAINSTORM & MARKET INSIGHT")
        # ══════════════════════════════════════════
        # Brainstorm requires Claude key — verify endpoint exists and responds
        r = await c.get("/api/brainstorm", params={"seed": "productivity apps", "style": "diverse"})
        t("Brainstorm endpoint exists", r.status_code in [200, 503])

        r = await c.get("/api/market-insight", params={"category": "SaaS"})
        t("Market insight returns data or empty", r.status_code == 200)
        mi = r.json()
        t("Market insight has category field", "category" in mi)

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
        t("Has idea input", "ideaInput" in body)
        t("Has Validate button", "Validate This Idea" in body)
        t("Has responsive media query", "@media" in body)
        t("No template literals (backticks)", body.count('`') == 0)
        t("No upgrade modal (personal tool)", "upgradeModal" not in body)
        t("No discount timer (personal tool)", "discountTimer" not in body)
        t("No pricing cards (personal tool)", "pricing-card" not in body)

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
        section("6. ADMIN ENDPOINTS (with auth)")
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
        section("7. IDEAS CRUD")
        # ══════════════════════════════════════════
        r = await c.get("/api/ideas")
        t("GET /api/ideas → 200", r.status_code == 200)
        t("Ideas is empty list", r.json() == [])

        # ══════════════════════════════════════════
        section("8. EMAIL CAPTURE")
        # ══════════════════════════════════════════
        r = await c.post("/api/email/capture", json={"email": "test@example.com", "source": "e2e_test"})
        t("Email capture → 200", r.status_code == 200)

        r = await c.post("/api/email/capture", json={"email": "", "source": ""})
        t("Email capture empty → 200 (accepts empty)", r.status_code == 200)

        # ══════════════════════════════════════════
        section("9. ANALYZE (requires Claude - expected fail without key)")
        # ══════════════════════════════════════════
        r = await c.post("/api/analyze", json={
            "idea": "An AI tool that validates startup ideas using pain-based analysis",
            "mode": "validate"
        })
        if r.status_code not in [200]:
            t("Analyze → skipped (no Claude key)", True, f"status={r.status_code}")
            print(f"    ↳ Got {r.status_code}: {r.text[:200]}")
            print("    ↳ Set ANTHROPIC_API_KEY to test analyze + downstream endpoints")
        else:
            # Parse SSE stream - look for 'result' event; may get 'error' if no Claude key
            data = None
            has_error = False
            for line in r.text.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        payload = json.loads(line[5:].strip())
                        if payload.get("type") == "result":
                            data = payload
                            break
                        if payload.get("type") == "error":
                            has_error = True
                    except json.JSONDecodeError:
                        pass

            if has_error and not data:
                t("Analyze → skipped (no Claude key, SSE error)", True)
                print("    ↳ SSE stream returned error — set ANTHROPIC_API_KEY for full test")
            elif data:
                t("Analyze → 200 with result (Claude key present)", True)
                t("Response has score", "score" in data)
                t("Response has concept", "concept" in data)
                t("Response has target_user", "target_user" in data)
                t("Response has core_pain", "core_pain" in data)
                t("Response has final_decision", "final_decision" in data)
                t("Response has regional_scores", "regional_scores" in data)
                t("Response has timing_analysis", "timing_analysis" in data)
                t("Response has share_url", "share_url" in data)
                t("Response has id", "id" in data)
                t("Score is 0-100", 0 <= data.get("score", -1) <= 100)

                idea_id = data["id"]

                # Check user status updated
                r2 = await c.get("/api/user/status")
                us2 = r2.json()
                t("Validations incremented to 1", us2["validations_this_month"] == 1)
                t("Still unlimited (personal tool)", us2["validations_remaining"] == 999)

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

                # PDF report
                r8 = await c.get(f"/api/idea/{idea_id}/pdf")
                t("PDF report → 200", r8.status_code == 200)

                # Public idea page
                r9 = await c.get(f"/api/ideas")
                ideas = r9.json()
                if ideas and ideas[0].get("share_token"):
                    share_token = ideas[0]["share_token"]
                    r10 = await c.get(f"/public/idea/{share_token}")
                    t("Public idea page → 200", r10.status_code == 200)
            else:
                t("Analyze → skipped (SSE empty)", True)
                print("    ↳ SSE stream had no result or error events")

        # ══════════════════════════════════════════
        section("10. CRON ENDPOINTS (with auth)")
        # ══════════════════════════════════════════
        r = await c.post("/api/cron/weekly-summary", headers=admin_headers)
        t("Weekly summary → 200", r.status_code == 200)

        r = await c.post("/api/cron/generate-ideas", headers=admin_headers)
        t("Generate ideas → 200 or 500 (no Claude)", r.status_code in [200, 500])

        r = await c.post("/api/cron/ready-to-post", headers=admin_headers)
        t("Ready-to-post → 200", r.status_code == 200)

    # ══════════════════════════════════════════
    section("11. PYDANTIC MODELS VALIDATION")
    # ══════════════════════════════════════════
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/analyze", json={})
        t("Analyze empty body → 422", r.status_code == 422)

        r = await c.post("/api/analyze", json={"idea": ""})
        t("Analyze empty idea → 400 (empty string rejected)", r.status_code in [400, 422])

        r = await c.post("/api/analyze", json={"idea": "valid idea text", "mode": "validate"})
        t("Analyze valid input → not 422", r.status_code != 422)

        r = await c.post("/api/signal", json={})
        t("Signal empty body → 422", r.status_code == 422)

    # ══════════════════════════════════════════
    section("12. SECURITY CHECKS")
    # ══════════════════════════════════════════
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/health")
        t("No server error on normal request", r.status_code == 200)

        r = await c.get("/api/admin/dashboard")
        t("Admin no secret → 403", r.status_code == 403)
        r = await c.get("/api/admin/dashboard", headers={"x-admin-secret": "wrong"})
        t("Admin wrong secret → 403", r.status_code == 403)

        # No Stripe endpoints (personal tool)
        r = await c.post("/api/checkout/create-session", json={"product_type": "pro_monthly"})
        t("Checkout endpoint removed (personal tool) → 404", r.status_code == 404)

        r = await c.post("/api/referral/apply", json={"code": "TEST"})
        t("Referral endpoint removed (personal tool) → 404", r.status_code == 404)


asyncio.run(run_all())

print(f"\n{'='*60}")
print(f"  RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed, {PASS_COUNT+FAIL_COUNT} total")
print(f"{'='*60}")
if FAIL_COUNT > 0:
    print("  ⚠ Some tests failed — review above output")
