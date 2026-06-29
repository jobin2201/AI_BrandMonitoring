from __future__ import annotations

import re
from typing import Any


REPUTATION_CATEGORIES = {
    "product_signals": {
        "title": "Product Failures / Successes",
        "short": "Whether products are failing, succeeding, or receiving strong market feedback.",
    },
    "esg_signals": {
        "title": "ESG Issues",
        "short": "Environmental, social, and governance signals mapped to BRSR and SDGs.",
    },
    "investment_signals": {
        "title": "Investments & Withdrawals",
        "short": "Investments, expansions, divestments, exits, shutdowns, and withdrawals.",
    },
    "regulatory_signals": {
        "title": "Regulatory Actions",
        "short": "Fines, investigations, compliance issues, lawsuits, and regulatory actions.",
    },
    "customer_complaints": {
        "title": "Customer Complaints",
        "short": "Service failures, refund issues, delays, poor experience, and consumer complaints.",
    },
    "security_incidents": {
        "title": "Security Incidents",
        "short": "Data breaches, cyber attacks, leaks, ransomware, and privacy incidents.",
    },
    "layoff_signals": {
        "title": "Layoffs & Employee Well-being",
        "short": "Layoffs, delayed pay, job cuts, workforce reductions, and employee welfare risks.",
    },
    "fraud_signals": {
        "title": "Fraud Allegations",
        "short": "Fraud, corruption, bribery, money laundering, and governance misconduct allegations.",
    },
    "executive_controversies": {
        "title": "Executive Controversies",
        "short": "CEO, founder, chairman, board, and senior leadership controversies.",
    },
}


TRUSTED_PUBLISHER_WEIGHTS = {
    "reuters": 1.0,
    "bloomberg": 1.0,
    "wall street journal": 1.0,
    "wsj": 1.0,
    "financial times": 1.0,
    "associated press": 0.96,
    "ap news": 0.96,
    "bbc": 0.94,
    "cnbc": 0.94,
    "the hindu": 0.92,
    "indian express": 0.92,
    "economic times": 0.9,
    "business standard": 0.9,
    "livemint": 0.88,
    "techcrunch": 0.88,
    "securityweek": 0.88,
    "recorded future": 0.88,
}

SOURCE_TYPE_WEIGHTS = {
    "google_news": 0.82,
    "newsapi": 0.8,
    "reddit": 0.6,
    "youtube": 0.42,
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def text_for_item(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "")
        for field in ["title", "body_text", "description", "snippet", "source_name"]
    ).strip()


def evidence_card(item: dict[str, Any], signal: str, confidence: float, reason: str, extra: dict | None = None) -> dict:
    text = text_for_item(item)
    source_weight = source_weight_for_item(item)
    return {
        "signal": signal,
        "title": item.get("title") or text[:120],
        "source": item.get("source") or "",
        "source_name": item.get("source_name") or "",
        "url": item.get("url") or "",
        "published_at": item.get("published_at") or "",
        "snippet": text[:260],
        "confidence": round(confidence, 3),
        "source_weight": source_weight,
        "reason": reason,
        **(extra or {}),
    }


def contains_any(text: str, terms: list[str]) -> tuple[bool, str]:
    normalized = f" {normalize(text)} "
    for term in terms:
        clean = normalize(term)
        if clean and f" {clean} " in normalized:
            return True, term
    return False, ""


def dedupe_items(items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("url") or normalize(item.get("title") or item.get("snippet") or "")
        if not key:
            continue
        current = best_by_key.get(key)
        if current is None or _rank_tuple(item) > _rank_tuple(current):
            best_by_key[key] = item
    return rank_evidence_items(list(best_by_key.values()))[:limit]


def source_weight_for_item(item: dict[str, Any]) -> float:
    source_name = normalize(str(item.get("source_name") or item.get("publisher") or item.get("channel") or ""))
    for publisher, weight in TRUSTED_PUBLISHER_WEIGHTS.items():
        if normalize(publisher) in source_name:
            return weight
    source = normalize(str(item.get("source") or item.get("platform") or ""))
    return SOURCE_TYPE_WEIGHTS.get(source, 0.7)


def _rank_tuple(item: dict[str, Any]) -> tuple[float, float]:
    return (
        float(item.get("source_weight") or source_weight_for_item(item)),
        float(item.get("confidence") or 0.0),
    )


def rank_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=_rank_tuple, reverse=True)


def _incident_group_key(item: dict[str, Any]) -> str:
    signal = normalize(str(item.get("signal") or ""))
    text = normalize(" ".join([
        str(item.get("title") or ""),
        str(item.get("snippet") or ""),
        " ".join(str(term) for term in item.get("matched_terms") or []),
    ]))
    incident_groups = [
        ("security_incident", ["data breach", "breach", "hack", "data leak", "cyber incident", "ransomware"]),
        ("employee_wellbeing_risk", ["layoff", "job cuts", "workforce reduction", "salary delay", "unpaid wages"]),
        ("regulatory_signal", ["lawsuit", "fine", "penalty", "investigation", "antitrust", "regulatory action"]),
        ("customer_complaint", ["complaint", "refund", "poor service", "worst experience", "delay"]),
        ("fraud_allegation", ["fraud", "scam", "bribery", "corruption", "money laundering"]),
        ("executive_controversy", ["ceo", "chairman", "founder", "board", "executive", "leadership"]),
    ]
    for group_signal, terms in incident_groups:
        if signal == group_signal:
            for term in terms:
                if normalize(term) in text:
                    return f"{group_signal}:{normalize(term)}"
    return f"{signal}:{normalize(str(item.get('title') or item.get('snippet') or ''))[:80]}"


def group_incident_items(items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in rank_evidence_items(items):
        key = _incident_group_key(item)
        existing = grouped.get(key)
        source_label = " - ".join(
            part for part in [item.get("source") or "", item.get("source_name") or ""] if part
        )
        if existing is None:
            grouped[key] = {
                **item,
                "evidence_sources": [source_label] if source_label else [],
                "source_count": 1,
            }
            continue
        if source_label and source_label not in existing.get("evidence_sources", []):
            existing.setdefault("evidence_sources", []).append(source_label)
        existing["source_count"] = len(existing.get("evidence_sources") or [])
        existing["confidence"] = round(max(
            float(existing.get("confidence") or 0.0),
            float(item.get("confidence") or 0.0),
        ), 3)
        existing["source_weight"] = max(
            float(existing.get("source_weight") or 0.0),
            float(item.get("source_weight") or 0.0),
        )
    return rank_evidence_items(list(grouped.values()))[:limit]
