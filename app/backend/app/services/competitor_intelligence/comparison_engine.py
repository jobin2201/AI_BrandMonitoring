from __future__ import annotations

import ast
import json
import os
import re
import time
from typing import Any

from dotenv import load_dotenv

from app.services.competitor_intelligence.competitor_logger import (
    append_competitor_log,
    write_competitor_log,
)
from app.services.competitor_intelligence.competitor_detector import load_brand_context
from app.services.competitor_intelligence.insight_extractor import extract_brand_insights
from app.services.competitor_intelligence.intelligence_common import enrich_competitor_profile

load_dotenv(os.path.join(os.path.dirname(__file__), "../../../.env"))


def parse_json_object(text: str) -> dict:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(raw[index:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue

        snippets = [raw]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            snippets.insert(0, match.group(0))
        for snippet in snippets:
            try:
                obj = ast.literal_eval(snippet)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        raise json.JSONDecodeError("No valid JSON object found", raw, 0)


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def build_competitor_profile(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        payload = {"competitor_name": payload}

    competitor_name = (
        payload.get("competitor_name")
        or payload.get("competitor")
        or payload.get("name")
        or ""
    ).strip()
    if not competitor_name:
        raise ValueError("competitor_name is required")

    return {
        "competitor_name": competitor_name,
        "product_names": normalize_list(payload.get("product_names")),
        "service_names": normalize_list(payload.get("service_names")),
        "ceo_names": normalize_list(payload.get("ceo_names")),
        "executive_names": normalize_list(payload.get("executive_names")),
        "campaign_names": normalize_list(payload.get("campaign_names")),
        "hashtags": normalize_list(payload.get("hashtags")),
        "competitor_keywords": normalize_list(payload.get("competitor_keywords")),
    }


def list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def sanitize_recommendations(recommendations: Any, competitor_name: str) -> tuple[list[str], list[str]]:
    competitor = (competitor_name or "").lower()
    blocked = []
    cleaned = []
    for recommendation in list_value(recommendations):
        lower = recommendation.lower()
        invalid = False
        if competitor:
            invalid_patterns = [
                f"partner with {competitor}",
                f"partnership with {competitor}",
                f"collaborate with {competitor}",
                f"collaboration with {competitor}",
                f"team up with {competitor}",
            ]
            invalid = any(pattern in lower for pattern in invalid_patterns)
        if invalid:
            blocked.append(recommendation)
            continue
        cleaned.append(recommendation)

    if not cleaned:
        cleaned.append(
            "Focus on category-specific differentiation using the strongest positive mention themes."
        )
    return cleaned, blocked


def sanitize_swot_result(
    result: dict[str, Any],
    competitor_profile: dict[str, Any],
    evidence_basis: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    competitor_name = competitor_profile.get("competitor_name") or ""
    recommendations, blocked_recommendations = sanitize_recommendations(
        result.get("recommendations") or result.get("recommendation") or [],
        competitor_name,
    )

    cleaned = {
        **result,
        "summary": str(result.get("summary") or result.get("comparison_summary") or ""),
        "strengths": list_value(result.get("strengths")),
        "weaknesses": list_value(result.get("weaknesses")),
        "opportunities": list_value(result.get("opportunities")),
        "threats": list_value(result.get("threats")),
        "recommendations": recommendations,
        "evidence_basis": evidence_basis or result.get("evidence_basis") or {},
    }
    try:
        cleaned["confidence"] = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        cleaned["confidence"] = 0.0

    validation = {
        "blocked_recommendations": blocked_recommendations,
        "has_summary": bool(cleaned["summary"]),
        "strength_count": len(cleaned["strengths"]),
        "weakness_count": len(cleaned["weaknesses"]),
        "opportunity_count": len(cleaned["opportunities"]),
        "threat_count": len(cleaned["threats"]),
        "recommendation_count": len(cleaned["recommendations"]),
        "has_evidence_basis": bool(cleaned["evidence_basis"]),
    }
    return cleaned, validation


def build_evidence_basis(brand_insights: dict[str, Any]) -> dict[str, Any]:
    return {
        "mention_count": brand_insights.get("mention_count") or 0,
        "strength_topics": (brand_insights.get("strength_topics") or [])[:8],
        "weakness_topics": (brand_insights.get("weakness_topics") or [])[:8],
        "common_topics": (brand_insights.get("common_topics") or [])[:8],
        "positive_examples": (brand_insights.get("positive_examples") or [])[:5],
        "negative_examples": (brand_insights.get("negative_examples") or [])[:5],
        "sentiment_distribution": brand_insights.get("sentiment_distribution") or {},
        "source_counts": brand_insights.get("source_counts") or {},
    }


def groq_generate_swot(
    brand: dict[str, Any],
    competitor_profile: dict[str, Any],
    brand_insights: dict,
) -> dict:
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing")

    client = Groq(api_key=api_key)
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    evidence_basis = build_evidence_basis(brand_insights)
    prompt = f"""
Compare the monitored brand against the temporary competitor profile.
Do not assume competitor data is stored in a database.

Brand from monitored_brands:
{json.dumps(brand, indent=2, default=str)}

Brand mention insights:
{json.dumps(brand_insights, indent=2, default=str)}

Evidence basis that MUST anchor every claim:
{json.dumps(evidence_basis, indent=2, default=str)}

Temporary competitor profile from request:
{json.dumps(competitor_profile, indent=2, default=str)}

Generate a practical SWOT-style competitor analysis.
Use the mention insights when available:
- strengths should come from strength_topics and positive_examples
- weaknesses should come from weakness_topics and negative_examples
- opportunities should be category/product/positioning specific
- threats should relate to the competitor profile, not generic services filler
- avoid generic advice like "introduce more services" unless the brand is actually a service business

Hard rules:
- Return strict JSON only. No markdown, no prose outside JSON, no Python dicts.
- Treat the evidence basis as the source of truth. If evidence is missing, say the signal is limited.
- Do not claim weak online presence, strong online presence, pricing power, product superiority, or market share unless the evidence basis explicitly supports it.
- Each strength and weakness must include a short evidence phrase such as "seen in X mentions", "positive example", "negative example", or "limited evidence".
- Never recommend partnerships, collaborations, or joint campaigns with this direct competitor.
- Do not fabricate competitor facts that are not present in the temporary competitor profile.
- Recommendations must be realistic actions for product, positioning, pricing, content, customer experience, or category messaging.
- Every recommendation should be connected to a listed strength, weakness, opportunity, threat, or mention topic.
- Do not output generic filler such as "improve marketing" unless tied to a specific topic from the inputs.

Return ONLY valid JSON:
{{
  "summary": "short executive summary",
  "strengths": ["brand strengths compared with competitor"],
  "weaknesses": ["brand weaknesses compared with competitor"],
  "opportunities": ["opportunities for the brand"],
  "threats": ["threats from the competitor"],
  "recommendations": ["specific recommended actions"],
  "evidence_basis": {{
    "used_strength_topics": [],
    "used_weakness_topics": [],
    "used_examples": []
  }},
  "confidence": 0.0
}}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw_response = response.choices[0].message.content or ""
    write_competitor_log("prompts", brand["brand_id"], {
        "stage": "swot",
        "model": model,
        "prompt": prompt,
        "raw_response": raw_response,
    })
    return parse_json_object(raw_response)


def fallback_swot(brand: dict[str, Any], competitor_profile: dict[str, Any], error: str = "") -> dict:
    brand_name = brand.get("brand_name") or "Brand"
    competitor_name = competitor_profile.get("competitor_name") or "Competitor"
    category = (
        brand.get("competitor_category")
        or brand.get("primary_category")
        or brand.get("subcategory")
        or brand.get("industry")
        or "the same market"
    )
    return {
        "summary": (
            f"{brand_name} and {competitor_name} appear to compete around {category}. "
            "This is a fallback SWOT because live LLM generation was unavailable."
        ),
        "strengths": [
            f"{brand_name} already has monitored mention data available for analysis.",
            "Existing brand context can be reused for focused comparison.",
        ],
        "weaknesses": [
            f"Competitor-side evidence for {competitor_name} was provided only as a temporary profile.",
            "A live LLM response was not available for deeper reasoning.",
        ],
        "opportunities": [
            f"Collect more competitor keywords, products, campaigns, and hashtags for {competitor_name}.",
            "Compare sentiment and source-level visibility after more monitored mentions are available.",
        ],
        "threats": [
            f"{competitor_name} may own stronger category-specific messaging in {category}.",
            "Limited competitor evidence can hide emerging threats.",
        ],
        "recommendations": [
            "Add richer competitor profile inputs and regenerate the SWOT.",
        ],
        "confidence": 0.35,
        "fallback": True,
        "error": error,
    }


def compare_with_competitor(brand_id: str, competitor_payload: dict[str, Any] | str) -> dict:
    started = time.perf_counter()
    trace_steps = []

    step_started = time.perf_counter()
    brand = load_brand_context(brand_id)
    trace_steps.append({
        "step": "load_brand_context",
        "status": "success",
        "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
    })

    step_started = time.perf_counter()
    competitor_profile = enrich_competitor_profile(build_competitor_profile(competitor_payload))
    profile_log = write_competitor_log("profiles", brand_id, {
        "stage": "temporary_competitor_profile",
        "profile": competitor_profile,
        "validation": {
            "has_competitor_name": bool(competitor_profile.get("competitor_name")),
            "has_products": bool(competitor_profile.get("product_names")),
            "has_keywords": bool(competitor_profile.get("competitor_keywords")),
        },
    })
    trace_steps.append({
        "step": "build_competitor_profile",
        "status": "success",
        "path": profile_log,
        "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
    })

    step_started = time.perf_counter()
    brand_insights = extract_brand_insights(brand_id)
    trace_steps.append({
        "step": "extract_brand_insights",
        "status": "success",
        "mention_count": brand_insights.get("mention_count"),
        "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
    })

    try:
        step_started = time.perf_counter()
        result = groq_generate_swot(brand, competitor_profile, brand_insights)
        trace_steps.append({
            "step": "groq_generate_swot",
            "status": "success",
            "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
        })
    except Exception as exc:
        print(f"[COMPETITOR] Groq SWOT failed; using fallback SWOT: {exc}")
        write_competitor_log("fallbacks", brand_id, {
            "stage": "swot",
            "reason": str(exc),
            "brand": brand,
            "competitor_profile": competitor_profile,
        })
        result = fallback_swot(brand, competitor_profile, error=str(exc))
        trace_steps.append({
            "step": "fallback_swot",
            "status": "success",
            "error": str(exc),
        })

    evidence_basis = build_evidence_basis(brand_insights)
    result, swot_validation = sanitize_swot_result(result, competitor_profile, evidence_basis)
    write_competitor_log("validation", brand_id, {
        "stage": "swot",
        "competitor": competitor_profile.get("competitor_name"),
        "validation": swot_validation,
    })

    recommendations = result.get("recommendations") or []

    response = {
        "brand": brand.get("brand_name"),
        "brand_id": brand_id,
        "competitor": competitor_profile["competitor_name"],
        "competitor_profile": competitor_profile,
        "summary": result.get("summary") or result.get("comparison_summary") or "",
        "comparison_summary": result.get("summary") or result.get("comparison_summary") or "",
        "strengths": result.get("strengths") or [],
        "weaknesses": result.get("weaknesses") or [],
        "opportunities": result.get("opportunities") or [],
        "threats": result.get("threats") or [],
        "recommendations": recommendations,
        "recommendation": recommendations[0] if recommendations else "",
        "evidence_basis": result.get("evidence_basis") or evidence_basis,
        "confidence": float(result.get("confidence") or 0.0),
        "fallback": bool(result.get("fallback")),
        "error": result.get("error") or "",
        "stored": False,
    }
    log_path = write_competitor_log("swot", brand_id, {
        "brand": brand,
        "competitor_profile": competitor_profile,
        "brand_insights": brand_insights,
        "response": response,
    })
    trace_steps.append({
        "step": "write_swot_log",
        "status": "success",
        "path": log_path,
    })
    write_competitor_log("traces", brand_id, {
        "stage": "swot",
        "status": "success",
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "steps": trace_steps,
    })
    append_competitor_log("swot_complete", {
        "brand_id": brand_id,
        "competitor": competitor_profile.get("competitor_name"),
        "fallback": response.get("fallback"),
    })
    print(f"[COMPETITOR] SWOT log -> {log_path}")
    return response
