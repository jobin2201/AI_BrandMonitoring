from __future__ import annotations

from typing import Any

from app.services.bw_workspace.reputation_category_mapper import REPUTATION_SECTION_KEYS


NEGATIVE_WEIGHTS = {
    "fraud_signals": 18,
    "security_incidents": 16,
    "regulatory_signals": 14,
    "layoff_signals": 12,
    "executive_controversies": 11,
    "customer_complaints": 8,
}

POSITIVE_WEIGHTS = {
    "investment_signals": 6,
    "esg_signals": 5,
    "product_signals": 3,
}


def calculate_reputation_health(reputation: dict[str, Any]) -> dict[str, Any]:
    negative_points = 0.0
    positive_points = 0.0
    risks: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}

    for key in REPUTATION_SECTION_KEYS:
        items = reputation.get(key, {}).get("items") or []
        related = reputation.get(key, {}).get("related_mentions") or []
        category_counts[key] = len(items) + len(related)
        for item in items:
            confidence = float(item.get("bw_confidence") or item.get("confidence") or 0)
            risk = float(item.get("bw_risk") or 0)
            if key in NEGATIVE_WEIGHTS:
                negative_points += NEGATIVE_WEIGHTS[key] * max(confidence, 0.4)
                risks.append({
                    "category": key,
                    "title": item.get("title") or item.get("signal") or "",
                    "risk": risk,
                    "confidence": confidence,
                })
            elif key in POSITIVE_WEIGHTS:
                positive_points += POSITIVE_WEIGHTS[key] * max(confidence, 0.4)

    score = max(0, min(100, round(82 + positive_points - negative_points)))
    label = "Healthy"
    if score < 45:
        label = "Critical"
    elif score < 65:
        label = "Watch"
    elif score < 80:
        label = "Stable"

    top_category = max(category_counts.items(), key=lambda item: item[1], default=("", 0))
    highest_risk = sorted(risks, key=lambda item: item["risk"], reverse=True)[:1]
    return {
        "score": score,
        "label": label,
        "verified_signals": sum(len(reputation.get(key, {}).get("items") or []) for key in REPUTATION_SECTION_KEYS),
        "related_mentions": sum(len(reputation.get(key, {}).get("related_mentions") or []) for key in REPUTATION_SECTION_KEYS),
        "top_category": top_category[0],
        "top_category_count": top_category[1],
        "highest_risk": highest_risk[0] if highest_risk else {},
        "positive_points": round(positive_points, 2),
        "negative_points": round(negative_points, 2),
    }


def calculate_crisis_score(reputation: dict[str, Any]) -> dict[str, Any]:
    crisis_categories = [
        "fraud_signals",
        "security_incidents",
        "regulatory_signals",
        "layoff_signals",
        "executive_controversies",
        "customer_complaints",
    ]
    risk = 0.0
    contributors = []
    for key in crisis_categories:
        for item in reputation.get(key, {}).get("items") or []:
            item_risk = float(item.get("bw_risk") or 0)
            risk += item_risk
            contributors.append({
                "category": key,
                "title": item.get("title") or item.get("signal") or "",
                "risk": item_risk,
            })
    score = max(0, min(100, round(risk * 12)))
    return {
        "score": score,
        "label": "High" if score >= 70 else "Medium" if score >= 40 else "Low",
        "contributors": sorted(contributors, key=lambda item: item["risk"], reverse=True)[:5],
    }
