"""
Scoring — Deterministic scoring model.
No reliance on Claude confidence or Claude final_decision.
"""


def _clamp(value: int | float, lo: int = 0, hi: int = 100) -> int:
    """Clamp a value between lo and hi."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    return max(lo, min(hi, v))


def calculate_deterministic_score(analysis: dict) -> int:
    """
    Calculate a deterministic score from analysis fields.
    Formula:
        score = (pain * 0.25) + (market * 0.20) + (execution * 0.20)
              + (distribution * 0.15) + (feasibility * 0.20)
    All values clamped 0-100.
    """
    pain = _clamp(analysis.get("pain_score", 0))
    market = _clamp(analysis.get("market_score", 0))
    execution = _clamp(analysis.get("execution_score", 0))
    distribution = _clamp(analysis.get("distribution_score", 0))
    feasibility = _clamp(analysis.get("feasibility_score", 0))

    score = (
        pain * 0.25
        + market * 0.20
        + execution * 0.20
        + distribution * 0.15
        + feasibility * 0.20
    )

    return _clamp(round(score))
