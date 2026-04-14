"""
E2E Test Suite for Idea Factory — Hardened Decision Engine
Tests all endpoints, constraints validation, kill rules, deterministic scoring,
and the removal of distraction features.
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
        t("Stats has top_score", "top_score" in stats)

        r = await c.get("/api/trends")
        t("GET /api/trends", r.status_code == 200)
        t("Trends is a dict with categories", isinstance(r.json(), dict) and "categories" in r.json())

        # ══════════════════════════════════════════
        section("2. FRONTEND PAGES")
        # ══════════════════════════════════════════
        r = await c.get("/")
        t("GET / → 200", r.status_code == 200)
        body = r.text
        t("Uses Inter font", "Inter" in body)
        t("Has score-ring CSS", "score-ring" in body)
        t("Has constraints form", "cAvailableHours" in body)
        t("Has reachable people field", "cReachablePeople" in body)
        t("Has channels field", "cChannels" in body)
        t("Has skills field", "cSkills" in body)
        t("Has Validate button", "Validate This Idea" in body)
        t("Has responsive media query", "@media" in body)
        t("No getBuildPlan function (removed)", "getBuildPlan" not in body)
        t("No premium-report reference", "premium-report" not in body)

        # ══════════════════════════════════════════
        section("3. PUBLIC PAGES")
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
        section("4. ADMIN ENDPOINTS")
        # ══════════════════════════════════════════
        # Without auth
        r = await c.get("/api/admin/dashboard")
        t("Admin dashboard no auth → 403", r.status_code == 403)
        r = await c.post("/api/cron/auto-rank")
        t("Auto-rank no auth → 403", r.status_code == 403)

        # With auth
        r = await c.get("/api/admin/dashboard", headers=admin_headers)
        t("Admin dashboard with auth → 200", r.status_code == 200)

        r = await c.post("/api/cron/auto-rank", headers=admin_headers)
        t("Auto-rank with auth → 200", r.status_code == 200)
        t("Auto-rank has checked field", "checked" in r.json())

        # ══════════════════════════════════════════
        section("5. IDEAS CRUD")
        # ══════════════════════════════════════════
        r = await c.get("/api/ideas")
        t("GET /api/ideas → 200", r.status_code == 200)
        t("Ideas is empty list", r.json() == [])

        # ══════════════════════════════════════════
        section("6. EMAIL CAPTURE")
        # ══════════════════════════════════════════
        r = await c.post("/api/email/capture", json={"email": "test@example.com", "source": "e2e_test"})
        t("Email capture → 200", r.status_code == 200)

        # ══════════════════════════════════════════
        section("7. CONSTRAINTS VALIDATION (Phase 1)")
        # ══════════════════════════════════════════
        # Missing constraints entirely
        r = await c.post("/api/analyze",
            content=json.dumps({"idea": "Test idea", "mode": "validate"}),
            headers={"Content-Type": "application/json"})
        t("Analyze without constraints → 400", r.status_code == 400)

        # Empty reachable_people
        r = await c.post("/api/analyze",
            content=json.dumps({
                "idea": "Test idea",
                "mode": "validate",
                "constraints": {
                    "available_hours": 40,
                    "skills": ["python"],
                    "audience_size": 100,
                    "channels": ["twitter"],
                    "cash_available": 500,
                    "reachable_people": []
                }
            }),
            headers={"Content-Type": "application/json"})
        t("Analyze empty reachable_people → 400", r.status_code == 400)

        # Missing idea text
        r = await c.post("/api/analyze",
            content=json.dumps({
                "idea": "",
                "mode": "validate",
                "constraints": {
                    "available_hours": 40,
                    "reachable_people": ["founders"]
                }
            }),
            headers={"Content-Type": "application/json"})
        t("Analyze empty idea → 400", r.status_code == 400)

        # ══════════════════════════════════════════
        section("8. REMOVED ENDPOINTS (Phase 6)")
        # ══════════════════════════════════════════
        r = await c.get("/api/idea/test123/pdf")
        t("PDF endpoint removed → 404/405", r.status_code in [404, 405])

        r = await c.get("/api/idea/test123/premium-report")
        t("Premium report removed → 404/405", r.status_code in [404, 405])

        r = await c.get("/api/idea/test123/landing-page")
        t("Landing page removed → 404/405", r.status_code in [404, 405])

        r = await c.get("/api/idea/test123/twitter-thread")
        t("Twitter thread removed → 404/405", r.status_code in [404, 405])

        # ══════════════════════════════════════════
        section("9. SECURITY CHECKS (Phase 11)")
        # ══════════════════════════════════════════
        r = await c.get("/api/health")
        t("No server error on normal request", r.status_code == 200)

        r = await c.get("/api/admin/dashboard")
        t("Admin no secret → 403", r.status_code == 403)
        r = await c.get("/api/admin/dashboard", headers={"x-admin-secret": "wrong"})
        t("Admin wrong secret → 403", r.status_code == 403)

    # ══════════════════════════════════════════
    section("10. UNIT TESTS — SCORING (Phase 3)")
    # ══════════════════════════════════════════
    from scoring import calculate_deterministic_score

    # Perfect scores
    analysis = {"pain_score": 100, "market_score": 100, "execution_score": 100,
                "distribution_score": 100, "feasibility_score": 100}
    t("Perfect score = 100", calculate_deterministic_score(analysis) == 100)

    # Zero scores
    analysis = {"pain_score": 0, "market_score": 0, "execution_score": 0,
                "distribution_score": 0, "feasibility_score": 0}
    t("Zero score = 0", calculate_deterministic_score(analysis) == 0)

    # Mixed scores
    analysis = {"pain_score": 70, "market_score": 60, "execution_score": 50,
                "distribution_score": 40, "feasibility_score": 80}
    expected = round(70 * 0.25 + 60 * 0.20 + 50 * 0.20 + 40 * 0.15 + 80 * 0.20)
    t(f"Mixed score = {expected}", calculate_deterministic_score(analysis) == expected)

    # Clamping
    analysis = {"pain_score": 200, "market_score": -10, "execution_score": 50,
                "distribution_score": 50, "feasibility_score": 50}
    result = calculate_deterministic_score(analysis)
    t("Clamping works (0-100)", 0 <= result <= 100)

    # ══════════════════════════════════════════
    section("11. UNIT TESTS — KILL RULES (Phase 2)")
    # ══════════════════════════════════════════
    from kill_rules import apply_kill_rules

    # Gate NO → KILL
    analysis = {
        "gate1": {"question": "Q1", "answer": "NO", "reasoning": "Bad", "evidence": "data"},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
    }
    constraints = {"reachable_people": ["founders"], "available_hours": 100, "channels": ["twitter"]}
    kill = apply_kill_rules(analysis, constraints, None)
    t("Gate NO → KILL", kill is not None and kill["decision"] == "KILL")

    # Empty reachable_people → KILL
    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
    }
    constraints = {"reachable_people": [], "available_hours": 100, "channels": ["twitter"]}
    kill = apply_kill_rules(analysis, constraints, None)
    t("Empty reachable_people → KILL", kill is not None and kill["decision"] == "KILL")

    # Build time > available → KILL
    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "build_time_hours": 200,
    }
    constraints = {"reachable_people": ["founders"], "available_hours": 40, "channels": ["twitter"]}
    kill = apply_kill_rules(analysis, constraints, None)
    t("Build time > available → KILL", kill is not None and kill["decision"] == "KILL")

    # No channels → KILL
    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
    }
    constraints = {"reachable_people": ["founders"], "available_hours": 100, "channels": []}
    kill = apply_kill_rules(analysis, constraints, None)
    t("No channels → KILL", kill is not None and kill["decision"] == "KILL")

    # No evidence → KILL
    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": ""},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
    }
    constraints = {"reachable_people": ["founders"], "available_hours": 100, "channels": ["twitter"]}
    kill = apply_kill_rules(analysis, constraints, None)
    t("No evidence → KILL", kill is not None and kill["decision"] == "KILL")

    # Empty research dict → KILL
    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
    }
    constraints = {"reachable_people": ["founders"], "available_hours": 100, "channels": ["twitter"]}
    kill = apply_kill_rules(analysis, constraints, {})
    t("Empty research → KILL", kill is not None and kill["decision"] == "KILL")

    # All pass → None (no kill)
    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": "data"},
    }
    constraints = {"reachable_people": ["founders"], "available_hours": 100, "channels": ["twitter"]}
    kill = apply_kill_rules(analysis, constraints, None)
    t("All pass → no kill", kill is None)

    # ══════════════════════════════════════════
    section("12. UNIT TESTS — DECISION ENGINE (Phase 5)")
    # ══════════════════════════════════════════
    from decision_engine import compute_final_decision

    t("Kill result → KILL", compute_final_decision(80, {"decision": "KILL", "reason": "test"}) == "KILL")
    t("Score 70 → BUILD", compute_final_decision(70, None) == "BUILD")
    t("Score 85 → BUILD", compute_final_decision(85, None) == "BUILD")
    t("Score 50 → MAYBE", compute_final_decision(50, None) == "MAYBE")
    t("Score 69 → MAYBE", compute_final_decision(69, None) == "MAYBE")
    t("Score 49 → KILL", compute_final_decision(49, None) == "KILL")
    t("Score 0 → KILL", compute_final_decision(0, None) == "KILL")

    # ══════════════════════════════════════════
    section("13. UNIT TESTS — EVIDENCE ENFORCEMENT (Phase 4)")
    # ══════════════════════════════════════════
    from main import enforce_evidence

    analysis = {
        "gate1": {"question": "Q1", "answer": "YES", "reasoning": "Ok", "evidence": ""},
        "gate2": {"question": "Q2", "answer": "YES", "reasoning": "Ok", "evidence": "real data"},
        "gate3": {"question": "Q3", "answer": "YES", "reasoning": "Ok", "evidence": ""},
    }
    enforced = enforce_evidence(analysis)
    t("Missing evidence → gate downgraded to NO", enforced["gate1"]["answer"] == "NO")
    t("Present evidence → gate stays YES", enforced["gate2"]["answer"] == "YES")
    t("Missing evidence gate3 → downgraded to NO", enforced["gate3"]["answer"] == "NO")

    # ══════════════════════════════════════════
    section("14. UNIT TESTS — JSON PARSER (Phase 9)")
    # ══════════════════════════════════════════
    from main import parse_json_response

    # Normal JSON
    t("Parse normal JSON", parse_json_response('{"key": "value"}') == {"key": "value"})

    # JSON with markdown fences
    t("Parse markdown-fenced JSON", parse_json_response('```json\n{"key": "value"}\n```') == {"key": "value"})

    # JSON with text around it
    t("Parse JSON embedded in text", parse_json_response('Here is the result: {"key": "value"} done') == {"key": "value"})

    # Invalid JSON raises
    try:
        parse_json_response("not json at all")
        t("Invalid JSON raises ValueError", False)
    except ValueError:
        t("Invalid JSON raises ValueError", True)


asyncio.run(run_all())

print(f"\n{'='*60}")
print(f"  RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed, {PASS_COUNT+FAIL_COUNT} total")
print(f"{'='*60}")
if FAIL_COUNT > 0:
    print("  ⚠ Some tests failed — review above output")
sys.exit(1 if FAIL_COUNT > 0 else 0)
