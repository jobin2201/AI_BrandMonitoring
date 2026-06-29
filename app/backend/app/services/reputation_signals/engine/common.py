from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any

from app.services.reputation_signals.reputation_common import REPUTATION_CATEGORIES
from app.services.reputation_signals.observability.logger import write_reputation_log
from app.services.competitor_intelligence.intelligence_common import normalize


DEFAULT_RESULTS_PER_SOURCE = 3
DEFAULT_CATEGORY_EVIDENCE_LIMIT = 12
DEFAULT_REPUTATION_SOURCE_WORKERS = 3
DEFAULT_REPUTATION_QUERY_WORKERS = 1
DEFAULT_REPUTATION_CATEGORY_WORKERS = 3
REPUTATION_SOURCES_BY_CATEGORY = {
    "product": {"google_news", "newsapi"},
    "esg": {"google_news", "newsapi"},
    "investments": {"google_news", "newsapi"},
    "regulatory": {"google_news", "newsapi"},
    "complaints": {"google_news", "reddit"},
    "security": {"google_news", "newsapi"},
    "layoffs": {"google_news", "newsapi"},
    "fraud": {"google_news", "newsapi"},
    "executive": {"google_news", "newsapi", "youtube"},
}
_NEWSAPI_DISABLED_UNTIL = 0.0
_BRAND_INTELLIGENCE_CACHE: dict[str, dict[str, Any]] = {}


def get_newsapi_disabled_until() -> float:
    return _NEWSAPI_DISABLED_UNTIL


def set_newsapi_disabled_until(value: float) -> None:
    global _NEWSAPI_DISABLED_UNTIL
    _NEWSAPI_DISABLED_UNTIL = value

def _empty_section(title: str, summary: str) -> dict[str, Any]:
    return {
        "title": title,
        "items": [],
        "count": 0,
        "summary": summary,
    }


def _empty_reputation_result(
    brand_id: str,
    brand: dict[str, Any] | None,
    error: str = "",
    traceback_text: str = "",
) -> dict[str, Any]:
    brand_name = (brand or {}).get("brand_name") or ""
    error_log = ""
    if error:
        error_log = write_reputation_log("errors", brand_id, {
            "stage": "temporary_reputation_error",
            "brand": brand_name,
            "error": error,
            "traceback": traceback_text,
        })
    return {
        "temporary": True,
        "stored": False,
        "brand_id": brand_id,
        "brand": brand_name,
        "competitor": "",
        "analysis_target": "active_brand",
        "descriptions": REPUTATION_CATEGORIES,
        "product_signals": _empty_section("Product Failures / Successes", "No product signals returned."),
        "esg_signals": _empty_section("ESG Issues", "No ESG signals returned."),
        "investment_signals": _empty_section("Investments & Withdrawals", "No investment signals returned."),
        "regulatory_signals": _empty_section("Regulatory Actions", "No regulatory signals returned."),
        "customer_complaints": _empty_section("Customer Complaints", "No customer complaint signals returned."),
        "security_incidents": _empty_section("Security Incidents", "No security incident signals returned."),
        "layoff_signals": _empty_section("Layoffs & Employee Well-being", "No layoff or employee well-being signals returned."),
        "fraud_signals": _empty_section("Fraud Allegations", "No fraud signals returned."),
        "executive_controversies": _empty_section("Executive Controversies", "No executive controversy signals returned."),
        "retrieval_summary": {"enabled": False, "error": error},
        "error": error,
        "error_log": error_log,
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [value]


def _unique_strings(*values: Any) -> list[str]:
    seen = set()
    unique: list[str] = []
    for value in values:
        for item in _as_list(value):
            text = str(item or "").strip()
            if not text:
                continue
            key = normalize(text)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(text)
    return unique
