"""
Kill Rules — Pre-scoring hard kill logic.
Runs BEFORE scoring to immediately reject weak ideas.
"""


def apply_kill_rules(analysis: dict, constraints: dict, research: dict | None) -> dict | None:
    """
    Apply hard kill rules. Returns a kill dict if idea should be killed,
    or None if idea passes all rules.
    """
    # Rule 1: Any gate answer == "NO"
    for gate_key in ("gate1", "gate2", "gate3"):
        gate = analysis.get(gate_key, {})
        answer = (gate.get("answer") or "").upper().strip()
        if answer == "NO":
            question = gate.get("question", gate_key)
            return {
                "decision": "KILL",
                "reason": f"Gate failed: {question} — answer was NO",
            }

    # Rule 2: reachable_people is empty
    reachable = constraints.get("reachable_people", [])
    if not reachable:
        return {
            "decision": "KILL",
            "reason": "No reachable people specified — cannot validate demand",
        }

    # Rule 3: estimated build time > available_hours
    try:
        build_time = float(analysis.get("build_time_hours", 0) or 0)
    except (TypeError, ValueError):
        build_time = 0
    try:
        available = float(constraints.get("available_hours", 0) or 0)
    except (TypeError, ValueError):
        available = 0
    if build_time > 0 and available > 0 and build_time > available:
        return {
            "decision": "KILL",
            "reason": f"Build time ({build_time}h) exceeds available hours ({available}h)",
        }

    # Rule 4: no distribution channel in constraints
    channels = constraints.get("channels", [])
    if not channels:
        return {
            "decision": "KILL",
            "reason": "No distribution channels specified — no way to reach users",
        }

    # Rule 5: no evidence provided for gates
    for gate_key in ("gate1", "gate2", "gate3"):
        gate = analysis.get(gate_key, {})
        evidence = (gate.get("evidence") or "").strip()
        if not evidence:
            question = gate.get("question", gate_key)
            return {
                "decision": "KILL",
                "reason": f"No evidence provided for gate: {question}",
            }

    # Rule 6: research data is empty when Perplexity was supposed to provide it
    if research is not None and not research:
        return {
            "decision": "KILL",
            "reason": "Research returned empty data — cannot validate market",
        }

    return None
