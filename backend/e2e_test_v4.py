"""
Idea Factory v4.0 — End-to-End Test Suite
Tests every endpoint, SSE streaming, DB persistence, PDF generation, public pages.
"""
import requests
import json
import time
import sys

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
ERRORS = []

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ══════════════════════════════════════════════════
#  1. HEALTH & BASIC
# ══════════════════════════════════════════════════
section("1. HEALTH & BASIC ENDPOINTS")

r = requests.get(f"{BASE}/api/health")
test("GET /api/health returns 200", r.status_code == 200)
d = r.json()
test("Health has status=ok", d.get("status") == "ok")
test("Health has version=4.0.0", d.get("version") == "4.0.0")
test("Health has engines dict", isinstance(d.get("engines"), dict))
test("Claude engine key exists", "claude" in d.get("engines", {}))
test("Perplexity engine key exists", "perplexity" in d.get("engines", {}))
test("GPT-4o engine key exists", "gpt4o" in d.get("engines", {}))
test("Grok engine key exists", "grok" in d.get("engines", {}))
test("Claude is enabled (has API key)", d["engines"]["claude"] == True)

# ══════════════════════════════════════════════════
#  2. FRONTEND SERVING
# ══════════════════════════════════════════════════
section("2. FRONTEND SERVING")

r = requests.get(f"{BASE}/")
test("GET / returns 200", r.status_code == 200)
test("Root returns HTML", "text/html" in r.headers.get("content-type", ""))
test("HTML contains Idea Factory title", "Idea Factory" in r.text)
test("HTML contains v4 marker", "/ v4" in r.text)
test("HTML has ideaInput textarea", 'id="ideaInput"' in r.text)
test("HTML has analyze button", 'analyzeBtn' in r.text)
test("HTML has pipeline section", 'id="pipeline"' in r.text)
test("HTML has results section", 'id="results"' in r.text)
test("HTML has score ring", 'scoreArc' in r.text)
test("HTML has history section", 'historyList' in r.text)
test("HTML has engine status bar", 'id="engines"' in r.text)
test("HTML has SSE handler JS", 'handleSSE' in r.text)
test("HTML has XSS escape function", 'function esc(' in r.text)
test("HTML has leaderboard nav", '/public/leaderboard' in r.text)
test("HTML has graveyard nav", '/public/graveyard' in r.text)

# ══════════════════════════════════════════════════
#  3. STATS (before any ideas)
# ══════════════════════════════════════════════════
section("3. STATS ENDPOINT")

r = requests.get(f"{BASE}/api/stats")
test("GET /api/stats returns 200", r.status_code == 200)
d = r.json()
test("Stats has validated field", "validated" in d)
test("Stats has total_ideas field", "total_ideas" in d)
test("Stats has avg_score field", "avg_score" in d)
test("Stats has top_score field", "top_score" in d)

# ══════════════════════════════════════════════════
#  4. ANALYZE (SSE STREAM) — The Core Feature
# ══════════════════════════════════════════════════
section("4. ANALYZE — SSE Stream (Core Feature)")

# Test empty idea rejection
r = requests.post(f"{BASE}/api/analyze", json={"idea": ""})
test("Empty idea returns 400", r.status_code == 400)

r = requests.post(f"{BASE}/api/analyze", json={"idea": "   "})
test("Whitespace-only idea returns 400", r.status_code == 400)

# Test actual analysis with SSE
print("\n  📡 Starting SSE stream analysis (this takes 15-60s)...")
idea_text = "A Chrome extension that automatically summarizes long email threads into 3 bullet points"
events = []
result = None

try:
    r = requests.post(
        f"{BASE}/api/analyze",
        json={"idea": idea_text},
        stream=True,
        timeout=120
    )
    test("POST /api/analyze returns 200", r.status_code == 200)
    test("Response is SSE stream", "text/event-stream" in r.headers.get("content-type", ""))

    buffer = ""
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        buffer += chunk
        lines = buffer.split("\n")
        buffer = lines.pop()
        for line in lines:
            if line.startswith("data: "):
                try:
                    evt = json.loads(line[6:])
                    events.append(evt)
                    if evt.get("type") == "step":
                        status_icon = "🔄" if evt["status"] == "start" else "✅" if evt["status"] == "done" else "⏭️"
                        print(f"    {status_icon} [{evt.get('ai','?')}] {evt.get('status')}: {evt.get('label') or evt.get('summary','')}")
                    elif evt.get("type") == "result":
                        result = evt
                        print(f"    🎯 Result received! Score: {evt.get('score')}, Verdict: {evt.get('verdict')}")
                except json.JSONDecodeError:
                    pass

except requests.exceptions.Timeout:
    test("SSE stream completed within timeout", False, "Timed out after 120s")
except Exception as e:
    test("SSE stream no errors", False, str(e))

# Validate SSE events
step_events = [e for e in events if e.get("type") == "step"]
result_events = [e for e in events if e.get("type") == "result"]

test("Got step events", len(step_events) > 0, f"Got {len(step_events)}")
test("Got exactly 1 result event", len(result_events) == 1, f"Got {len(result_events)}")

# Check pipeline steps
ai_names_seen = set(e.get("ai") for e in step_events)
test("Perplexity step events present", "perplexity" in ai_names_seen)
test("Grok step events present", "grok" in ai_names_seen)
test("Claude step events present", "claude" in ai_names_seen)
test("GPT step events present", "gpt" in ai_names_seen)

start_events = [e for e in step_events if e.get("status") == "start"]
done_or_skip = [e for e in step_events if e.get("status") in ("done", "skipped")]
test("Each AI had a start event", len(start_events) >= 4, f"Got {len(start_events)} starts")
test("Each AI had a done/skipped event", len(done_or_skip) >= 4, f"Got {len(done_or_skip)} completions")

# Claude must always run (has API key)
claude_events = [e for e in step_events if e.get("ai") == "claude"]
claude_done = any(e.get("status") == "done" for e in claude_events)
test("Claude completed (has API key)", claude_done)

# ══════════════════════════════════════════════════
#  5. VALIDATE RESULT STRUCTURE
# ══════════════════════════════════════════════════
section("5. RESULT STRUCTURE VALIDATION")

if result:
    # Core fields
    test("Result has id", isinstance(result.get("id"), str) and len(result["id"]) > 0)
    test("Result has idea text", result.get("idea") == idea_text)
    test("Result has concept", isinstance(result.get("concept"), str) and len(result["concept"]) > 0)
    test("Result has target_user", isinstance(result.get("target_user"), str))
    test("Result has core_pain", isinstance(result.get("core_pain"), str))
    test("Result has value_promise", isinstance(result.get("value_promise"), str))
    test("Result has summary", isinstance(result.get("summary"), str) and len(result["summary"]) > 0)
    test("Result has category", isinstance(result.get("category"), str))

    # Verdict & Score
    test("Result has verdict", result.get("verdict") in ("BUILD", "SKIP", "MAYBE"))
    score = result.get("score", -1)
    test("Result has score (0-100)", isinstance(score, int) and 0 <= score <= 100, f"score={score}")

    # Scores breakdown
    scores = result.get("scores", {})
    test("Scores has pain", isinstance(scores.get("pain"), (int, float)))
    test("Scores has market", isinstance(scores.get("market"), (int, float)))
    test("Scores has execution", isinstance(scores.get("execution"), (int, float)))
    test("Scores has timing", isinstance(scores.get("timing"), (int, float)))

    # Gates
    gates = result.get("gates", {})
    test("Gates has build_fast", "build_fast" in gates)
    test("Gates has will_pay", "will_pay" in gates)
    test("Gates has urgent_pain", "urgent_pain" in gates)
    for gk in ("build_fast", "will_pay", "urgent_pain"):
        g = gates.get(gk, {})
        test(f"Gate {gk} has answer", g.get("answer", "").upper() in ("YES", "NO"), f"answer={g.get('answer')}")
        test(f"Gate {gk} has reasoning", isinstance(g.get("reasoning"), str) and len(g.get("reasoning", "")) > 0)
        test(f"Gate {gk} has confidence", isinstance(g.get("confidence"), (int, float)))

    # Regional scores
    regions = result.get("regional_scores", [])
    test("Has regional_scores (list)", isinstance(regions, list) and len(regions) > 0)
    if regions:
        r0 = regions[0]
        test("Region has name", isinstance(r0.get("region"), str))
        test("Region has demand", isinstance(r0.get("demand"), (int, float)))
        test("Region has reasoning", isinstance(r0.get("reasoning"), str))

    # Timing analysis
    timing = result.get("timing_analysis", {})
    test("Has timing_analysis", isinstance(timing, dict) and len(timing) > 0)
    test("Timing has readiness", timing.get("readiness") in ("NOW", "WAIT_3_MONTHS", "WAIT_6_MONTHS"), f"readiness={timing.get('readiness')}")
    test("Timing has reasoning", isinstance(timing.get("reasoning"), str))

    # Moat analysis
    moat = result.get("moat_analysis", {})
    test("Has moat_analysis", isinstance(moat, dict) and len(moat) > 0)
    test("Moat has defensibility", moat.get("defensibility") in ("LOW", "MEDIUM", "HIGH"), f"def={moat.get('defensibility')}")

    # Content
    content = result.get("content", {})
    test("Content has reddit post", isinstance(content.get("reddit"), str) and len(content.get("reddit", "")) > 0)
    test("Content has tweet", isinstance(content.get("tweet"), str) and len(content.get("tweet", "")) > 0)
    test("Content has pitch", isinstance(content.get("pitch"), str))
    test("Content has offer", isinstance(content.get("offer"), str))
    test("Content has price", isinstance(content.get("price"), str))
    test("Content has cta", isinstance(content.get("cta"), str))

    # Next steps
    steps = result.get("next_steps", [])
    test("Has next_steps (list)", isinstance(steps, list) and len(steps) >= 3, f"got {len(steps)} steps")

    # AI sources
    sources = result.get("ai_sources", [])
    test("Has ai_sources list", isinstance(sources, list) and len(sources) >= 1)
    test("Claude in ai_sources", "claude" in sources)

    # Share URL
    test("Has share_url", isinstance(result.get("share_url"), str) and "/public/idea/" in result.get("share_url", ""))

    # Research (may be None if no Perplexity key)
    research = result.get("research", {})
    test("Research field exists", research is not None)  # Can be {} if no key

    # Social buzz (may be None if no Grok key)
    buzz = result.get("social_buzz", {})
    test("Social buzz field exists", buzz is not None)

    # Business model (may be None if no GPT key)
    biz = result.get("business_model", {})
    test("Business model field exists", biz is not None)

    # Kill reason
    test("Has kill_reason field", "kill_reason" in result)

    idea_id = result.get("id")
    share_token = result.get("share_url", "").split("/")[-1] if result.get("share_url") else None
else:
    test("Result was received", False, "No result from SSE stream")
    idea_id = None
    share_token = None

# ══════════════════════════════════════════════════
#  6. DATABASE PERSISTENCE
# ══════════════════════════════════════════════════
section("6. DATABASE PERSISTENCE")

if idea_id:
    # Get single idea
    r = requests.get(f"{BASE}/api/idea/{idea_id}")
    test("GET /api/idea/{id} returns 200", r.status_code == 200)
    d = r.json()
    test("Stored idea has correct id", d.get("id") == idea_id)
    test("Stored idea has score", isinstance(d.get("score"), int))
    test("Stored idea has verdict", d.get("verdict") in ("BUILD", "SKIP", "MAYBE"))

    # List ideas
    r = requests.get(f"{BASE}/api/ideas")
    test("GET /api/ideas returns 200", r.status_code == 200)
    ideas = r.json()
    test("Ideas list is non-empty", len(ideas) > 0)
    found = any(i.get("id") == idea_id for i in ideas)
    test("Our idea appears in list", found)
    if ideas:
        i0 = ideas[0]
        test("List item has concept", "concept" in i0)
        test("List item has score", "score" in i0)
        test("List item has verdict", "verdict" in i0)
        test("List item has category", "category" in i0)
        test("List item has share_url", "share_url" in i0)

    # Stats updated
    r = requests.get(f"{BASE}/api/stats")
    d = r.json()
    test("Stats validated > 0 after analysis", d.get("validated", 0) > 0 or d.get("total_ideas", 0) > 0)

    # 404 for unknown idea
    r = requests.get(f"{BASE}/api/idea/nonexistent-id")
    test("Unknown idea returns 404", r.status_code == 404)
else:
    print("  ⚠️  Skipping DB tests — no idea_id from analysis")

# ══════════════════════════════════════════════════
#  7. SIGNAL TRACKING
# ══════════════════════════════════════════════════
section("7. SIGNAL TRACKING")

if idea_id:
    for sig_type in ("pay", "rep", "clk"):
        r = requests.post(f"{BASE}/api/signal", json={"idea_id": idea_id, "signal_type": sig_type})
        test(f"POST /api/signal ({sig_type}) returns 200", r.status_code == 200)
        d = r.json()
        test(f"Signal response has {sig_type} count", sig_type in d)

    # Verify counts incremented
    r = requests.post(f"{BASE}/api/signal", json={"idea_id": idea_id, "signal_type": "pay"})
    d = r.json()
    test("Pay signal incremented to 2", d.get("pay") == 2)

    # Invalid idea signal
    r = requests.post(f"{BASE}/api/signal", json={"idea_id": "fake-id", "signal_type": "pay"})
    test("Signal for unknown idea returns 404", r.status_code == 404)
else:
    print("  ⚠️  Skipping signal tests — no idea_id")

# ══════════════════════════════════════════════════
#  8. DECISION ENDPOINT
# ══════════════════════════════════════════════════
section("8. DECISION ENDPOINT")

if idea_id:
    r = requests.post(f"{BASE}/api/decision/{idea_id}?decision=BUILD")
    test("POST /api/decision returns 200", r.status_code == 200)
    d = r.json()
    test("Decision response has status ok", d.get("status") == "ok")
    test("Decision response has decision", d.get("decision") == "BUILD")

    # Verify persisted
    r = requests.get(f"{BASE}/api/idea/{idea_id}")
    test("Decision persisted in DB", r.json().get("verdict") == "BUILD")

    # Unknown idea
    r = requests.post(f"{BASE}/api/decision/fake-id?decision=SKIP")
    test("Decision for unknown idea returns 404", r.status_code == 404)
else:
    print("  ⚠️  Skipping decision tests — no idea_id")

# ══════════════════════════════════════════════════
#  9. PDF GENERATION
# ══════════════════════════════════════════════════
section("9. PDF GENERATION")

if idea_id:
    r = requests.get(f"{BASE}/api/idea/{idea_id}/pdf")
    test("GET /api/idea/{id}/pdf returns 200", r.status_code == 200)
    test("PDF content-type", "application/pdf" in r.headers.get("content-type", ""))
    test("PDF has content-disposition", "attachment" in r.headers.get("content-disposition", ""))
    test("PDF body is non-empty", len(r.content) > 1000, f"size={len(r.content)}")
    test("PDF starts with %PDF", r.content[:5] == b"%PDF-")

    # 404 for unknown idea
    r = requests.get(f"{BASE}/api/idea/fake-id/pdf")
    test("PDF for unknown idea returns 404", r.status_code == 404)
else:
    print("  ⚠️  Skipping PDF tests — no idea_id")

# ══════════════════════════════════════════════════
#  10. PREMIUM REPORT (Build Plan)
# ══════════════════════════════════════════════════
section("10. PREMIUM REPORT (Build Plan)")

if idea_id:
    print("  📡 Generating build plan (takes 10-30s)...")
    try:
        r = requests.get(f"{BASE}/api/idea/{idea_id}/premium-report", timeout=60)
        test("GET /api/idea/{id}/premium-report returns 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            d = r.json()
            test("Has blueprint", isinstance(d.get("blueprint"), dict))
            test("Has revenue_sim", isinstance(d.get("revenue_sim"), dict))
            test("Has mvp_plan", isinstance(d.get("mvp_plan"), dict))
            test("Has distribution_plan", isinstance(d.get("distribution_plan"), dict))

            bp = d.get("blueprint", {})
            test("Blueprint has product_name", isinstance(bp.get("product_name"), str))
            test("Blueprint has tech_stack", isinstance(bp.get("tech_stack"), list))
            test("Blueprint has mvp_features", isinstance(bp.get("mvp_features"), list))

            rev = d.get("revenue_sim", {})
            test("Revenue sim has month1", "month1" in rev or "month_1" in rev)

            mvp = d.get("mvp_plan", {})
            test("MVP plan has phases", isinstance(mvp.get("phases"), list))

            dist = d.get("distribution_plan", {})
            test("Distribution plan has channels", isinstance(dist.get("channels"), list))

            # Second call should return cached version (fast)
            t0 = time.time()
            r2 = requests.get(f"{BASE}/api/idea/{idea_id}/premium-report", timeout=10)
            t1 = time.time()
            test("Cached premium report returns 200", r2.status_code == 200)
            test("Cached call is fast (<3s)", (t1 - t0) < 3, f"took {t1-t0:.1f}s")
    except Exception as e:
        test("Premium report no errors", False, str(e))
else:
    print("  ⚠️  Skipping premium report tests — no idea_id")

# ══════════════════════════════════════════════════
#  11. LANDING PAGE GENERATION
# ══════════════════════════════════════════════════
section("11. LANDING PAGE GENERATION")

if idea_id:
    print("  📡 Generating landing page (takes 10-30s)...")
    try:
        r = requests.get(f"{BASE}/api/idea/{idea_id}/landing-page", timeout=60)
        test("GET /api/idea/{id}/landing-page returns 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            test("Landing page is HTML", "text/html" in r.headers.get("content-type", ""))
            test("Landing page has content", len(r.text) > 500, f"size={len(r.text)}")
            test("Landing page has HTML tags", "<html" in r.text.lower() or "<body" in r.text.lower() or "<div" in r.text.lower())
    except Exception as e:
        test("Landing page no errors", False, str(e))
else:
    print("  ⚠️  Skipping landing page tests — no idea_id")

# ══════════════════════════════════════════════════
#  12. TWITTER THREAD
# ══════════════════════════════════════════════════
section("12. TWITTER THREAD")

if idea_id:
    print("  📡 Generating Twitter thread (takes 5-15s)...")
    try:
        r = requests.get(f"{BASE}/api/idea/{idea_id}/twitter-thread", timeout=60)
        test("GET /api/idea/{id}/twitter-thread returns 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            d = r.json()
            test("Has thread content", isinstance(d.get("thread"), str) and len(d.get("thread", "")) > 50)
            test("Thread mentions idea_id", d.get("idea_id") == idea_id)
    except Exception as e:
        test("Twitter thread no errors", False, str(e))
else:
    print("  ⚠️  Skipping twitter thread tests — no idea_id")

# ══════════════════════════════════════════════════
#  13. PUBLIC PAGES
# ══════════════════════════════════════════════════
section("13. PUBLIC PAGES")

# Leaderboard
r = requests.get(f"{BASE}/public/leaderboard")
test("GET /public/leaderboard returns 200", r.status_code == 200)
test("Leaderboard is HTML", "text/html" in r.headers.get("content-type", ""))
test("Leaderboard has title", "Leaderboard" in r.text)
test("Leaderboard has nav", "IDEA FACTORY" in r.text)

# Graveyard
r = requests.get(f"{BASE}/public/graveyard")
test("GET /public/graveyard returns 200", r.status_code == 200)
test("Graveyard is HTML", "text/html" in r.headers.get("content-type", ""))
test("Graveyard has title", "Graveyard" in r.text)

# Public idea page
if share_token:
    r = requests.get(f"{BASE}/public/idea/{share_token}")
    test("GET /public/idea/{token} returns 200", r.status_code == 200)
    test("Public idea is HTML", "text/html" in r.headers.get("content-type", ""))
    test("Public idea has concept", result.get("concept", "XXX_MISSING") in r.text if result else True)
    test("Public idea has score", str(result.get("score", -999)) in r.text if result else True)
    test("Public idea has Download PDF link", "/pdf" in r.text)

# Invalid token
r = requests.get(f"{BASE}/public/idea/fake-token-12345")
test("Invalid share token returns 404", r.status_code == 404)

# ══════════════════════════════════════════════════
#  14. EMAIL CAPTURE
# ══════════════════════════════════════════════════
section("14. EMAIL CAPTURE")

try:
    r = requests.post(f"{BASE}/api/email/capture", json={
        "email": "test@example.com",
        "source": "e2e_test",
        "idea_id": idea_id,
        "tags": "test"
    })
    test("POST /api/email/capture returns 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        test("Email capture response", r.json().get("status") == "captured")
except Exception as e:
    test("Email capture no errors", False, str(e))

# ══════════════════════════════════════════════════
#  15. ADMIN DASHBOARD
# ══════════════════════════════════════════════════
section("15. ADMIN DASHBOARD")

# Without auth
r = requests.get(f"{BASE}/api/admin/dashboard")
test("Admin without auth returns 403", r.status_code == 403)

# With auth
r = requests.get(f"{BASE}/api/admin/dashboard", headers={"x-admin-secret": "change-me-in-production"})
test("Admin with auth returns 200", r.status_code == 200)
d = r.json()
test("Admin has total_ideas", "total_ideas" in d)
test("Admin has avg_score", "avg_score" in d)
test("Admin has top_ideas list", isinstance(d.get("top_ideas"), list))

# ══════════════════════════════════════════════════
#  16. AUTO-RANK CRON
# ══════════════════════════════════════════════════
section("16. AUTO-RANK CRON")

r = requests.post(f"{BASE}/api/cron/auto-rank", headers={"x-admin-secret": "change-me-in-production"})
test("POST /api/cron/auto-rank returns 200", r.status_code == 200)
d = r.json()
test("Auto-rank has checked count", "checked" in d)
test("Auto-rank has updated count", "updated" in d)

# Without auth
r = requests.post(f"{BASE}/api/cron/auto-rank")
test("Auto-rank without auth returns 403", r.status_code == 403)

# ══════════════════════════════════════════════════
#  17. TRENDS
# ══════════════════════════════════════════════════
section("17. TRENDS")

r = requests.get(f"{BASE}/api/trends")
test("GET /api/trends returns 200", r.status_code == 200)
d = r.json()
test("Trends has categories", isinstance(d.get("categories"), list))
test("Trends has decisions", isinstance(d.get("decisions"), list))
test("Trends has total_ideas", isinstance(d.get("total_ideas"), int))

# ══════════════════════════════════════════════════
#  18. SECOND ANALYSIS (verify multi-idea support)
# ══════════════════════════════════════════════════
section("18. SECOND IDEA ANALYSIS")

print("  📡 Submitting second idea...")
idea2 = "A mobile app that connects dog owners for group walks in their neighborhood"
events2 = []
result2 = None

try:
    r = requests.post(f"{BASE}/api/analyze", json={"idea": idea2}, stream=True, timeout=120)
    test("Second analyze returns 200", r.status_code == 200)
    buffer = ""
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        buffer += chunk
        lines = buffer.split("\n")
        buffer = lines.pop()
        for line in lines:
            if line.startswith("data: "):
                try:
                    evt = json.loads(line[6:])
                    events2.append(evt)
                    if evt.get("type") == "result":
                        result2 = evt
                        print(f"    🎯 Result: Score {evt.get('score')}, Verdict: {evt.get('verdict')}")
                except:
                    pass
except Exception as e:
    test("Second analysis no errors", False, str(e))

if result2:
    test("Second idea has different id", result2.get("id") != idea_id)
    test("Second idea has score", isinstance(result2.get("score"), int))
    test("Second idea has verdict", result2.get("verdict") in ("BUILD", "SKIP", "MAYBE"))

    # Verify both ideas in list
    r = requests.get(f"{BASE}/api/ideas")
    ideas = r.json()
    test("Ideas list has 2+ ideas", len(ideas) >= 2)
    ids = [i["id"] for i in ideas]
    test("Both ideas in list", idea_id in ids and result2["id"] in ids)

# ══════════════════════════════════════════════════
#  FINAL REPORT
# ══════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  FINAL REPORT")
print(f"{'='*60}")
print(f"\n  ✅ Passed: {PASS}")
print(f"  ❌ Failed: {FAIL}")
print(f"  📊 Total:  {PASS + FAIL}")
print(f"  🎯 Rate:   {PASS/(PASS+FAIL)*100:.1f}%\n")

if ERRORS:
    print(f"  FAILURES:")
    for e in ERRORS:
        print(f"    • {e}")
    print()

sys.exit(0 if FAIL == 0 else 1)
