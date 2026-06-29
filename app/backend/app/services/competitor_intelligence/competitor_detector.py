from __future__ import annotations

import ast
import json
import os
import re
import time
from typing import Any

import psycopg2
from dotenv import load_dotenv

from app.services.competitor_intelligence.competitor_logger import (
    append_competitor_log,
    write_competitor_log,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "../../../.env"))


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def get_existing_columns(cur, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    return {row[0] for row in cur.fetchall()}


def load_brand_context(brand_id: str) -> dict[str, Any]:
    """
    Fetch the monitored brand only. Competitor analysis is intentionally
    stateless and does not create or read competitor-specific tables.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        columns = get_existing_columns(cur, "monitored_brands")
        optional_columns = [
            "industry",
            "entity_type",
            "primary_category",
            "subcategory",
            "competitor_category",
            "manufacturer",
            "categories",
            "product_names",
            "service_names",
            "ceo_names",
            "executive_names",
            "campaign_names",
            "hashtags",
            "brand_keywords",
            "aliases",
            "context_terms",
            "negative_terms",
            "brand_context",
        ]
        selected_optional = [col for col in optional_columns if col in columns]
        select_sql = ", ".join(["brand_name", *selected_optional])
        cur.execute(
            f"""
            SELECT {select_sql}
            FROM monitored_brands
            WHERE id = %s
            LIMIT 1
            """,
            (brand_id,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError("Brand monitor not found")

        brand = {
            "brand_id": brand_id,
            "brand_name": row[0],
        }
        list_columns = {
            "categories",
            "product_names",
            "service_names",
            "ceo_names",
            "executive_names",
            "campaign_names",
            "hashtags",
            "brand_keywords",
            "aliases",
            "context_terms",
            "negative_terms",
        }
        for index, col in enumerate(selected_optional, start=1):
            value = row[index]
            if value is None:
                value = [] if col in list_columns else ""
            brand[col] = value

        for col in optional_columns:
            if col not in brand:
                brand[col] = [] if col in list_columns else ""

        return brand
    finally:
        cur.close()
        conn.close()


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

        # Groq occasionally returns a Python-looking dict instead of strict
        # JSON. Accept it as a compatibility fallback, then normalize below.
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


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def token_set(value: str) -> set[str]:
    stop = {
        "the",
        "inc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "company",
        "group",
        "auto",
        "motors",
    }
    return {token for token in normalize_name(value).split() if len(token) > 2 and token not in stop}


DOMAIN_KEYWORDS = {
    "ai": {
        "ai", "artificial", "intelligence", "generative", "llm", "model",
        "models", "chatbot", "chatgpt", "openai", "anthropic", "claude",
        "gemini", "mistral", "cohere", "perplexity", "xai", "deepseek",
    },
    "automotive": {
        "automotive", "vehicle", "vehicles", "car", "cars", "suv", "ev",
        "automobile", "hyundai", "kia", "skoda", "honda", "maruti",
        "toyota", "volkswagen", "tesla", "bmw", "mercedes",
    },
    "smartphone": {
        "smartphone", "smartphones", "phone", "phones", "mobile", "iphone",
        "galaxy", "android", "pixel", "oneplus", "xiaomi", "vivo", "oppo",
        "realme", "motorola",
    },
    "sportswear": {
        "sportswear", "apparel", "shoes", "sneaker", "sneakers", "fashion",
        "nike", "adidas", "puma", "reebok", "under", "armour",
    },
    "airline": {
        "airline", "aviation", "flight", "flights", "indigo", "spicejet",
        "vistara", "akasa",
    },
    "ecommerce": {
        "ecommerce", "commerce", "retail", "marketplace", "shopping",
        "amazon", "flipkart", "meesho", "myntra", "ajio",
    },
    "computer": {
        "computer", "laptop", "laptops", "hardware", "pc", "thinkpad",
        "lenovo", "dell", "hp", "asus", "acer",
    },
    "entertainment": {
        "cinema", "cinemas", "movie", "movies", "theatre", "theater",
        "theatres", "theaters", "multiplex", "film", "films", "screening",
        "screenings", "box", "office", "pvr", "inox", "cinepolis",
        "cinemax", "carnival",
    },
}


def infer_domain_from_text(text: str) -> str:
    tokens = token_set(text)
    scores = {
        domain: len(tokens.intersection(keywords))
        for domain, keywords in DOMAIN_KEYWORDS.items()
    }
    best_domain, best_score = max(scores.items(), key=lambda item: item[1])
    return best_domain if best_score > 0 else ""


def brand_domain(brand: dict[str, Any]) -> str:
    parts = [
        brand.get("brand_name"),
        brand.get("industry"),
        brand.get("entity_type"),
        brand.get("primary_category"),
        brand.get("subcategory"),
        brand.get("competitor_category"),
        " ".join(brand.get("categories") or []),
        " ".join(brand.get("context_terms") or []),
        " ".join(brand.get("brand_keywords") or []),
        " ".join(brand.get("aliases") or []),
    ]
    return infer_domain_from_text(" ".join(str(part or "") for part in parts))


def candidate_domain(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("name") or candidate.get("competitor_name"),
        candidate.get("reason"),
        candidate.get("type") or candidate.get("competitor_type"),
    ]
    return infer_domain_from_text(" ".join(str(part or "") for part in parts))


def self_terms_for_brand(brand: dict[str, Any]) -> set[str]:
    terms = {
        normalize_name(brand.get("brand_name") or ""),
        normalize_name(brand.get("manufacturer") or ""),
    }
    for key in ["aliases", "product_names", "service_names"]:
        for value in brand.get(key) or []:
            terms.add(normalize_name(value))
    terms.update(token_set(brand.get("brand_name") or ""))
    terms.update(token_set(brand.get("manufacturer") or ""))
    return {term for term in terms if term}


def is_self_competitor(candidate_name: str, brand: dict[str, Any]) -> bool:
    candidate = normalize_name(candidate_name)
    if not candidate:
        return True

    self_terms = self_terms_for_brand(brand)
    if candidate in self_terms:
        return True

    candidate_tokens = token_set(candidate)
    manufacturer = normalize_name(brand.get("manufacturer") or "")
    brand_name = normalize_name(brand.get("brand_name") or "")
    brand_tokens = token_set(brand_name)

    if manufacturer and manufacturer in candidate:
        return True
    if brand_name and (candidate in brand_name or brand_name in candidate):
        return True
    if brand_tokens and candidate_tokens and brand_tokens.intersection(candidate_tokens):
        return True
    return False


def load_recent_mention_texts(brand_id: str, limit: int = 200) -> list[str]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT title, body_text
            FROM brand_mentions
            WHERE brand_id = %s
            ORDER BY collected_at DESC
            LIMIT %s
            """,
            (brand_id, limit),
        )
        return [
            " ".join(part for part in [row[0] or "", row[1] or ""] if part)
            for row in cur.fetchall()
        ]
    except Exception as exc:
        print(f"[COMPETITOR] Mention frequency lookup skipped: {exc}")
        return []
    finally:
        cur.close()
        conn.close()


def mention_frequency_score(candidate_name: str, mention_texts: list[str]) -> tuple[int, float]:
    candidate_tokens = token_set(candidate_name)
    if not candidate_tokens or not mention_texts:
        return 0, 0.0

    count = 0
    normalized_candidate = normalize_name(candidate_name)
    for text in mention_texts:
        normalized_text = normalize_name(text)
        if normalized_candidate in normalized_text:
            count += 1
            continue
        if candidate_tokens.intersection(set(normalized_text.split())):
            count += 1
    return count, min(count / 20, 0.35)


def category_terms_for_brand(brand: dict[str, Any]) -> set[str]:
    text_parts = [
        brand.get("industry"),
        brand.get("entity_type"),
        brand.get("primary_category"),
        brand.get("subcategory"),
        brand.get("competitor_category"),
        " ".join(brand.get("categories") or []),
        " ".join(brand.get("context_terms") or []),
        " ".join(brand.get("brand_keywords") or []),
    ]
    return token_set(" ".join(str(part or "") for part in text_parts))


def category_relevance_score(candidate: dict[str, Any], brand: dict[str, Any]) -> float:
    category_terms = category_terms_for_brand(brand)
    if not category_terms:
        return 0.0

    candidate_text = " ".join(
        str(part or "")
        for part in [
            candidate.get("name") or candidate.get("competitor_name"),
            candidate.get("reason"),
            candidate.get("type") or candidate.get("competitor_type"),
        ]
    )
    candidate_terms = token_set(candidate_text)
    if not candidate_terms:
        return 0.0

    overlap = len(category_terms.intersection(candidate_terms))
    if overlap:
        return min(0.18, 0.06 * overlap)

    source = str(candidate.get("source") or "")
    if source.startswith("fallback"):
        return 0.12
    return 0.04


def brand_overlap_score(candidate_name: str, brand: dict[str, Any]) -> float:
    candidate_tokens = token_set(candidate_name)
    self_tokens = set()
    for term in self_terms_for_brand(brand):
        self_tokens.update(token_set(term))

    if not candidate_tokens or not self_tokens:
        return 1.0
    overlap = candidate_tokens.intersection(self_tokens)
    if not overlap:
        return 1.0
    return max(0.0, 1.0 - (len(overlap) / max(len(candidate_tokens), 1)))


def make_candidate(
    name: str,
    competitor_type: str = "direct",
    confidence: float = 0.55,
    reason: str = "",
    source: str = "fallback_temporary",
) -> dict[str, Any]:
    return {
        "name": name,
        "competitor_name": name,
        "competitor_type": competitor_type,
        "type": competitor_type,
        "confidence": confidence,
        "reason": reason,
        "source": source,
    }


def rank_and_filter_candidates(
    brand: dict[str, Any],
    candidates: list[dict[str, Any]],
    mention_texts: list[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = []
    rejected = []
    seen = set()
    expected_domain = brand_domain(brand)

    for index, candidate in enumerate(candidates):
        name = candidate.get("name") or candidate.get("competitor_name") or ""
        normalized = normalize_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        if is_self_competitor(name, brand):
            rejected.append({
                "name": name,
                "reason": "self_brand_or_same_manufacturer",
                "brand_overlap_score": brand_overlap_score(name, brand),
            })
            continue

        actual_domain = candidate_domain(candidate)
        if expected_domain and actual_domain and expected_domain != actual_domain:
            rejected.append({
                "name": name,
                "reason": "industry_or_category_mismatch",
                "expected_domain": expected_domain,
                "candidate_domain": actual_domain,
            })
            continue

        mentions, mention_boost = mention_frequency_score(name, mention_texts)
        category_score = category_relevance_score(candidate, brand)
        overlap_score = brand_overlap_score(name, brand)
        base = float(candidate.get("confidence") or 0.55)
        order_penalty = min(index * 0.025, 0.12)
        confidence = max(
            0.1,
            min(0.98, base + mention_boost + category_score + (overlap_score * 0.05) - order_penalty),
        )
        ranked.append({
            **candidate,
            "name": name,
            "competitor_name": name,
            "confidence": round(confidence, 3),
            "mention_count": mentions,
            "category_relevance": round(category_score, 3),
            "brand_overlap_score": round(overlap_score, 3),
            "expected_domain": expected_domain,
            "candidate_domain": actual_domain,
            "confidence_breakdown": {
                "base": round(base, 3),
                "mention_boost": round(mention_boost, 3),
                "category_relevance": round(category_score, 3),
                "brand_overlap_bonus": round(overlap_score * 0.05, 3),
                "order_penalty": round(order_penalty, 3),
            },
            "reason": candidate.get("reason") or (
                f"Seen in {mentions} recent mentions."
                if mentions
                else "Suggested from category context."
            ),
        })

    ranked.sort(key=lambda item: (item.get("mention_count") or 0, item.get("confidence") or 0), reverse=True)
    return ranked[:limit], rejected


def fallback_competitors(
    brand: dict[str, Any],
    limit: int = 8,
    mention_texts: list[str] | None = None,
) -> list[dict[str, Any]]:
    text = " ".join(
        str(part or "")
        for part in [
            brand.get("brand_name"),
            brand.get("industry"),
            brand.get("entity_type"),
            brand.get("primary_category"),
            brand.get("subcategory"),
            brand.get("competitor_category"),
            " ".join(brand.get("categories") or []),
            " ".join(brand.get("context_terms") or []),
            " ".join(brand.get("brand_keywords") or []),
        ]
    ).lower()

    fallback_sets = [
        (
            {"ai", "artificial", "intelligence", "generative", "llm", "chatgpt", "openai", "model", "models"},
            ["Anthropic Claude", "Google Gemini", "Meta AI", "Mistral AI", "Cohere", "xAI Grok", "Perplexity AI", "DeepSeek"],
        ),
        (
            {"smartphone", "phone", "mobile", "iphone", "galaxy", "android"},
            ["Samsung Galaxy", "Google Pixel", "OnePlus", "Xiaomi", "Vivo", "OPPO", "Realme", "Motorola Edge"],
        ),
        (
            {"automotive", "vehicle", "car", "suv", "ev", "automobile"},
            ["Hyundai Creta", "Kia Seltos", "Skoda Kushaq", "Honda Elevate", "Maruti Grand Vitara", "Toyota Hyryder", "Volkswagen Taigun"],
        ),
        (
            {"sportswear", "apparel", "shoes", "sneaker", "fashion"},
            ["Adidas", "Nike", "Puma", "Reebok", "New Balance", "Under Armour"],
        ),
        (
            {"airline", "aviation", "flight"},
            ["IndiGo", "Air India", "Akasa Air", "Vistara", "SpiceJet"],
        ),
        (
            {"e-commerce", "retail", "marketplace", "shopping"},
            ["Flipkart", "Amazon", "Meesho", "Myntra", "Ajio", "Tata Cliq"],
        ),
        (
            {"technology", "computer", "laptop", "electronics", "hardware"},
            ["HP", "Dell", "Lenovo", "Apple", "Asus", "Acer", "Samsung"],
        ),
        (
            {"cinema", "cinemas", "movie", "movies", "theatre", "theater", "multiplex", "film", "screening"},
            ["INOX", "Cinepolis", "Miraj Cinemas", "Carnival Cinemas", "Cinemax", "Mukta A2 Cinemas"],
        ),
    ]

    names: list[str] = []
    for keywords, candidates in fallback_sets:
        if any(keyword in text for keyword in keywords):
            names = candidates
            break

    if not names:
        domain = brand_domain(brand)
        if domain == "ai":
            names = ["Anthropic Claude", "Google Gemini", "Meta AI", "Mistral AI", "Cohere", "xAI Grok"]
        elif domain == "automotive":
            names = ["Hyundai Creta", "Kia Seltos", "Honda Elevate", "Toyota Hyryder"]
        elif domain == "smartphone":
            names = ["Samsung Galaxy", "Google Pixel", "OnePlus", "Xiaomi"]
        elif domain == "entertainment":
            names = ["INOX", "Cinepolis", "Miraj Cinemas", "Carnival Cinemas", "Cinemax"]
        else:
            names = ["Google", "Amazon", "Microsoft", "Apple", "Samsung", "Meta", "Reliance", "Tata"]

    candidates = [
        make_candidate(
            name,
            competitor_type="direct",
            confidence=max(0.42, 0.66 - index * 0.035),
            reason="Fallback suggestion based on brand category context.",
        )
        for index, name in enumerate(names)
    ]
    ranked, _ = rank_and_filter_candidates(brand, candidates, mention_texts or [], limit)
    return ranked


def build_discovery_prompt(brand: dict[str, Any], limit: int) -> str:
    return f"""
Find likely competitors for this monitored entity. Do not use database storage.

Brand/entity:
{json.dumps(brand, indent=2, default=str)}

Return ONLY valid JSON:
{{
  "competitors": [
    {{
      "name": "Competitor name",
      "type": "direct",
      "confidence": 0.0,
      "reason": "short reason"
    }}
  ]
}}

Rules:
- Return strict JSON only. No markdown, no prose, no Python dicts, no trailing comments.
- Use double quotes for every JSON key and string value.
- Competitors must match the brand's category/subcategory, not just the broad company.
- For products or vehicles, return competing products/models where possible.
- Exclude the monitored brand itself, its manufacturer, and same-family products.
- Example: for iPhone/Apple, never return Apple, Apple iPhone, iPhone, or other Apple iPhone models.
- Example: for Samsung Galaxy S21, never return Samsung, Samsung Galaxy, Galaxy S22, or Samsung phones.
- Type must be one of: direct, indirect, market_leader, budget_alternative, premium_alternative.
- Limit to {limit} competitors.
"""


def groq_discover_competitors(brand: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("[COMPETITOR] GROQ_API_KEY missing; competitor discovery skipped")
        return fallback_competitors(brand, limit=limit)

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    prompt = build_discovery_prompt(brand, limit)
    from groq import Groq

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw_response = response.choices[0].message.content or ""
    write_competitor_log("prompts", brand["brand_id"], {
        "stage": "competitor_discovery",
        "model": model,
        "prompt": prompt,
        "raw_response": raw_response,
    })
    payload = parse_json_object(raw_response)
    competitors = payload.get("competitors") or []

    cleaned = []
    for item in competitors[:limit]:
        if isinstance(item, str):
            cleaned.append(make_candidate(item, confidence=0.7, source="groq_temporary"))
        elif isinstance(item, dict) and item.get("name"):
            competitor_type = item.get("competitor_type") or item.get("type") or "direct"
            cleaned.append(make_candidate(
                item.get("name"),
                competitor_type=competitor_type,
                confidence=float(item.get("confidence") or 0.7),
                reason=item.get("reason") or "",
                source="groq_temporary",
            ))
    return cleaned


def discover_competitors(brand_id: str, limit: int = 8, refresh: bool = False) -> list[dict[str, Any]]:
    # refresh is accepted for API compatibility; there is no persistence/cache here.
    trace_steps = []
    started = time.perf_counter()

    step_started = time.perf_counter()
    brand = load_brand_context(brand_id)
    trace_steps.append({
        "step": "load_brand_context",
        "status": "success",
        "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
    })

    step_started = time.perf_counter()
    mention_texts = load_recent_mention_texts(brand_id)
    trace_steps.append({
        "step": "load_recent_mention_texts",
        "status": "success",
        "count": len(mention_texts),
        "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
    })

    source = "groq"
    error = ""
    try:
        step_started = time.perf_counter()
        raw_candidates = groq_discover_competitors(brand, limit=max(limit * 2, 12))
        trace_steps.append({
            "step": "groq_discover_competitors",
            "status": "success",
            "count": len(raw_candidates),
            "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
        })
    except Exception as exc:
        source = "fallback"
        error = str(exc)
        print(f"[COMPETITOR] Groq discovery failed; using fallback suggestions: {exc}")
        write_competitor_log("fallbacks", brand_id, {
            "stage": "competitor_discovery",
            "reason": error,
            "brand": brand,
        })
        raw_candidates = fallback_competitors(brand, limit=max(limit * 2, 12), mention_texts=mention_texts)
        trace_steps.append({
            "step": "fallback_competitors",
            "status": "success",
            "count": len(raw_candidates),
            "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
        })

    step_started = time.perf_counter()
    ranked, rejected = rank_and_filter_candidates(brand, raw_candidates, mention_texts, limit)
    if not ranked and source != "fallback":
        source = "fallback"
        write_competitor_log("fallbacks", brand_id, {
            "stage": "competitor_discovery_empty_after_validation",
            "reason": "all candidates rejected or no valid candidates returned",
            "brand": brand,
            "raw_candidates": raw_candidates,
            "rejected": rejected,
        })
        raw_candidates = fallback_competitors(brand, limit=max(limit * 2, 12), mention_texts=mention_texts)
        ranked, fallback_rejected = rank_and_filter_candidates(brand, raw_candidates, mention_texts, limit)
        rejected.extend(fallback_rejected)
    trace_steps.append({
        "step": "validate_and_rank_candidates",
        "status": "success",
        "accepted": len(ranked),
        "rejected": len(rejected),
        "duration_ms": round((time.perf_counter() - step_started) * 1000, 2),
    })

    validation_entries = [
        {
            "candidate": item.get("name"),
            "result": "accepted",
            "mention_count": item.get("mention_count"),
            "confidence": item.get("confidence"),
            "category_relevance": item.get("category_relevance"),
            "brand_overlap_score": item.get("brand_overlap_score"),
            "reason": item.get("reason"),
        }
        for item in ranked
    ] + [
        {
            "candidate": item.get("name"),
            "result": "rejected",
            "reason": item.get("reason"),
        }
        for item in rejected
    ]
    write_competitor_log("validation", brand_id, {
        "stage": "competitor_discovery",
        "entries": validation_entries,
    })

    log_path = write_competitor_log("discovery", brand_id, {
        "brand": brand,
        "source": source,
        "error": error,
        "mention_texts_scanned": len(mention_texts),
        "raw_candidates": raw_candidates,
        "rejected": rejected,
        "returned": ranked,
    })
    trace_steps.append({
        "step": "write_discovery_log",
        "status": "success",
        "path": log_path,
    })
    write_competitor_log("traces", brand_id, {
        "stage": "competitor_discovery",
        "status": "success",
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "steps": trace_steps,
    })
    append_competitor_log("competitor_discovery_complete", {
        "brand_id": brand_id,
        "source": source,
        "accepted": len(ranked),
        "rejected": len(rejected),
    })
    print(f"[COMPETITOR] Discovery log -> {log_path}")
    return ranked
