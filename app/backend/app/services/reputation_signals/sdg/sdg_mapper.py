from __future__ import annotations

from typing import Any

from app.services.reputation_signals.sdg.sdg_rules import SDG_RULES


SDG_MAP = {
    keyword: [rule["code"]]
    for rule in SDG_RULES
    for keyword in rule["keywords"]
}


def all_sdg_keywords() -> list[str]:
    return [keyword for rule in SDG_RULES for keyword in rule["keywords"]]


def sdg_rules_by_keyword() -> dict[str, dict[str, Any]]:
    return {
        keyword.lower(): rule
        for rule in SDG_RULES
        for keyword in rule["keywords"]
    }


SIGNAL_TO_DEFAULT_SDGS = {
    "environmental": ["SDG13"],
    "social": ["SDG8"],
    "governance": ["SDG16"],
    "product_success": ["SDG9", "SDG12"],
    "product_failure": ["SDG12"],
    "product_launch": ["SDG9", "SDG12"],
    "product_review": ["SDG12"],
    "product_comparison": ["SDG12"],
    "product_feature": ["SDG9", "SDG12"],
    "investment": ["SDG8", "SDG9"],
    "withdrawal": ["SDG8"],
    "regulatory_action": ["SDG16"],
    "customer_complaint": ["SDG12"],
    "security_incident": ["SDG16"],
    "layoff": ["SDG8"],
    "employee_wellbeing_risk": ["SDG8"],
    "fraud_allegation": ["SDG16"],
    "executive_controversy": ["SDG16"],
}


def map_sdg_terms(matched_terms: list[str] | None = None, signal: str = "") -> list[dict[str, Any]]:
    rules_by_keyword = sdg_rules_by_keyword()
    output = []
    seen = set()
    for term in matched_terms or []:
        rule = rules_by_keyword.get(term.lower())
        if not rule or rule["code"] in seen:
            continue
        seen.add(rule["code"])
        output.append({
            "code": rule["code"],
            "name": rule["name"],
            "pillar": rule["pillar"],
            "matched_terms": [term],
        })

    if output:
        return output

    default_codes = SIGNAL_TO_DEFAULT_SDGS.get(signal, [])
    for rule in SDG_RULES:
        if rule["code"] not in default_codes or rule["code"] in seen:
            continue
        seen.add(rule["code"])
        output.append({
            "code": rule["code"],
            "name": rule["name"],
            "pillar": rule["pillar"],
            "matched_terms": [],
        })
    return output
