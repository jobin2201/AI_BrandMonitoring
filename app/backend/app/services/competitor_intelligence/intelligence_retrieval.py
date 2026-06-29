from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.parse import quote_plus, unquote


from app.services.competitor_intelligence.competitor_logger import write_competitor_log
from app.services.competitor_intelligence.intelligence_common import *

def metric_subject_terms(
    competitor_profile: dict[str, Any],
    metric: str,
) -> list[str]:
    competitor_profile = enrich_competitor_profile(competitor_profile)
    competitor = (
        competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or ""
    ).strip()
    entity_info = infer_competitor_entity_info(competitor_profile)
    company = entity_info.get("company") or competitor_profile.get("competitor_company") or ""
    product = entity_info.get("product") or competitor_profile.get("competitor_product") or ""
    focus_terms = explicit_focus_terms(competitor_profile)
    product_terms = product_or_service_terms(competitor_profile)

    subjects: list[str] = []
    if metric in PRODUCT_LEVEL_METRICS and product_terms:
        subjects.extend(product_terms)
    elif metric in CORPORATE_LEVEL_METRICS and company:
        subjects.append(company)
    elif focus_terms:
        subjects.extend(focus_terms[:4])
        if competitor and metric in CORPORATE_LEVEL_METRICS:
            subjects.append(competitor)
    elif metric in PRODUCT_LEVEL_METRICS and product:
        subjects.append(product)
    elif metric in CORPORATE_LEVEL_METRICS and not company and product:
        return []
    else:
        subjects.append(competitor)

    expanded: list[str] = []
    for subject in subjects:
        clean_subject = subject.strip()
        if not clean_subject:
            continue
        expanded.append(clean_subject)
        if competitor and normalize(competitor) not in normalize(clean_subject):
            expanded.append(f"{competitor} {clean_subject}")
    return [term for term in dict.fromkeys(expanded) if term]


def query_specificity_score(
    query: str,
    competitor_profile: dict[str, Any],
) -> int:
    normalized_query = normalize(query)
    product_terms = product_or_service_terms(competitor_profile)
    focus_terms = explicit_focus_terms(competitor_profile)
    competitor = normalize(
        competitor_profile.get("competitor_name")
        or competitor_profile.get("competitor")
        or ""
    )
    score = 0
    if any(normalize(term) and normalize(term) in normalized_query for term in product_terms):
        score += 6
    if any(normalize(term) and normalize(term) in normalized_query for term in focus_terms):
        score += 3
    if competitor and competitor in normalized_query:
        score += 1
    if competitor and normalized_query == competitor and focus_terms:
        score -= 8
    return score


def infer_industry_key(brand: dict[str, Any] | None, competitor_profile: dict[str, Any]) -> str:
    text = " ".join(
        str(part or "")
        for part in [
            (brand or {}).get("industry"),
            (brand or {}).get("primary_category"),
            (brand or {}).get("subcategory"),
            (brand or {}).get("competitor_category"),
            " ".join((brand or {}).get("categories") or []),
            competitor_profile.get("competitor_name"),
            " ".join(competitor_profile.get("competitor_keywords") or []),
        ]
    ).lower()
    if any(term in text for term in ["cinema", "multiplex", "movie", "theatre", "theater"]):
        return "cinema"
    if any(term in text for term in ["smartphone", "phone", "mobile", "iphone", "galaxy"]):
        return "smartphone"
    if any(term in text for term in ["automotive", "car", "suv", "vehicle", "automobile"]):
        return "automotive"
    if any(term in text for term in ["ai", "artificial intelligence", "llm", "model", "cloud"]):
        return "ai"
    return ""


def fallback_metric_queries(
    competitor_profile: dict[str, Any],
    brand: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    base_terms = competitor_query_terms(competitor_profile)
    if not base_terms:
        return {}

    brand_name = (brand or {}).get("brand_name") or ""
    industry_key = infer_industry_key(brand, competitor_profile)
    max_queries = max(1, get_competitor_int_env("COMPETITOR_GOOGLE_NEWS_QUERIES_PER_METRIC", 3))
    queries: dict[str, list[str]] = {}

    for metric, terms in METRIC_QUERY_TERMS.items():
        subjects = metric_subject_terms(competitor_profile, metric)
        if not subjects:
            continue
        metric_terms = list(terms)
        metric_terms.extend(INDUSTRY_QUERY_TERMS.get(industry_key, {}).get(metric, []))
        metric_terms = [term for term in dict.fromkeys(metric_terms) if term]

        generated = []
        if metric == "comparison" and brand_name:
            generated.append(f"{subjects[0]} vs {brand_name}")
            generated.append(f"{subjects[0]} {brand_name} comparison")
        for index, term in enumerate(metric_terms):
            subject = subjects[min(index, len(subjects) - 1)]
            generated.append(f"{subject} {term}")
            if len(generated) >= max_queries:
                break
        queries[metric] = generated[:max_queries]

    return queries


def groq_generate_metric_queries(
    brand: dict[str, Any],
    competitor_profile: dict[str, Any],
) -> dict[str, list[str]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {}

    from groq import Groq

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    max_queries = max(1, get_competitor_int_env("COMPETITOR_GOOGLE_NEWS_QUERIES_PER_METRIC", 3))
    prompt = f"""
You are a competitor intelligence search query generator.

Generate Google News search queries for each metric. Queries must be specific
to the competitor and industry. Include indirect evidence queries where useful
such as expansion for hiring, locations for cinema, manufacturing for phones,
or API pricing for AI/software.

Brand:
{json.dumps(brand, indent=2, default=str)}

Competitor:
{json.dumps(competitor_profile, indent=2, default=str)}

Metric definitions:
{json.dumps(METRIC_DESCRIPTIONS, indent=2, default=str)}

Return ONLY strict JSON with these exact keys:
{{
  "pricing": [],
  "features": [],
  "hiring": [],
  "funding": [],
  "ma": [],
  "terminations": [],
  "comparison": []
}}

Rules:
- Each list must contain at most {max_queries} queries.
- Every query must include the competitor name or a competitor product/service.
- If competitor product_names, service_names, campaigns, hashtags, or keywords
  are supplied, prefer those specific terms over broad company-only searches.
- For product-level competitors, pricing/features/comparison queries must include
  the product or service name, not only the parent company.
- For company-level metrics (hiring, funding, ma, terminations), use the parent
  company name, not product/model names. Products do not raise funding, acquire
  companies, hire employees, or announce layoffs.
- Comparison queries should include the monitored brand when possible.
- Do not include explanations.
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
            "stage": "competitor_metric_query_generation",
            "model": model,
            "prompt": prompt,
            "raw_response": raw_response,
        })
        parsed = parse_json_object(raw_response)
        cleaned: dict[str, list[str]] = {}
        for metric in METRIC_QUERY_TERMS:
            values = parsed.get(metric) or []
            cleaned[metric] = [
                str(query).strip()
                for query in as_list(values)
                if str(query).strip()
            ][:max_queries]
        return cleaned
    except Exception as exc:
        write_competitor_log("fallbacks", brand["brand_id"], {
            "stage": "competitor_metric_query_generation",
            "reason": str(exc),
        })
        print(f"[COMPETITOR] Groq query generation skipped: {exc}")
        return {}


def build_metric_news_queries(
    competitor_profile: dict[str, Any],
    brand: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """
    Generate metric-specific retrieval queries. This gives each tab its own
    evidence pool instead of hoping one broad competitor search covers every
    signal.
    """
    generated = groq_generate_metric_queries(brand or {}, competitor_profile) if brand else {}
    fallback = fallback_metric_queries(competitor_profile, brand)
    merged: dict[str, list[str]] = {}
    max_queries = max(1, get_competitor_int_env("COMPETITOR_GOOGLE_NEWS_QUERIES_PER_METRIC", 3))
    entity_info = infer_competitor_entity_info(competitor_profile)
    company = entity_info.get("company") or ""
    has_product_context = bool(product_or_service_terms(competitor_profile) or entity_info.get("product"))

    for metric in METRIC_QUERY_TERMS:
        if metric in CORPORATE_LEVEL_METRICS and company and has_product_context:
            values = fallback.get(metric) or []
        else:
            values = [*(generated.get(metric) or []), *(fallback.get(metric) or [])]
        unique_values = [
            query for query in dict.fromkeys(str(value).strip() for value in values)
            if query
        ]
        unique_values.sort(
            key=lambda query: query_specificity_score(query, competitor_profile),
            reverse=True,
        )
        merged[metric] = unique_values[:max_queries]

    context_terms = metric_subject_terms(competitor_profile, "features")
    if context_terms:
        brand_name = (brand or {}).get("brand_name") or ""
        context_queries = [context_terms[0]]
        if brand_name:
            context_queries.append(f"{context_terms[0]} {brand_name}")
        merged["general_context"] = [
            query for query in dict.fromkeys(context_queries)
            if query
        ][:2]
    return merged


def _google_news_search_for_competitor(query: str) -> list[dict[str, Any]]:
    """
    Reuse the existing Google News scraper without changing it. Competitor
    intelligence runs in a sync FastAPI worker, so asyncio.run mirrors the
    existing route's async wrapper behavior.
    """
    from app.api.google_news.google_news_scraper import _google_news_search_async

    return asyncio.run(_google_news_search_async(query))


def _newsapi_articles_for_competitor(query: str) -> list[dict[str, Any]]:
    try:
        from app.api.routes.articles import get_articles

        payload = get_articles(brand=query)
        articles = payload.get("newsapi_results") if isinstance(payload, dict) else []
        return [
            {
                "title": item.get("title") or "",
                "body_text": item.get("description") or item.get("body_text") or "",
                "source": "newsapi",
                "source_name": item.get("source_name") or "NewsAPI",
                "published_at": item.get("published_at") or "",
                "url": item.get("url") or "",
            }
            for item in (articles or [])
        ]
    except Exception as exc:
        print(f"[COMPETITOR][NEWSAPI] Articles route fallback failed for {query}: {exc}")
        return []


def _youtube_videos_for_competitor(query: str) -> list[dict[str, Any]]:
    try:
        from app.api.youtube.youtube_scraper import get_channel_stats, search_videos

        videos = search_videos(query, max_results=10, order="relevance")
        stats = get_channel_stats([video.get("channelId") for video in videos])
        return [
            {
                "title": video.get("title") or "",
                "body_text": "",
                "source": "youtube",
                "source_name": video.get("channelTitle") or "",
                "published_at": video.get("published") or "",
                "url": f"https://www.youtube.com/watch?v={video.get('video_id') or ''}",
                "subscriber_count": stats.get(video.get("channelId"), {}).get("subscriber_count", 0),
            }
            for video in videos
        ]
    except Exception as exc:
        print(f"[COMPETITOR][YOUTUBE] Search fallback failed for {query}: {exc}")
        return []


def _web_search_for_competitor(query: str) -> list[dict[str, Any]]:
    try:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            },
        )
        with urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")

        items = []
        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html):
            href = unquote(match.group("href"))
            title = re.sub(r"<[^>]+>", " ", match.group("title"))
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue
            items.append({
                "title": title,
                "body_text": "",
                "source": "web_search",
                "source_name": "DuckDuckGo",
                "published_at": "",
                "url": href,
            })
            if len(items) >= 10:
                break
        return items
    except Exception as exc:
        print(f"[COMPETITOR][WEB] Web search fallback failed for {query}: {exc}")
        return []


def _reddit_json_posts_for_competitor(query: str) -> list[dict[str, Any]]:
    try:
        url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=relevance&limit=10"
        request = Request(
            url,
            headers={
                "User-Agent": "brand-monitoring-competitor-intelligence/1.0",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))

        posts = []
        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            permalink = data.get("permalink") or ""
            posts.append({
                "title": data.get("title") or "",
                "body_text": data.get("selftext") or "",
                "source": "reddit",
                "source_name": f"r/{data.get('subreddit')}" if data.get("subreddit") else "Reddit",
                "published_at": "",
                "url": f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink,
            })
        return posts
    except Exception as exc:
        print(f"[COMPETITOR][REDDIT] Reddit JSON search failed for {query}: {exc}")
        return []


def _reddit_google_news_posts_for_competitor(query: str) -> list[dict[str, Any]]:
    try:
        items = _google_news_search_for_competitor(f"site:reddit.com {query}")
        return [
            {
                "title": item.get("title") or "",
                "body_text": item.get("body_text") or item.get("description") or "",
                "source": "reddit",
                "source_name": item.get("source_name") or "Reddit via Google News",
                "published_at": item.get("published_at") or "",
                "url": item.get("url") or "",
            }
            for item in items
        ]
    except Exception as exc:
        print(f"[COMPETITOR][REDDIT] Google News reddit fallback failed for {query}: {exc}")
        return []


async def _reddit_posts_for_competitor_async(query: str) -> list[dict[str, Any]]:
    from playwright.async_api import async_playwright

    from app.api.reddit.reddit_scraper import (
        close_consent_popup,
        extract_post,
        extract_post_links,
    )

    results: list[dict[str, Any]] = []
    search_url = f"https://www.reddit.com/search/?q={quote_plus(query)}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1024},
            java_script_enabled=True,
            locale="en-US",
        )
        page = await context.new_page()
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await close_consent_popup(page)
            for _ in range(3):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(900)
            post_links = (await extract_post_links(page))[:5]
            for post_url in post_links:
                post = await extract_post(context, query, post_url)
                if not post:
                    continue
                results.append({
                    "title": post.get("content") or "",
                    "body_text": post.get("content") or "",
                    "source": "reddit",
                    "source_name": post.get("username") or "Reddit",
                    "published_at": post.get("date") or "",
                    "url": post.get("url") or post_url,
                })
                if len(results) >= 5:
                    break
        finally:
            await browser.close()
    return results


def _reddit_posts_for_competitor(query: str) -> list[dict[str, Any]]:
    posts = _reddit_json_posts_for_competitor(query)
    if posts:
        return posts
    return _reddit_google_news_posts_for_competitor(query)


def _append_source_items(
    *,
    items: list[dict[str, Any]],
    source: str,
    metric: str,
    query: str,
    competitor_profile: dict[str, Any],
    all_mentions: list[dict[str, Any]],
    seen: set,
    per_metric_remaining: int,
) -> tuple[int, int, int]:
    accepted = 0
    rejected_wrong_profile = 0
    rejected_wrong_metric = 0
    for item in items:
        if accepted >= per_metric_remaining:
            break
        if not article_matches_profile(item, competitor_profile):
            rejected_wrong_profile += 1
            continue
        metric_candidate = False
        if not article_matches_metric(item, metric):
            if metric in CORPORATE_LEVEL_METRICS and is_business_fallback_candidate(item, metric):
                metric_candidate = True
            else:
                rejected_wrong_metric += 1
                continue

        title = item.get("title") or ""
        url = item.get("url") or ""
        key = url or normalize(title)
        if not key or key in seen:
            continue
        seen.add(key)
        all_mentions.append({
            "title": title,
            "body_text": item.get("body_text") or "",
            "source": source,
            "source_name": item.get("source_name") or item.get("source") or "",
            "sentiment_label": "",
            "sentiment_score": None,
            "primary_category": "competitor_intelligence",
            "emotion": "",
            "relevance_score": None,
            "published_at": item.get("published_at") or "",
            "url": url,
            "metric": metric,
            "query": query,
            "metric_candidate": metric_candidate,
            "match_type": f"{source}_metric_evidence",
        })
        if not metric_candidate:
            accepted += 1
    return accepted, rejected_wrong_profile, rejected_wrong_metric


def collect_metric_google_news_evidence(
    brand_id: str,
    competitor_profile: dict[str, Any],
    brand: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if os.getenv("COMPETITOR_GOOGLE_NEWS_ENABLED", "true").lower() in {"0", "false", "no"}:
        return [], {"enabled": False, "reason": "disabled_by_env"}

    started = time.perf_counter()
    queries = build_metric_news_queries(competitor_profile, brand)
    min_evidence_per_metric = max(
        1,
        get_competitor_int_env("COMPETITOR_MIN_EVIDENCE_PER_METRIC", 3),
    )
    per_metric_limit = max(
        min_evidence_per_metric,
        get_competitor_int_env("COMPETITOR_GOOGLE_NEWS_RESULTS_PER_METRIC", 8),
    )
    all_mentions: list[dict[str, Any]] = []
    source_runs: dict[str, list[dict[str, Any]]] = {}
    seen = set()

    for metric, metric_queries in queries.items():
        source_runs[metric] = []
        accepted_for_metric = 0
        for query in metric_queries:
            query_started = time.perf_counter()
            raw_items: list[dict[str, Any]] = []
            error = ""
            try:
                raw_items = _google_news_search_for_competitor(query)
            except Exception as exc:
                error = str(exc)
                print(f"[COMPETITOR][GOOGLE_NEWS] {metric} query failed: {exc}")

            accepted = 0
            rejected_wrong_profile = 0
            rejected_wrong_metric = 0
            for item in raw_items:
                if not article_matches_profile(item, competitor_profile):
                    rejected_wrong_profile += 1
                    continue
                metric_candidate = False
                if not article_matches_metric(item, metric):
                    if metric in CORPORATE_LEVEL_METRICS and is_business_fallback_candidate(item, metric):
                        metric_candidate = True
                    else:
                        rejected_wrong_metric += 1
                        continue

                title = item.get("title") or ""
                url = item.get("url") or ""
                key = url or normalize(title)
                if not key or key in seen:
                    continue
                seen.add(key)
                mention = {
                    "title": title,
                    "body_text": item.get("body_text") or "",
                    "source": "google_news",
                    "source_name": item.get("source_name") or item.get("source") or "",
                    "sentiment_label": "",
                    "sentiment_score": None,
                    "primary_category": "competitor_intelligence",
                    "emotion": "",
                    "relevance_score": None,
                    "published_at": item.get("published_at") or "",
                    "url": url,
                    "metric": metric,
                    "query": query,
                    "metric_candidate": metric_candidate,
                    "match_type": "google_news_metric_evidence",
                }
                all_mentions.append(mention)
                if not metric_candidate:
                    accepted += 1
                    accepted_for_metric += 1
                if accepted_for_metric >= per_metric_limit:
                    break

            source_runs[metric].append({
                "query": query,
                "raw_found": len(raw_items),
                "accepted": accepted,
                "rejected_wrong_profile": rejected_wrong_profile,
                "rejected_wrong_metric": rejected_wrong_metric,
                "error": error,
                "duration_ms": round((time.perf_counter() - query_started) * 1000, 2),
            })
            if accepted_for_metric >= per_metric_limit:
                break

        def run_fallback_source(source_label: str, source_name: str, fetcher) -> None:
            nonlocal accepted_for_metric
            if metric == "general_context" or accepted_for_metric >= per_metric_limit:
                return
            for fallback_query in metric_queries:
                if accepted_for_metric >= per_metric_limit:
                    break
                if not fallback_query:
                    continue
                remaining = per_metric_limit - accepted_for_metric
                query_started = time.perf_counter()
                error = ""
                try:
                    items = fetcher(fallback_query)
                except Exception as exc:
                    error = str(exc)
                    items = []
                accepted, rejected_profile, rejected_metric = _append_source_items(
                    items=items,
                    source=source_label,
                    metric=metric,
                    query=fallback_query,
                    competitor_profile=competitor_profile,
                    all_mentions=all_mentions,
                    seen=seen,
                    per_metric_remaining=remaining,
                )
                accepted_for_metric += accepted
                source_runs[metric].append({
                    "query": fallback_query,
                    "source": source_name,
                    "raw_found": len(items),
                    "accepted": accepted,
                    "rejected_wrong_profile": rejected_profile,
                    "rejected_wrong_metric": rejected_metric,
                    "error": error,
                    "duration_ms": round((time.perf_counter() - query_started) * 1000, 2),
                })

        run_fallback_source("newsapi", "newsapi_route", _newsapi_articles_for_competitor)
        run_fallback_source("web_search", "web_search", _web_search_for_competitor)
        run_fallback_source("reddit", "reddit_live", _reddit_posts_for_competitor)
        run_fallback_source("youtube", "youtube_search", _youtube_videos_for_competitor)

    summary = {
        "enabled": True,
        "min_evidence_per_metric": min_evidence_per_metric,
        "per_metric_limit": per_metric_limit,
        "env_path": str(BACKEND_ENV_PATH),
        "queries": queries,
        "runs": source_runs,
        "retrieved": len(all_mentions),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    log_path = write_competitor_log("retrieval", brand_id, {
        "stage": "metric_google_news_retrieval",
        "competitor_profile": competitor_profile,
        "summary": summary,
        "items": all_mentions[:50],
    })
    print(f"[COMPETITOR] Metric retrieval log -> {log_path}")
    return all_mentions, summary
