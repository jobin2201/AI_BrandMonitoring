from __future__ import annotations

import time
from typing import Any

from app.services.competitor_intelligence.analyzers.feature_analyzer import feature_announcements
from app.services.competitor_intelligence.analyzers.funding_analyzer import funding_events
from app.services.competitor_intelligence.analyzers.hiring_analyzer import hiring_trends
from app.services.competitor_intelligence.analyzers.merger_analyzer import merger_events
from app.services.competitor_intelligence.analyzers.pricing_analyzer import pricing_intelligence
from app.services.competitor_intelligence.analyzers.sentiment_analyzer import sentiment_breakdown
from app.services.competitor_intelligence.analyzers.sov_analyzer import share_of_voice
from app.services.competitor_intelligence.analyzers.termination_analyzer import termination_events
from app.services.competitor_intelligence.competitor_detector import load_brand_context
from app.services.competitor_intelligence.competitor_logger import (
    append_competitor_log,
    write_competitor_log,
)
from app.services.competitor_intelligence.intelligence_common import *
from app.services.competitor_intelligence.intelligence_retrieval import collect_metric_google_news_evidence
from app.services.competitor_intelligence.intelligence_signals import (
    apply_llm_metric_signals,
    apply_no_evidence_status,
    apply_roberta_sentiment,
    classified_signals_from_mentions,
    dedupe_events,
    llm_extract_metric_signals,
    sentiment_from_llm_signals,
    sentiment_from_mentions,
    validate_competitor_evidence,
)

def generate_competitor_intelligence(
    brand_id: str,
    competitor_profile: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    brand = load_brand_context(brand_id)
    competitor_profile = enrich_competitor_profile(competitor_profile)
    try:
        terms = keyword_terms(competitor_profile)
        explicit_product_terms = product_or_service_terms(competitor_profile)
        if not explicit_product_terms:
            terms = [*terms, *product_family_terms(terms)]
        brand_terms = brand_identity_terms(brand)
        brand_mentions = safe_metric_step("load_brand_mentions", [], load_brand_mentions, brand_id)
        # Competitor intelligence should use fresh live evidence for competitor
        # sources. Do not reuse older competitor rows from brand_mentions here.
        competitor_mentions: list[dict[str, Any]] = []
        direct_comparisons: list[dict[str, Any]] = []
        metric_news_mentions, metric_retrieval_summary = safe_metric_step(
            "metric_google_news_retrieval",
            ([], {"enabled": False, "reason": "retrieval_failed"}),
            collect_metric_google_news_evidence,
            brand_id,
            competitor_profile,
            brand,
        )
        wikipedia_context = safe_metric_step(
            "wikipedia_competitor_context",
            {},
            get_competitor_wikipedia_context,
            competitor_profile,
        )
        wikipedia_terms = []
        if isinstance(wikipedia_context, dict):
            wikipedia_terms = [
                wikipedia_context.get("entity_name") or "",
                *(wikipedia_context.get("search_terms") or []),
            ]
        raw_context_terms = [
            *wikipedia_context_terms(wikipedia_context),
            *explicit_focus_terms(competitor_profile),
        ]
        competitor_name_norm = normalize(
            competitor_profile.get("competitor_name")
            or competitor_profile.get("competitor")
            or ""
        )
        entity_context_terms = [
            term for term in dict.fromkeys(raw_context_terms)
            if normalize(term) and normalize(term) != competitor_name_norm
        ]
        require_entity_context = (
            requires_context_disambiguation(competitor_profile)
            and bool(entity_context_terms)
        )
        validation_competitor_terms = [*terms, *wikipedia_terms]
        if not explicit_product_terms:
            validation_competitor_terms = [
                *validation_competitor_terms,
                *product_family_terms(validation_competitor_terms),
            ]
        required_metric_terms = {
            metric: explicit_product_terms
            for metric in PRODUCT_LEVEL_METRICS
            if explicit_product_terms
        }
        metric_news_mentions, validation_summary = safe_metric_step(
            "gliner_relevance_validation",
            ([], {"input": len(metric_news_mentions), "kept": 0, "rejected": len(metric_news_mentions)}),
            validate_competitor_evidence,
            metric_news_mentions,
            brand_terms,
            validation_competitor_terms,
            required_metric_terms,
            entity_context_terms,
            require_entity_context,
        )
        metric_news_mentions = safe_metric_step(
            "roberta_competitor_sentiment",
            metric_news_mentions,
            apply_roberta_sentiment,
            metric_news_mentions,
        )
        competitor_mentions = [
            mention for mention in metric_news_mentions
            if mention.get("classification") not in {"", "general", None}
            or mention.get("relevance") == "direct_comparison"
        ]
        direct_comparisons = [
            mention for mention in metric_news_mentions
            if mention.get("classification") == "comparison"
            or mention.get("relevance") == "direct_comparison"
        ]
        metric_mentions = metric_news_mentions
        local_signals = classified_signals_from_mentions(metric_news_mentions)

        def metric_subset(metric: str) -> list[dict[str, Any]]:
            return [
                mention for mention in metric_mentions
                if mention.get("classification") == metric
            ]

        sentiment = safe_metric_step("sentiment_breakdown", {
            "counts": {"neutral": 0, "positive": 0, "negative": 0},
            "percentages": {"neutral": 0.0, "positive": 0.0, "negative": 0.0},
            "total_mentions": 0,
        }, sentiment_breakdown, competitor_mentions)
        sentiment = sentiment_from_mentions(metric_news_mentions, sentiment)
        sov = safe_metric_step("share_of_voice", {
            "brand": 0,
            "competitor": 0,
            "brand_mentions": len(brand_mentions),
            "competitor_mentions": len(competitor_mentions),
        }, share_of_voice, len(brand_mentions), len(competitor_mentions))
        pricing = safe_metric_step("pricing_intelligence", empty_pricing(), pricing_intelligence, metric_subset("pricing"))
        features = safe_metric_step("feature_announcements", [], feature_announcements, metric_subset("features"))
        hiring = safe_metric_step("hiring_trends", empty_hiring(), hiring_trends, metric_subset("hiring"))
        funding = safe_metric_step("funding_events", [], funding_events, metric_subset("funding"))
        mergers = safe_metric_step("merger_events", [], merger_events, metric_subset("ma"))
        terminations = safe_metric_step("termination_events", [], termination_events, metric_subset("terminations"))
        pricing, features, hiring, funding, mergers, terminations = safe_metric_step(
            "apply_local_metric_classification",
            (pricing, features, hiring, funding, mergers, terminations),
            apply_llm_metric_signals,
            pricing,
            features,
            hiring,
            funding,
            mergers,
            terminations,
            {
                "pricing": local_signals["pricing"],
                "feature_announcements": local_signals["features"],
                "hiring_trends": local_signals["hiring"],
                "funding": local_signals["funding"],
                "mergers": local_signals["mergers"],
                "terminations": local_signals["terminations"],
            },
        )
        evidence_target = int(metric_retrieval_summary.get("min_evidence_per_metric") or 3)
        local_metric_counts = {
            "pricing": len(pricing.get("examples") or []),
            "features": len(features),
            "hiring": len(hiring.get("evidence") or []),
            "funding": len(funding),
            "ma": len(mergers),
            "terminations": len(terminations),
            "comparison": len(local_signals["direct_comparisons"]),
        }
        underfilled_metrics = {
            metric for metric, count in local_metric_counts.items()
            if count < evidence_target
        }
        llm_input_mentions = [
            mention for mention in metric_mentions
            if mention.get("metric") in underfilled_metrics
            or mention.get("classification") in underfilled_metrics
        ]
        llm_signals = (
            llm_extract_metric_signals(brand, competitor_profile, llm_input_mentions)
            if underfilled_metrics and llm_input_mentions
            else {}
        )
        llm_direct_comparisons = local_signals["direct_comparisons"]
        llm_classified_evidence = [
            {
                "title": mention.get("title") or "",
                "url": mention.get("url") or "",
                "source": mention.get("source") or "",
                "relevance": mention.get("relevance") or "",
                "tabs": [mention.get("classification") or "general"],
                "sentiment": mention.get("sentiment_label") or "",
                "reason": mention.get("classification_reason") or mention.get("validation_reason") or "",
                "confidence": mention.get("classification_confidence"),
            }
            for mention in metric_news_mentions[:20]
        ]
        if llm_signals:
            sentiment = sentiment_from_llm_signals(llm_signals, sentiment)
            llm_direct_comparisons = [
                item for item in as_list(llm_signals.get("direct_comparisons") or [])
                if isinstance(item, dict)
                and article_matches_metric(
                    {
                        "title": " ".join(
                            str(item.get(field) or "")
                            for field in ["title", "reason", "snippet", "evidence"]
                        )
                    },
                    "comparison",
                )
            ]
            llm_classified_evidence = [
                item for item in as_list(llm_signals.get("classified_evidence") or [])
                if isinstance(item, dict)
            ]
            pricing, features, hiring, funding, mergers, terminations = safe_metric_step(
                "apply_llm_metric_signals",
                (pricing, features, hiring, funding, mergers, terminations),
                apply_llm_metric_signals,
                pricing,
                features,
                hiring,
                funding,
                mergers,
                terminations,
                llm_signals,
            )
        pricing, features, hiring, funding, mergers, terminations = apply_no_evidence_status(
            pricing,
            features,
            hiring,
            funding,
            mergers,
            terminations,
            metric_retrieval_summary,
            [*metric_news_mentions, *competitor_mentions],
        )
        pricing["examples"] = dedupe_events(pricing.get("examples") or [], 8)
        pricing["evidence_count"] = len(pricing.get("examples") or [])
        features = dedupe_events(features, 12)
        hiring["evidence"] = dedupe_events(hiring.get("evidence") or [], 12)
        hiring["evidence_count"] = len(hiring.get("evidence") or [])
        funding = dedupe_events(funding, 12)
        mergers = dedupe_events(mergers, 12)
        terminations = dedupe_events(terminations, 12)
        direct_comparisons = dedupe_events(direct_comparisons, 50)
        llm_direct_comparisons = dedupe_events(llm_direct_comparisons, 12)
        llm_classified_evidence = dedupe_events(llm_classified_evidence, 20)
    except Exception as exc:
        result = empty_intelligence_result(brand_id, brand, competitor_profile, str(exc))
        log_path = write_competitor_log("fallbacks", brand_id, {
            "stage": "competitor_intelligence",
            "reason": str(exc),
            "result": result,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        append_competitor_log("competitor_intelligence_fallback", {
            "brand_id": brand_id,
            "competitor": result["competitor"],
            "error": str(exc),
            "path": log_path,
        })
        print(f"[COMPETITOR] Intelligence fallback -> {log_path}")
        return result

    result = {
        "brand_id": brand_id,
        "brand": brand.get("brand_name"),
        "competitor": competitor_profile.get("competitor_name") or competitor_profile.get("competitor") or "",
        "keywords": terms,
        "metric_descriptions": METRIC_DESCRIPTIONS,
        "sentiment": sentiment,
        "share_of_voice": sov,
        "pricing": pricing,
        "feature_announcements": features,
        "hiring_trends": hiring,
        "funding": funding,
        "mergers": mergers,
        "terminations": terminations,
        "temporary": True,
        "stored": False,
        "evidence": {
            "brand_mentions_scanned": len(brand_mentions),
            "competitor_mentions_matched": len(competitor_mentions),
            "metric_google_news_mentions": len(metric_news_mentions),
            "metric_retrieval_summary": metric_retrieval_summary,
            "gliner_validation_summary": validation_summary,
            "wikipedia_context": wikipedia_context,
            "direct_comparison_mentions": len(direct_comparisons) + len(llm_direct_comparisons),
            "competitor_examples": [
                evidence_item(mention, mention.get("match_type") or "keyword_mention")
                for mention in competitor_mentions[:8]
            ],
            "direct_comparison_examples": [
                evidence_item(mention, "direct_comparison")
                for mention in direct_comparisons[:8]
            ] + llm_direct_comparisons[:8],
            "pricing_examples": pricing.get("examples") or [],
            "feature_examples": features[:8],
            "hiring_examples": hiring.get("evidence") or [],
            "funding_examples": funding[:8],
            "merger_examples": mergers[:8],
            "termination_examples": terminations[:8],
            "metric_google_news_examples": [
                evidence_item(mention, mention.get("metric") or "metric_google_news")
                for mention in metric_news_mentions[:12]
            ],
            "classified_evidence_examples": llm_classified_evidence,
            "llm_metric_signal_used": bool(llm_signals),
        },
    }

    log_path = write_competitor_log("intelligence", brand_id, {
        "brand": brand,
        "competitor_profile": competitor_profile,
        "result": result,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    })
    write_competitor_log("traces", brand_id, {
        "stage": "competitor_intelligence",
        "status": "success",
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "steps": [
            {"step": "load_brand_context", "status": "success"},
            {"step": "load_brand_mentions", "status": "success", "count": len(brand_mentions)},
            {
                "step": "live_competitor_evidence",
                "status": "success",
                "count": len(competitor_mentions),
                "direct_comparisons": len(direct_comparisons),
            },
            {
                "step": "metric_google_news_retrieval",
                "status": "success" if metric_retrieval_summary.get("enabled") else "skipped",
                "count": len(metric_news_mentions),
                "summary": metric_retrieval_summary,
            },
            {
                "step": "wikipedia_competitor_context",
                "status": "success" if wikipedia_context else "skipped_or_empty",
                "context": wikipedia_context,
            },
            {
                "step": "gliner_relevance_validation",
                "status": "success",
                "summary": validation_summary,
            },
            {
                "step": "roberta_sentiment",
                "status": "success" if any(
                    mention.get("sentiment_source") == "roberta"
                    for mention in metric_news_mentions
                ) else "skipped_or_unavailable",
            },
            {
                "step": "local_metric_classification",
                "status": "success",
                "classified_count": len(metric_news_mentions),
            },
            {"step": "analyze_metrics", "status": "success"},
            {"step": "llm_metric_signal_extraction", "status": "success" if llm_signals else "skipped_or_empty"},
            {"step": "write_intelligence_log", "status": "success", "path": log_path},
        ],
    })
    append_competitor_log("competitor_intelligence_complete", {
        "brand_id": brand_id,
        "competitor": result["competitor"],
        "competitor_mentions": len(competitor_mentions),
    })
    print(f"[COMPETITOR] Intelligence log -> {log_path}")
    return result
