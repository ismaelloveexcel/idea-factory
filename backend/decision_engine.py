"""
Decision Engine — Final deterministic decision logic.
LLMs NEVER decide. All decisions come from rules.
"""


def compute_final_decision(score: int, kill_result: dict | None) -> str:
    """
    Compute the final decision based on score and kill rules.
    Returns: "KILL", "MAYBE", or "BUILD"
    """
    if kill_result:
        return "KILL"

    if score >= 70:
        return "BUILD"

    if score >= 50:
        return "MAYBE"

    return "KILL"
