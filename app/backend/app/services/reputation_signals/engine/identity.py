from __future__ import annotations

import copy
import json
import os
import time
import traceback
from datetime import datetime
from typing import Any

from app.services.competitor_intelligence.competitor_detector import load_brand_context, parse_json_object
from app.services.competitor_intelligence.intelligence_common import looks_like_product_name, normalize
from app.services.entity_resolution.resolver_manager import resolve_brand
from app.services.reputation_signals.engine.analysis import run_reputation_analysis
from app.services.reputation_signals.engine.common import (
    _BRAND_INTELLIGENCE_CACHE,
    _as_list,
    _empty_reputation_result,
    _unique_strings,
)
from app.services.reputation_signals.observability.logger import write_reputation_log

def _brand_profile(brand: dict[str, Any]) -> dict[str, Any]:
    brand_name = brand.get("brand_name") or ""
    aliases = brand.get("aliases") or []
    product_names = brand.get("product_names") or []
    service_names = brand.get("service_names") or []
    keywords = [
        *(brand.get("brand_keywords") or []),
        *(brand.get("context_terms") or []),
        *aliases,
    ]
    return {
        "competitor_name": brand_name,
        "competitor_company": brand.get("manufacturer") or brand_name,
        "aliases": aliases,
        "product_names": product_names,
        "service_names": service_names,
        "competitor_keywords": keywords,
        "context_terms": brand.get("context_terms") or [],
        "negative_terms": brand.get("negative_terms") or [],
        "ignore_terms": brand.get("negative_terms") or [],
        "entity_resolution": brand.get("entity_resolution") or {},
        "entity_type": brand.get("entity_type") or "brand",
    }


def _sanitize_ignore_terms_for_brand(brand: dict[str, Any], terms: list[str]) -> list[str]:
    identity_terms = {
        normalize(term)
        for term in [
            brand.get("brand_name") or "",
            brand.get("manufacturer") or "",
            *((brand.get("aliases") or [])),
            *((brand.get("product_names") or [])),
            *((brand.get("service_names") or [])),
        ]
        if normalize(str(term or ""))
    }
    entity_resolution = brand.get("entity_resolution") or {}
    if isinstance(entity_resolution, dict):
        entity_name = entity_resolution.get("entity_name") or ""
        if normalize(entity_name):
            identity_terms.add(normalize(entity_name))

    identity_tokens = {
        token
        for identity in identity_terms
        for token in identity.split()
        if token
    }

    sanitized = []
    for term in terms or []:
        normalized = normalize(str(term or ""))
        if not normalized:
            continue
        if normalized in identity_terms or normalized in identity_tokens:
            continue
        sanitized.append(term)
    return _unique_strings(sanitized)


def _merge_resolved_brand_context(brand: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resolved, dict) or not resolved:
        return brand

    merged = dict(brand)
    brand_name = str(brand.get("brand_name") or "").strip()
    resolved_name = str(resolved.get("entity_name") or "").strip()
    resolved_entity_type = str(resolved.get("entity_type") or "").lower()
    resolved_differs_from_input = bool(
        resolved_name
        and brand_name
        and normalize(resolved_name) != normalize(brand_name)
    )
    product_like_input = bool(
        brand_name
        and looks_like_product_name(brand_name)
        and resolved_differs_from_input
    )

    # Keep the user's active brand name for UI continuity, but use resolver output
    # as identity context for retrieval and filtering.
    merged["aliases"] = _unique_strings(
        brand.get("aliases"),
        resolved.get("aliases"),
        resolved.get("search_terms"),
        resolved_name if resolved_name and normalize(resolved_name) != normalize(brand.get("brand_name") or "") else "",
    )
    merged["categories"] = _unique_strings(brand.get("categories"), resolved.get("categories"))
    merged["context_terms"] = _unique_strings(
        brand.get("context_terms"),
        resolved.get("context_terms"),
        resolved.get("positive_terms"),
        resolved.get("primary_category"),
        resolved.get("subcategory"),
        resolved.get("competitor_category"),
    )
    merged["negative_terms"] = _sanitize_ignore_terms_for_brand(merged, _unique_strings(
        brand.get("negative_terms"),
        resolved.get("negative_terms"),
        resolved.get("ignore_terms"),
        resolved.get("exclude_terms"),
    ))
    merged["brand_keywords"] = _unique_strings(
        brand.get("brand_keywords"),
        resolved.get("search_terms"),
        resolved.get("aliases"),
        resolved.get("primary_category"),
        resolved.get("subcategory"),
    )
    merged["product_names"] = _unique_strings(
        brand.get("product_names"),
        resolved.get("product_names"),
        resolved.get("products"),
        brand_name if resolved_entity_type == "product" or product_like_input else "",
    )
    merged["service_names"] = _unique_strings(
        brand.get("service_names"),
        resolved.get("service_names"),
        resolved.get("services"),
    )

    for field in ["industry", "entity_type", "primary_category", "subcategory", "competitor_category", "brand_context"]:
        if resolved.get(field) and not merged.get(field):
            merged[field] = resolved.get(field)
    if resolved.get("description") and not merged.get("brand_context"):
        merged["brand_context"] = resolved.get("description")
    resolved_company_name = resolved.get("manufacturer") or (resolved_name if product_like_input else "")
    if resolved_company_name and not merged.get("manufacturer"):
        merged["manufacturer"] = resolved_company_name

    merged["entity_resolution"] = {
        "source": resolved.get("source") or "unknown",
        "confidence": resolved.get("confidence"),
        "entity_name": resolved_name or brand.get("brand_name") or "",
        "entity_type": resolved.get("entity_type") or merged.get("entity_type") or "",
        "industry": resolved.get("industry") or merged.get("industry") or "",
        "primary_category": resolved.get("primary_category") or merged.get("primary_category") or "",
        "manufacturer": resolved.get("manufacturer") or merged.get("manufacturer") or "",
    }
    merged["negative_terms"] = _sanitize_ignore_terms_for_brand(merged, merged.get("negative_terms") or [])
    return merged


def _resolve_brand_for_reputation(brand_id: str, brand: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    brand_name = brand.get("brand_name") or ""
    if not brand_name:
        return brand, {}

    print(f"[REPUTATION][ENTITY] Resolving active brand before reputation analysis: {brand_name}")
    try:
        resolved = resolve_brand(brand_name) or {}
        enriched_brand = _merge_resolved_brand_context(brand, resolved)
        log_path = write_reputation_log("entity_resolution", brand_id, {
            "stage": "reputation_entity_resolution",
            "input_brand": brand_name,
            "resolved": resolved,
            "enriched_brand_context": {
                "brand_name": enriched_brand.get("brand_name"),
                "manufacturer": enriched_brand.get("manufacturer"),
                "entity_type": enriched_brand.get("entity_type"),
                "industry": enriched_brand.get("industry"),
                "primary_category": enriched_brand.get("primary_category"),
                "aliases": enriched_brand.get("aliases"),
                "product_names": enriched_brand.get("product_names"),
                "service_names": enriched_brand.get("service_names"),
                "context_terms": enriched_brand.get("context_terms"),
            },
        })
        print(
            "[REPUTATION][ENTITY] Resolved active brand -> "
            f"{resolved.get('entity_name') or brand_name} "
            f"source={resolved.get('source') or 'unknown'} log={log_path}"
        )
        return enriched_brand, resolved
    except Exception as exc:
        log_path = write_reputation_log("errors", brand_id, {
            "stage": "reputation_entity_resolution",
            "input_brand": brand_name,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
        print(f"[REPUTATION][ENTITY] Resolver failed; using stored brand context -> {log_path}: {exc}")
        return brand, {}


def _brand_intelligence_cache_key(brand: dict[str, Any], resolved: dict[str, Any]) -> str:
    entity_name = ""
    if isinstance(resolved, dict):
        entity_name = str(resolved.get("entity_name") or "").strip()
    brand_name = str(brand.get("brand_name") or "").strip()
    return normalize(entity_name or brand_name)


def _fallback_brand_intelligence(brand: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    brand_name = brand.get("brand_name") or ""
    entity_name = resolved.get("entity_name") if isinstance(resolved, dict) else ""
    categories = _unique_strings(brand.get("categories"), resolved.get("categories") if isinstance(resolved, dict) else [])
    aliases = _unique_strings(brand.get("aliases"), resolved.get("aliases") if isinstance(resolved, dict) else [])
    products = _unique_strings(
        brand.get("product_names"),
        resolved.get("product_names") if isinstance(resolved, dict) else [],
        resolved.get("products") if isinstance(resolved, dict) else [],
    )
    services = _unique_strings(
        brand.get("service_names"),
        resolved.get("service_names") if isinstance(resolved, dict) else [],
        resolved.get("services") if isinstance(resolved, dict) else [],
    )
    keywords = _unique_strings(
        brand.get("context_terms"),
        brand.get("brand_keywords"),
        resolved.get("positive_terms") if isinstance(resolved, dict) else [],
        resolved.get("search_terms") if isinstance(resolved, dict) else [],
        categories,
    )
    return {
        "source": "fallback_resolved_entity",
        "entity_name": entity_name or brand_name,
        "industry": brand.get("industry") or (resolved.get("industry") if isinstance(resolved, dict) else ""),
        "categories": categories,
        "aliases": aliases,
        "products": products,
        "product_lines": products,
        "services": services,
        "executives": _unique_strings(brand.get("ceo_names"), brand.get("executive_names")),
        "investors": [],
        "strategic_partners": [],
        "parent_company": "",
        "funding_entities": [],
        "important_keywords": keywords,
        "category_queries": {},
    }


def _llm_brand_intelligence(brand: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {}

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    prompt = f"""
You are a brand intelligence query expansion engine.

Use the resolved entity context to identify important real-world entities and
search queries for reputation monitoring. Do not invent facts if uncertain.
Prefer well-known names, product lines, partners, investors, executives, and
industry-specific keywords that are likely to improve news/social retrieval.

Resolved brand context:
{json.dumps({
    "brand": brand,
    "resolved_entity": resolved,
}, indent=2, default=str)}

Return ONLY strict JSON:
{{
  "executives": [],
  "founders": [],
  "investors": [],
  "subsidiaries": [],
  "products": [],
  "product_lines": [],
  "competitors": [],
  "parent_company": "",
  "funding_entities": [],
  "strategic_partners": [],
  "important_keywords": [],
  "industry_keywords": [],
  "category_queries": {{
    "product": [],
    "esg": [],
    "investments": [],
    "regulatory": [],
    "complaints": [],
    "security": [],
    "layoffs": [],
    "fraud": [],
    "executive": []
  }}
}}

Rules:
- Every query must include the brand/entity name, an alias, a product line, or a known related entity plus the brand name.
- Keep each category to at most 6 concise search queries.
- Make queries useful for Google News, NewsAPI, Reddit, or YouTube.
- Do not include generic category-only queries.
"""
    raw_response = ""
    started = time.perf_counter()
    try:
        from groq import Groq

        timeout_seconds = max(
            1.0,
            float(os.getenv("REPUTATION_GROQ_TIMEOUT_SECONDS", "8")),
        )
        max_retries = max(
            0,
            int(os.getenv("REPUTATION_GROQ_MAX_RETRIES", "1")),
        )
        client = Groq(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw_response = response.choices[0].message.content or ""
        payload = parse_json_object(raw_response)
        payload["source"] = "groq_brand_intelligence"
        usage = getattr(response, "usage", None)
        payload["groq_usage"] = {
            "requests": 1,
            "cached_hits": 0,
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "model": model,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "success": True,
        }
        return payload
    finally:
        write_reputation_log("prompts", str(brand.get("brand_id") or "unknown"), {
            "stage": "brand_intelligence_generation",
            "model": model,
            "prompt": prompt,
            "raw_response": raw_response,
        })


def _get_brand_intelligence(
    brand_id: str,
    brand: dict[str, Any],
    resolved: dict[str, Any],
) -> dict[str, Any]:
    cache_key = _brand_intelligence_cache_key(brand, resolved)
    if cache_key and cache_key in _BRAND_INTELLIGENCE_CACHE:
        cached = copy.deepcopy(_BRAND_INTELLIGENCE_CACHE[cache_key])
        original_usage = cached.get("groq_usage") or {}
        cached["groq_usage"] = {
            "requests": 0,
            "cached_hits": 1,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "duration_ms": 0.0,
            "model": original_usage.get("model") or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            "success": True,
        }
        cached["cache_hit"] = True
        print(f"[REPUTATION][INTELLIGENCE] Cache hit for {cache_key}")
        return cached

    started = time.perf_counter()
    fallback = _fallback_brand_intelligence(brand, resolved)
    source = fallback.get("source")
    intelligence = fallback
    try:
        generated = _llm_brand_intelligence(brand, resolved)
        if generated:
            intelligence = {
                **fallback,
                **generated,
                "aliases": _unique_strings(fallback.get("aliases"), generated.get("aliases")),
                "products": _unique_strings(fallback.get("products"), generated.get("products")),
                "product_lines": _unique_strings(fallback.get("product_lines"), generated.get("product_lines")),
                "important_keywords": _unique_strings(
                    fallback.get("important_keywords"),
                    generated.get("important_keywords"),
                    generated.get("industry_keywords"),
                ),
            }
            source = intelligence.get("source") or "groq_brand_intelligence"
    except Exception as exc:
        intelligence["groq_usage"] = {
            "requests": 1,
            "cached_hits": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            "success": False,
            "error": str(exc),
        }
        write_reputation_log("errors", brand_id, {
            "stage": "brand_intelligence_generation",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
        print(f"[REPUTATION][INTELLIGENCE] Brand intelligence LLM failed; using fallback: {exc}")

    intelligence["source"] = source
    intelligence["generated_at"] = datetime.utcnow().isoformat()
    intelligence["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    if cache_key:
        _BRAND_INTELLIGENCE_CACHE[cache_key] = intelligence
    log_path = write_reputation_log("brand_intelligence", brand_id, {
        "stage": "temporary_brand_intelligence",
        "cache_key": cache_key,
        "source": source,
        "intelligence": intelligence,
    })
    print(f"[REPUTATION][INTELLIGENCE] Ready source={source} log={log_path}")
    return intelligence


def run_brand_reputation_analysis(brand_id: str) -> dict[str, Any]:
    try:
        brand = load_brand_context(brand_id)
        resolved_brand, resolved_entity = _resolve_brand_for_reputation(brand_id, brand)
        profile = _brand_profile(resolved_brand)
        profile["_brand_intelligence"] = _get_brand_intelligence(brand_id, resolved_brand, resolved_entity)
        result = run_reputation_analysis(brand_id, resolved_brand, profile)
        result["entity_resolution"] = resolved_entity or resolved_brand.get("entity_resolution") or {}
    except LookupError:
        raise
    except Exception as exc:
        result = _empty_reputation_result(
            brand_id,
            {},
            str(exc),
            traceback.format_exc(),
        )
    result["competitor"] = ""
    result["analysis_target"] = "active_brand"
    result["brand_id"] = brand_id
    return result
