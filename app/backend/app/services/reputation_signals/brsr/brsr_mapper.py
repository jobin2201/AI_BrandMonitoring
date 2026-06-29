from __future__ import annotations

from app.services.reputation_signals.brsr.brsr_rules import BRSR_RULES


BRSR_MAP = {
    keyword: principle
    for principle, keywords in BRSR_RULES.items()
    for keyword in keywords
}


SIGNAL_TO_BRSR = {
    "environmental": "Principle 6",
    "social": "Principle 3",
    "governance": "Principle 1",
    "product_success": "Principle 9",
    "product_failure": "Principle 9",
    "product_launch": "Principle 9",
    "product_review": "Principle 9",
    "product_comparison": "Principle 9",
    "product_feature": "Principle 9",
    "investment": "Principle 8",
    "withdrawal": "Principle 8",
    "regulatory_action": "Principle 1",
    "customer_complaint": "Principle 9",
    "security_incident": "Principle 9",
    "layoff": "Principle 3",
    "employee_wellbeing_risk": "Principle 3",
    "fraud_allegation": "Principle 1",
    "executive_controversy": "Principle 1",
}


def map_brsr_signal(signal: str, matched_terms: list[str] | None = None) -> dict[str, str]:
    for term in matched_terms or []:
        principle = BRSR_MAP.get(term.lower())
        if principle:
            return {"principle": principle, "matched_term": term}
    return {
        "principle": SIGNAL_TO_BRSR.get(signal, ""),
        "matched_term": "",
    }
