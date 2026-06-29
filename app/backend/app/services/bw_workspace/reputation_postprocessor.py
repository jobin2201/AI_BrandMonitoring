from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from app.services.bw_workspace.reputation_category_mapper import (
    REPUTATION_SECTION_KEYS,
    choose_best_category,
    evidence_identity,
)


def _empty_like(section: dict[str, Any] | None) -> dict[str, Any]:
    section = section or {}
    return {
        **section,
        "items": [],
        "related_mentions": [],
        "count": 0,
    }


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.65:
        return "medium"
    return "low"


def _source_quality(item: dict[str, Any]) -> float:
    if item.get("source_weight") is not None:
        try:
            return max(0.0, min(1.0, float(item.get("source_weight") or 0)))
        except (TypeError, ValueError):
            return 0.5
    source = str(item.get("source") or "").casefold()
    if source in {"newsapi", "google_news"}:
        return 0.8
    if source == "reddit":
        return 0.6
    if source == "youtube":
        return 0.45
    return 0.5


def _recency_score(item: dict[str, Any]) -> float:
    value = item.get("published_at") or item.get("date") or ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    days = max(0, (datetime.now(timezone.utc) - parsed).days)
    if days <= 30:
        return 1.0
    if days <= 180:
        return 0.75
    if days <= 365:
        return 0.5
    return 0.25


def _normalized_confidence(item: dict[str, Any], category_score: int, verified_min: int) -> float:
    try:
        classifier = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        classifier = 0.0
    if classifier > 1:
        classifier = classifier / 100
    evidence = min(1.0, category_score / max(1, verified_min))
    source = _source_quality(item)
    recency = _recency_score(item)
    return round((classifier * 0.45) + (evidence * 0.3) + (source * 0.15) + (recency * 0.1), 4)


def _risk_score(item: dict[str, Any], assignment: dict[str, Any], bw_confidence: float) -> float:
    severity = float(assignment.get("severity") or 1)
    return round(severity * bw_confidence * _recency_score(item), 4)


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    kept = []
    for item in items:
        key = evidence_identity(item)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def postprocess_reputation(raw: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(raw or {})
    for key in REPUTATION_SECTION_KEYS:
        result[key] = _empty_like(result.get(key))

    evidence_by_id: dict[str, dict[str, Any]] = {}
    category_debug: dict[str, dict[str, int]] = {
        key: {
            "raw_verified": 0,
            "raw_related": 0,
            "verified": 0,
            "related": 0,
            "rejected": 0,
        }
        for key in REPUTATION_SECTION_KEYS
    }
    for key in REPUTATION_SECTION_KEYS:
        section = raw.get(key) or {}
        for source_name in ("items", "related_mentions"):
            was_verified = source_name == "items"
            for item in section.get(source_name) or []:
                if not isinstance(item, dict):
                    continue
                if was_verified:
                    category_debug[key]["raw_verified"] += 1
                else:
                    category_debug[key]["raw_related"] += 1
                identity = evidence_identity(item)
                if not identity:
                    continue
                current = evidence_by_id.get(identity)
                current_confidence = float((current or {}).get("confidence") or 0)
                item_confidence = float(item.get("confidence") or 0)
                if current is None or item_confidence >= current_confidence:
                    evidence_by_id[identity] = {
                        **item,
                        "_was_verified": bool(was_verified or (current or {}).get("_was_verified")),
                        "_source_sections": sorted(set(
                            list((current or {}).get("_source_sections") or [])
                            + [key]
                        )),
                    }
                elif current is not None:
                    current["_was_verified"] = bool(current.get("_was_verified") or was_verified)
                    current["_source_sections"] = sorted(set(
                        list(current.get("_source_sections") or [])
                        + [key]
                    ))

    rejected = []
    for item in evidence_by_id.values():
        assignment = choose_best_category(item)
        if not assignment:
            fallback_section = next(
                (
                    key
                    for key in item.get("_source_sections") or []
                    if key in REPUTATION_SECTION_KEYS
                ),
                "",
            )
            if fallback_section:
                related = {
                    **item,
                    "bw_category": fallback_section,
                    "bw_category_score": 0,
                    "bw_matched_terms": [],
                    "bw_confidence": _normalized_confidence(item, 0, 1),
                    "bw_confidence_label": "low",
                    "bw_risk": 0.0,
                    "bw_reason": "Related mention from the existing Reputation Signals engine; category evidence was below BW verification threshold.",
                }
                result[fallback_section]["related_mentions"].append(related)
                category_debug[fallback_section]["related"] += 1
                continue
            rejected.append({
                "title": item.get("title") or item.get("signal") or "",
                "url": item.get("url") or "",
                "reason": "no_category_specific_evidence",
                "source_sections": item.get("_source_sections") or [],
            })
            for key in item.get("_source_sections") or []:
                if key in category_debug:
                    category_debug[key]["rejected"] += 1
            continue

        bw_confidence = _normalized_confidence(
            item,
            int(assignment["score"]),
            int(assignment["verified_min"]),
        )
        enriched = {
            **item,
            "bw_category": assignment["section"],
            "bw_category_score": assignment["score"],
            "bw_matched_terms": assignment["matched_terms"],
            "bw_confidence": bw_confidence,
            "bw_confidence_label": _confidence_label(bw_confidence),
            "bw_risk": _risk_score(item, assignment, bw_confidence),
            "bw_reason": (
                "Category evidence: "
                + (", ".join(assignment["matched_terms"]) if assignment["matched_terms"] else "signal metadata")
            ),
        }
        verified = (
            bool(item.get("_was_verified"))
            and bw_confidence >= 0.65
            and int(assignment["score"]) >= int(assignment["verified_min"])
        )
        target = result[assignment["section"]]["items" if verified else "related_mentions"]
        target.append(enriched)
        category_debug[assignment["section"]]["verified" if verified else "related"] += 1

    for key in REPUTATION_SECTION_KEYS:
        section = result[key]
        section["items"] = sorted(
            _dedupe(section.get("items") or []),
            key=lambda item: (float(item.get("bw_risk") or 0), float(item.get("bw_confidence") or 0)),
            reverse=True,
        )
        section["related_mentions"] = sorted(
            _dedupe(section.get("related_mentions") or []),
            key=lambda item: (float(item.get("bw_category_score") or 0), float(item.get("bw_confidence") or 0)),
            reverse=True,
        )
        section["count"] = len(section["items"])

    result["bw_postprocessing"] = {
        "input_articles": len(evidence_by_id),
        "rejected_articles": len(rejected),
        "rejection_samples": rejected[:10],
        "category_debug": category_debug,
        "mode": "bw_orchestration_over_existing_reputation_engine",
    }
    return result
