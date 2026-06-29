from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from .intelligence_common import compact_evidence
from app.services.competitor_intelligence.competitor_logger import write_competitor_log
from app.services.competitor_intelligence.intelligence_common import *
from app.services.entity_resolution.entity_detector import detect_brand_entities

@lru_cache(maxsize=1)
def get_roberta_sentiment_model():
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

        model_name = os.getenv("COMPETITOR_SENTIMENT_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest")
        allow_download = os.getenv("ALLOW_HF_DOWNLOADS", "0") == "1"
        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=not allow_download)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, local_files_only=not allow_download)
        print(f"[COMPETITOR] RoBERTa sentiment loaded: {model_name}")
        return pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,
            truncation=True,
            max_length=128,
            device=-1,
        )
    except Exception as exc:
        print(f"[COMPETITOR] RoBERTa sentiment unavailable: {exc}")
        return None


def apply_roberta_sentiment(mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not mentions:
        return []
    try:
        model = get_roberta_sentiment_model()
        texts = [text_for_mention(mention) or "no content" for mention in mentions]
        if model is None:
            return mentions
        raw_results = model(texts)
        sentiments = []
        for result_list in raw_results:
            scores = {item["label"].lower(): float(item["score"]) for item in result_list}
            top_label = max(scores, key=scores.get)
            sentiments.append({
                "label": top_label,
                "confidence": round(scores[top_label], 3),
                "sentiment_score": round(scores.get("positive", 0) - scores.get("negative", 0), 3),
                "scores": {key: round(value, 3) for key, value in scores.items()},
            })
        enriched = []
        for mention, sentiment in zip(mentions, sentiments):
            enriched.append({
                **mention,
                "sentiment_label": sentiment.get("label") or mention.get("sentiment_label") or "neutral",
                "sentiment_score": sentiment.get("sentiment_score"),
                "sentiment_confidence": sentiment.get("confidence"),
                "sentiment_breakdown": sentiment.get("scores") or {},
                "sentiment_source": "roberta",
            })
        return enriched
    except Exception as exc:
        print(f"[COMPETITOR] RoBERTa sentiment skipped: {exc}")
        return mentions


@lru_cache(maxsize=1)
def get_zero_shot_classifier():
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

        model_name = os.getenv("COMPETITOR_ZERO_SHOT_MODEL", "facebook/bart-large-mnli")
        allow_download = os.getenv("ALLOW_HF_DOWNLOADS", "0") == "1"
        print(f"[COMPETITOR] Loading zero-shot classifier: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=not allow_download)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, local_files_only=not allow_download)
        return pipeline(
            "zero-shot-classification",
            model=model,
            tokenizer=tokenizer,
            device=-1,
        )
    except Exception as exc:
        print(f"[COMPETITOR] Zero-shot classifier unavailable; keyword fallback active: {exc}")
        return None


def keyword_bucket(text: str, direct_comparison: bool = False) -> tuple[str, float, str]:
    normalized_text = normalize(text)
    if direct_comparison:
        return "comparison", 0.86, "brand_and_competitor_comparison_terms"

    for bucket, keywords in BUCKET_KEYWORDS.items():
        if bucket == "comparison":
            continue
        for keyword in keywords:
            if normalize(keyword) and normalize(keyword) in normalized_text:
                return bucket, 0.62, f"keyword:{keyword}"
    return "general", 0.45, "keyword_fallback_general"


def classify_metric_bucket(
    text: str,
    direct_comparison: bool = False,
    retrieval_metric: str = "",
) -> tuple[str, float, str]:
    if not text:
        return "general", 0.0, "empty_text"
    if direct_comparison:
        return "comparison", 0.92, "direct_comparison"

    if retrieval_metric in {"pricing", "features", "hiring", "funding", "ma", "terminations", "comparison"}:
        if retrieval_metric == "comparison":
            return "general", 0.42, "comparison_requires_brand_and_competitor"
        if retrieval_metric in CORPORATE_LEVEL_METRICS:
            if article_matches_metric({"title": text, "source": ""}, retrieval_metric):
                return retrieval_metric, 0.82, f"business_metric_gate:{retrieval_metric}"
            return "general", 0.42, f"missing_business_metric_signal:{retrieval_metric}"
        keyword_bucket_name, keyword_score, keyword_reason = keyword_bucket(text, direct_comparison)
        if keyword_bucket_name == retrieval_metric:
            return retrieval_metric, max(0.78, keyword_score), f"retrieval_metric:{retrieval_metric}"
        if keyword_bucket_name == "general" and article_matches_metric({"title": text}, retrieval_metric):
            return retrieval_metric, 0.78, f"metric_keyword_gate:{retrieval_metric}"

    classifier = get_zero_shot_classifier()
    if classifier is None:
        return keyword_bucket(text, direct_comparison)

    try:
        result = classifier(text[:1000], ZERO_SHOT_LABELS, multi_label=False)
        label = (result.get("labels") or ["general news"])[0]
        score = float((result.get("scores") or [0.0])[0])
        bucket = BUCKET_TO_KEY.get(label, "general")
        if score < float(os.getenv("COMPETITOR_ZERO_SHOT_MIN_SCORE", "0.75")):
            return "general", score, f"zero_shot_low_confidence:{label}"
        return bucket, score, f"zero_shot:{label}"
    except Exception as exc:
        print(f"[COMPETITOR] Zero-shot classification failed; keyword fallback active: {exc}")
        return keyword_bucket(text, direct_comparison)


def validate_competitor_evidence(
    mentions: list[dict[str, Any]],
    brand_terms: list[str],
    competitor_terms: list[str],
    required_metric_terms: dict[str, list[str]] | None = None,
    entity_context_terms: list[str] | None = None,
    require_entity_context: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validated = []
    rejected = []

    for mention in mentions:
        text = text_for_mention(mention)
        has_competitor = term_present(text, competitor_terms)
        has_brand = term_present(text, brand_terms)
        direct = bool(has_brand and has_competitor and COMPARISON_RE.search(text or ""))
        reason = ""
        gliner_entities = []
        entity_confidence = 0.0

        if has_competitor:
            relevance = "direct_comparison" if direct else "competitor"
            reason = "competitor_term_match"
            entity_confidence = 0.82
        else:
            try:
                gliner_entities = detect_brand_entities(text[:600], min_score=0.45)
            except Exception as exc:
                print(f"[COMPETITOR] GLiNER validation skipped: {exc}")
                gliner_entities = []
            entity_texts = [entity.get("text") or "" for entity in gliner_entities]
            entity_blob = " ".join(entity_texts)
            if term_present(entity_blob, competitor_terms):
                relevance = "direct_comparison" if has_brand else "competitor"
                reason = "gliner_competitor_entity"
                entity_confidence = 0.72
            elif direct:
                relevance = "direct_comparison"
                reason = "direct_comparison_terms"
                entity_confidence = 0.68
            else:
                rejected.append({
                    "title": mention.get("title") or "",
                    "url": mention.get("url") or "",
                    "reason": "neither_competitor_nor_direct_comparison",
                    "entities": entity_texts,
                })
                continue

        context_terms = entity_context_terms or []
        if require_entity_context and context_terms and not term_present(text, context_terms):
            rejected.append({
                "title": mention.get("title") or "",
                "url": mention.get("url") or "",
                "reason": "entity_context_confidence_too_low",
                "entity_confidence": round(min(entity_confidence, 0.35), 3),
                "required_context_terms": context_terms[:8],
            })
            continue

        metric = mention.get("metric") or ""
        required_terms = (required_metric_terms or {}).get(metric) or []
        if required_terms and not term_present(text, required_terms):
            rejected.append({
                "title": mention.get("title") or "",
                "url": mention.get("url") or "",
                "metric": metric,
                "reason": "missing_metric_specific_product_or_service_term",
                "required_terms": required_terms[:8],
            })
            continue

        if is_consumer_noise_for_business_metric(mention, metric):
            rejected.append({
                "title": mention.get("title") or "",
                "url": mention.get("url") or "",
                "metric": metric,
                "source": mention.get("source") or "",
                "reason": "consumer_content_for_business_metric",
            })
            continue

        bucket, bucket_score, bucket_reason = classify_metric_bucket(
            text,
            relevance == "direct_comparison",
            mention.get("metric") or "",
        )
        validated.append({
            **mention,
            "relevance": relevance,
            "validation_reason": reason,
            "classification": bucket,
            "classification_confidence": round(bucket_score, 3),
            "classification_reason": bucket_reason,
            "gliner_entities": gliner_entities,
            "entity_confidence": round(entity_confidence, 3),
        })

    return validated, {
        "input": len(mentions),
        "kept": len(validated),
        "rejected": len(rejected),
        "rejected_examples": rejected[:20],
    }


def classified_signals_from_mentions(
    mentions: list[dict[str, Any]],
) -> dict[str, Any]:
    pricing = empty_pricing()
    features = []
    hiring = empty_hiring()
    funding = []
    mergers = []
    terminations = []
    direct_comparisons = []

    for mention in mentions:
        bucket = mention.get("classification") or "general"
        item = {
            "title": mention.get("title") or "",
            "source": mention.get("source") or "",
            "source_name": mention.get("source_name") or "",
            "url": mention.get("url") or "",
            "reason": mention.get("classification_reason") or mention.get("validation_reason") or "",
            "confidence": mention.get("classification_confidence"),
            "sentiment": mention.get("sentiment_label") or "",
            "relevance": mention.get("relevance") or "",
            "snippet": text_for_mention(mention)[:240],
        }
        if bucket == "pricing":
            pricing["examples"].append({**item, "prices": [], "pricing_context": item["reason"]})
        elif bucket == "features":
            features.append({**item, "feature": item["title"], "trigger": item["reason"], "evidence": item["snippet"]})
        elif bucket == "hiring":
            hiring["evidence"].append(item)
        elif bucket == "funding":
            funding.append({**item, "event": item["reason"], "amount": ""})
        elif bucket == "ma":
            mergers.append({**item, "event": item["reason"]})
        elif bucket == "terminations":
            terminations.append({**item, "event": item["reason"], "count": None})
        elif bucket == "comparison":
            direct_comparisons.append(item)

    pricing["examples"] = pricing["examples"][:8]
    pricing["evidence_count"] = len(pricing["examples"])
    hiring["evidence"] = hiring["evidence"][:12]
    hiring["evidence_count"] = len(hiring["evidence"])
    if hiring["evidence_count"] >= 5:
        hiring["trend"] = "increasing"
    elif hiring["evidence_count"]:
        hiring["trend"] = "some_activity"

    return {
        "pricing": pricing,
        "features": features[:12],
        "hiring": hiring,
        "funding": funding[:12],
        "mergers": mergers[:12],
        "terminations": terminations[:12],
        "direct_comparisons": direct_comparisons[:12],
    }


def apply_no_evidence_status(
    pricing: dict[str, Any],
    features: list[dict[str, Any]],
    hiring: dict[str, Any],
    funding: list[dict[str, Any]],
    mergers: list[dict[str, Any]],
    terminations: list[dict[str, Any]],
    metric_retrieval_summary: dict[str, Any],
    validated_mentions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    validated_by_metric: dict[str, int] = {}
    for mention in validated_mentions:
        metric = mention.get("metric") or ""
        if metric:
            validated_by_metric[metric] = validated_by_metric.get(metric, 0) + 1

    runs = as_dict(metric_retrieval_summary.get("runs") or {})

    related_mentions = [
        mention for mention in validated_mentions
        if (mention.get("title") or mention.get("url"))
    ]

    def status(metric: str, label: str) -> dict[str, Any]:
        raw_found = sum(int(run.get("raw_found") or 0) for run in as_list(runs.get(metric) or []))
        related = next(
            (mention for mention in related_mentions if mention.get("metric") == metric),
            None,
        )
        if related:
            return {
                "status": "related_context",
                "metric": metric,
                "event": "related_context",
                "title": related.get("title") or f"Related {label} context",
                "source": related.get("source") or "google_news",
                "url": related.get("url") or "",
                "snippet": text_for_mention(related)[:240],
                "sentiment": related.get("sentiment_label") or "",
                "relevance": related.get("relevance") or "competitor",
                "reason": (
                    f"No direct {label} signal was validated for this tab, "
                    "so this is the closest validated competitor-related article."
                ),
                "confidence": related.get("classification_confidence") or 0.55,
            }
        return {
            "status": "no_direct_evidence",
            "metric": metric,
            "event": "no_direct_evidence",
            "title": f"No direct {label} evidence found",
            "source": "google_news",
            "url": "",
            "reason": (
                f"Searched {raw_found} Google News result(s), but no validated "
                f"competitor-specific {label} signal was found."
            ),
            "insight": (
                f"No direct {label} event was validated after live retrieval. "
                "For mature companies or product-level competitors, this usually means "
                "the stronger market signals are in earnings, partnerships, product "
                "launches, hiring, pricing, or expansion news rather than this tab."
            ),
            "confidence": 1.0,
        }

    if not pricing.get("examples") and not validated_by_metric.get("pricing"):
        pricing["examples"] = [status("pricing", "pricing")]
        pricing["evidence_count"] = 0
    if not features and not validated_by_metric.get("features"):
        features = [status("features", "feature")]
    if not hiring.get("evidence") and not validated_by_metric.get("hiring"):
        hiring["evidence"] = [status("hiring", "hiring")]
        hiring["evidence_count"] = 0
    if not funding and not validated_by_metric.get("funding"):
        funding = [status("funding", "funding")]
    if not mergers and not validated_by_metric.get("ma"):
        mergers = [status("ma", "M&A")]
    if not terminations and not validated_by_metric.get("terminations"):
        terminations = [status("terminations", "termination")]

    return pricing, features, hiring, funding, mergers, terminations




def llm_extract_metric_signals(
    brand: dict[str, Any],
    competitor_profile: dict[str, Any],
    competitor_mentions: list[dict[str, Any]],
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not competitor_mentions:
        return {}

    batch_size = max(1, int(os.getenv("COMPETITOR_GROQ_EVIDENCE_BATCH_SIZE", "5")))
    if len(competitor_mentions) > batch_size:
        batches = [
            competitor_mentions[index:index + batch_size]
            for index in range(0, len(competitor_mentions), batch_size)
        ]
        payloads = []
        for index, batch in enumerate(batches, start=1):
            print(f"[COMPETITOR] Groq metric extraction batch {index}/{len(batches)} ({len(batch)} items)")
            payload = llm_extract_metric_signals(brand, competitor_profile, batch)
            if payload:
                payloads.append(payload)
        return merge_llm_signal_payloads(payloads)

    from groq import Groq

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    evidence = compact_evidence(competitor_mentions, limit=batch_size)
    prompt = f"""
You are a competitor intelligence analyst.

Classify the provided evidence for the monitored brand and temporary
competitor. Before any article enters a metric tab, decide whether it is
primarily about:
A) the competitor
B) the monitored brand vs the competitor
C) neither

Discard C/neither completely. Do not infer, assume, or invent facts. If
evidence does not explicitly support a metric, return an empty array/object for
that metric. Use only the supplied evidence titles/snippets/URLs.

Brand:
{json.dumps(brand, indent=2, default=str)}

Temporary competitor profile:
{json.dumps(competitor_profile, indent=2, default=str)}

Metric definitions:
{json.dumps(METRIC_DESCRIPTIONS, indent=2, default=str)}

Strict business metric validation rules:
- Funding: include ONLY evidence that explicitly mentions a funding round, raised capital,
  fundraising, investors, valuation, venture capital, financing, credit facility, debt
  financing, strategic capital, or capital infusion. Product reviews, price/deal videos,
  unboxings, benchmarks, and product comparisons are never funding.
- M&A: include ONLY evidence that explicitly mentions merger, acquisition, acquired,
  buyout, takeover, ownership stake, joint venture, or corporate consolidation. A product
  launch, review, partnership for marketing, or integration is not M&A unless ownership
  change is explicit.
- Hiring: include ONLY evidence that explicitly mentions hiring, recruiting, recruitment,
  job openings, new roles, headcount growth, staff expansion, team expansion, talent
  acquisition, or workforce expansion. Generic mentions of employees, executives, or
  workforce are not enough.
- Terminations: include ONLY evidence that explicitly mentions layoffs, laid off, job cuts,
  workforce reduction, headcount reduction, staff cuts, redundancies, office/store/plant
  closure, ceased operations, or restructuring tied to workforce/operations. Device
  shutdowns, discontinued videos, tutorials, product shutdown/restart, and review content
  are not terminations.
- For YouTube or Reddit product-review style evidence, never classify it as funding, M&A,
  hiring, or terminations unless it contains explicit company-level business terms above.
- If evidence is weak or only product-level, leave the business metric empty.

Evidence mentions:
{json.dumps(evidence, indent=2, default=str)}

Return ONLY strict JSON:
{{
  "classified_evidence": [
    {{
      "title": "exact evidence title",
      "url": "url",
      "source": "source",
      "relevance": "competitor|direct_comparison|neither",
      "tabs": ["sentiment", "features"],
      "sentiment": "positive|neutral|negative",
      "reason": "why it belongs",
      "confidence": 0.0
    }}
  ],
  "pricing": {{
    "price_points": [],
    "examples": [
      {{
        "title": "exact evidence title",
        "source": "source",
        "url": "url",
        "pricing_context": "why this is pricing",
        "prices": [],
        "reason": "why this belongs in pricing",
        "confidence": 0.0
      }}
    ]
  }},
  "feature_announcements": [
    {{
      "feature": "specific product, service, release, rollout, integration, or availability signal",
      "trigger": "matched phrase from evidence",
      "source": "source",
      "url": "url",
      "evidence": "short exact evidence snippet",
      "reason": "why this belongs in features",
      "confidence": 0.0
    }}
  ],
  "hiring_trends": {{
    "trend": "no_signal|some_activity|increasing",
    "evidence": [
      {{
        "title": "exact evidence title",
        "source": "source",
        "url": "url",
        "reason": "matched hiring/workforce signal",
        "confidence": 0.0
      }}
    ]
  }},
  "funding": [
    {{
      "event": "funding event",
      "amount": "",
      "title": "exact evidence title",
      "source": "source",
      "url": "url",
      "reason": "why this belongs in funding",
      "confidence": 0.0
    }}
  ],
  "mergers": [
    {{
      "event": "merger, acquisition, partnership, or joint venture",
      "title": "exact evidence title",
      "source": "source",
      "url": "url",
      "reason": "why this belongs in M&A",
      "confidence": 0.0
    }}
  ],
  "terminations": [
    {{
      "event": "layoff, closure, shutdown, discontinued operation, or restructuring",
      "count": null,
      "title": "exact evidence title",
      "source": "source",
      "url": "url",
      "reason": "why this belongs in terminations",
      "confidence": 0.0
    }}
  ],
  "direct_comparisons": [
    {{
      "title": "exact evidence title",
      "source": "source",
      "url": "url",
      "reason": "why this is a direct comparison",
      "confidence": 0.0
    }}
  ]
}}
"""
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw_response = response.choices[0].message.content or ""
        write_competitor_log("prompts", brand["brand_id"], {
            "stage": "competitor_metric_signal_extraction",
            "model": model,
            "prompt": prompt,
            "raw_response": raw_response,
        })
        return parse_json_object(raw_response)
    except Exception as exc:
        write_competitor_log("fallbacks", brand["brand_id"], {
            "stage": "competitor_metric_signal_extraction",
            "reason": str(exc),
            "prompt": prompt,
            "raw_response": locals().get("raw_response", ""),
        })
        print(f"[COMPETITOR] Groq metric extraction skipped: {exc}")
        return {}


def merge_unique_events(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    seen = set()
    for item in [*(existing or []), *(incoming or [])]:
        if not isinstance(item, dict):
            continue
        key = event_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def event_key(item: dict[str, Any]) -> str:
    url = normalize(str(item.get("url") or ""))
    if url:
        return f"url:{url}"
    return normalize(" ".join(
        str(item.get(field) or "")
        for field in ["title", "feature", "event", "source"]
    ))


def dedupe_events(items: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    deduped = merge_unique_events([], items)
    return deduped[:limit] if limit is not None else deduped


def merge_llm_signal_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    if not payloads:
        return {}

    merged: dict[str, Any] = {
        "classified_evidence": [],
        "pricing": {"price_points": [], "examples": []},
        "feature_announcements": [],
        "hiring_trends": {"trend": "no_signal", "evidence": []},
        "funding": [],
        "mergers": [],
        "terminations": [],
        "direct_comparisons": [],
    }
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        merged["classified_evidence"] = merge_unique_events(
            merged["classified_evidence"],
            as_list(payload.get("classified_evidence") or []),
        )

        pricing = as_dict(payload.get("pricing") or {})
        merged["pricing"]["price_points"] = list(dict.fromkeys([
            *as_list(merged["pricing"].get("price_points") or []),
            *as_list(pricing.get("price_points") or []),
        ]))[:20]
        merged["pricing"]["examples"] = merge_unique_events(
            as_list(merged["pricing"].get("examples") or []),
            as_list(pricing.get("examples") or []),
        )[:12]

        merged["feature_announcements"] = merge_unique_events(
            merged["feature_announcements"],
            as_list(payload.get("feature_announcements") or []),
        )

        hiring = as_dict(payload.get("hiring_trends") or {})
        hiring_evidence = merge_unique_events(
            as_list(merged["hiring_trends"].get("evidence") or []),
            as_list(hiring.get("evidence") or []),
        )
        merged["hiring_trends"]["evidence"] = hiring_evidence[:12]
        if len(hiring_evidence) >= 5:
            merged["hiring_trends"]["trend"] = "increasing"
        elif hiring_evidence:
            merged["hiring_trends"]["trend"] = "some_activity"

        for key in ["funding", "mergers", "terminations", "direct_comparisons"]:
            merged[key] = merge_unique_events(merged[key], as_list(payload.get(key) or []))

    return merged


def valid_feature_signal(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(field) or "")
        for field in ["feature", "title", "trigger", "evidence", "snippet"]
    )
    if not text.strip():
        return False
    if NON_FEATURE_SIGNAL_RE.search(text):
        return False
    return bool(FEATURE_SIGNAL_RE.search(text))


def valid_metric_signal(item: dict[str, Any], metric: str) -> bool:
    text = " ".join(
        str(item.get(field) or "")
        for field in ["title", "event", "reason", "snippet", "evidence", "pricing_context"]
    )
    if not text.strip():
        return False
    source = item.get("source") or ""
    if is_consumer_noise_for_business_metric({**item, "title": text, "source": source}, metric):
        return False
    if article_matches_metric({"title": text, "body_text": "", "source": source}, metric):
        return True
    try:
        confidence = float(item.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        metric in {"funding", "ma", "hiring", "terminations"}
        and source not in CONSUMER_REVIEW_SOURCES
        and confidence >= 0.9
        and bool(BUSINESS_METRIC_REQUIRED_RE.get(metric, re.compile("$^")).search(text))
    )


def apply_llm_metric_signals(
    pricing: dict[str, Any],
    features: list[dict[str, Any]],
    hiring: dict[str, Any],
    funding: list[dict[str, Any]],
    mergers: list[dict[str, Any]],
    terminations: list[dict[str, Any]],
    llm_signals: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(llm_signals, dict):
        return pricing, features, hiring, funding, mergers, terminations

    llm_pricing = as_dict(llm_signals.get("pricing") or {})
    llm_price_points = as_list(llm_pricing.get("price_points") or [])
    llm_pricing_examples = as_list(llm_pricing.get("examples") or [])
    pricing["price_points"] = list(dict.fromkeys([*(pricing.get("price_points") or []), *llm_price_points]))[:20]
    pricing["examples"] = merge_unique_events(pricing.get("examples") or [], llm_pricing_examples)[:8]
    pricing["evidence_count"] = len(pricing.get("examples") or [])

    llm_features = [
        item for item in as_list(llm_signals.get("feature_announcements") or [])
        if isinstance(item, dict) and valid_feature_signal(item)
    ]
    features = merge_unique_events(features, llm_features)[:12]

    llm_hiring = as_dict(llm_signals.get("hiring_trends") or {})
    hiring_evidence = merge_unique_events(hiring.get("evidence") or [], llm_hiring.get("evidence") or [])[:12]
    hiring_evidence = [
        item for item in hiring_evidence
        if isinstance(item, dict) and valid_metric_signal(item, "hiring")
    ][:12]
    hiring["evidence"] = hiring_evidence
    hiring["evidence_count"] = len(hiring_evidence)
    if hiring["evidence_count"] >= 5:
        hiring["trend"] = "increasing"
    elif hiring["evidence_count"]:
        hiring["trend"] = "some_activity"

    funding = merge_unique_events(
        funding,
        [
            item for item in as_list(llm_signals.get("funding") or [])
            if isinstance(item, dict) and valid_metric_signal(item, "funding")
        ],
    )[:12]
    mergers = merge_unique_events(
        mergers,
        [
            item for item in as_list(llm_signals.get("mergers") or [])
            if isinstance(item, dict) and valid_metric_signal(item, "ma")
        ],
    )[:12]
    terminations = merge_unique_events(
        terminations,
        [
            item for item in as_list(llm_signals.get("terminations") or [])
            if isinstance(item, dict) and valid_metric_signal(item, "terminations")
        ],
    )[:12]
    return pricing, features, hiring, funding, mergers, terminations


def sentiment_from_llm_signals(
    llm_signals: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    classified = [
        item for item in as_list(llm_signals.get("classified_evidence") or [])
        if isinstance(item, dict)
        and item.get("relevance") in {"competitor", "direct_comparison"}
    ]
    if not classified:
        return fallback

    counts = {"neutral": 0, "positive": 0, "negative": 0}
    for item in classified:
        sentiment = str(item.get("sentiment") or "neutral").lower()
        if sentiment not in counts:
            sentiment = "neutral"
        counts[sentiment] += 1

    total = sum(counts.values())
    if total == 0:
        return fallback

    return {
        "counts": counts,
        "percentages": {
            label: round((count / total) * 100, 2)
            for label, count in counts.items()
        },
        "total_mentions": total,
        "source": "llm_classified_google_news",
    }


def sentiment_from_mentions(
    mentions: list[dict[str, Any]],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not mentions:
        return fallback
    counts = {"neutral": 0, "positive": 0, "negative": 0}
    for mention in mentions:
        sentiment = str(mention.get("sentiment_label") or "neutral").lower()
        if sentiment not in counts:
            sentiment = "neutral"
        counts[sentiment] += 1
    total = sum(counts.values())
    if not total:
        return fallback
    return {
        "counts": counts,
        "percentages": {
            label: round((count / total) * 100, 2)
            for label, count in counts.items()
        },
        "total_mentions": total,
        "source": "roberta_validated_google_news",
    }
