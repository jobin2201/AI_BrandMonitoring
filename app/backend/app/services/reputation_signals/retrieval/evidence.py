from __future__ import annotations

import asyncio
import concurrent.futures
import os
import sys
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import psycopg2

from app.services.competitor_intelligence.intelligence_common import normalize
from app.services.competitor_intelligence.intelligence_retrieval import (
    _google_news_search_for_competitor,
    _youtube_videos_for_competitor,
)
from app.services.reputation_signals.reputation_common import dedupe_items
from app.services.reputation_signals.engine.common import (
    DEFAULT_CATEGORY_EVIDENCE_LIMIT,
    DEFAULT_REPUTATION_CATEGORY_WORKERS,
    DEFAULT_REPUTATION_QUERY_WORKERS,
    DEFAULT_REPUTATION_SOURCE_WORKERS,
    DEFAULT_RESULTS_PER_SOURCE,
    REPUTATION_SOURCES_BY_CATEGORY,
    get_newsapi_disabled_until,
    set_newsapi_disabled_until,
)
from app.services.reputation_signals.retrieval.entity_validation import (
    _reputation_relevance_score,
    _validate_article_against_resolved_entity,
)
from app.services.reputation_signals.observability.logger import write_reputation_log
from app.services.reputation_signals.retrieval.query_planner import _queries
from app.services.reputation_signals.retrieval.query_planner import _product_aliases
from app.services.reputation_signals.retrieval.query_planner import _subjects

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


PRODUCT_VALIDATED_CATEGORIES = {"product", "complaints", "security"}


def _stored_evidence_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def _stored_evidence_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return f"url:{url}"
    title = normalize(str(item.get("title") or ""))
    if not title:
        return ""
    source_name = normalize(str(
        item.get("source_name")
        or item.get("author")
        or item.get("source")
        or ""
    ))
    published_at = str(item.get("published_at") or "").strip()[:10]
    return f"title:{title}|source:{source_name}|date:{published_at}"


def _merge_evidence_origin(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    origins = []
    for item in [existing, incoming]:
        value = str(item.get("evidence_origin") or "").strip()
        origins.extend(part for part in value.split("+") if part)
    merged_origins = list(dict.fromkeys(origins))
    preferred = incoming if len(str(incoming.get("body_text") or incoming.get("snippet") or "")) > len(
        str(existing.get("body_text") or existing.get("snippet") or "")
    ) else existing
    other = existing if preferred is incoming else incoming
    return {
        **other,
        **preferred,
        "evidence_origin": "+".join(merged_origins) or "live",
        "stored_evidence": "stored" in merged_origins,
        "live_evidence": "live" in merged_origins,
    }


def _merge_category_evidence(
    stored_items: list[dict[str, Any]],
    live_items: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    merged: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for item in [*stored_items, *live_items]:
        key = _stored_evidence_key(item)
        if not key:
            continue
        if key in merged:
            duplicate_count += 1
            merged[key] = _merge_evidence_origin(merged[key], item)
        else:
            merged[key] = item
    deduped = dedupe_items(list(merged.values()), limit)
    return deduped, {
        "stored": len(stored_items),
        "live": len(live_items),
        "before_dedupe": len(stored_items) + len(live_items),
        "duplicates_merged": duplicate_count,
        "deduped": len(deduped),
    }


def _load_stored_evidence_rows(
    brand_id: str,
    days: int,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    conn = None
    cur = None
    try:
        conn = _stored_evidence_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                bm.title,
                bm.url,
                bm.source,
                bm.published_at,
                bm.body_text,
                bm.author,
                bm.collected_at,
                bm.relevance_score,
                bm.semantic_score,
                bm.match_confidence,
                bm.match_reason,
                bm.matched_terms,
                a.title,
                a.body_text,
                a.source_name,
                a.author,
                a.published_at
            FROM brand_mentions bm
            LEFT JOIN articles a ON a.url = bm.url
            WHERE bm.brand_id = %s
              AND COALESCE(bm.published_at, bm.collected_at) >= NOW() - (%s * INTERVAL '1 day')
            ORDER BY bm.collected_at DESC
            LIMIT %s
            """,
            (brand_id, days, limit),
        )
        items = []
        for row in cur.fetchall():
            published_at = row[3] or row[16] or row[6]
            items.append({
                "title": row[0] or row[12] or "",
                "url": row[1] or "",
                "source": row[2] or "stored",
                "source_name": row[14] or row[5] or row[15] or row[2] or "Stored mention",
                "body_text": row[4] or row[13] or "",
                "snippet": row[4] or row[13] or "",
                "description": row[13] or row[4] or "",
                "author": row[5] or row[15] or "",
                "published_at": published_at.isoformat() if hasattr(published_at, "isoformat") else str(published_at or ""),
                "collected_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6] or ""),
                "stored_relevance_score": row[7],
                "stored_semantic_score": row[8],
                "match_confidence": row[9],
                "match_reason": row[10] or "",
                "matched_terms": row[11] or [],
                "evidence_origin": "stored",
                "stored_evidence": True,
                "live_evidence": False,
            })
        return items, {
            "enabled": True,
            "rows_loaded": len(items),
            "days": days,
            "limit": limit,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": "",
        }
    except Exception as exc:
        print(f"[REPUTATION][STORED] Stored evidence unavailable: {exc}")
        return [], {
            "enabled": False,
            "rows_loaded": 0,
            "days": days,
            "limit": limit,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
        }
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def _collect_stored_evidence(
    brand_id: str,
    profile: dict[str, Any],
    categories: list[str],
    category_limit: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    days = max(1, int(os.getenv("REPUTATION_STORED_EVIDENCE_DAYS", "30")))
    row_limit = max(
        category_limit,
        int(os.getenv("REPUTATION_STORED_EVIDENCE_LIMIT", "300")),
    )
    rows, load_summary = _load_stored_evidence_rows(brand_id, days, row_limit)
    evidence: dict[str, list[dict[str, Any]]] = {}
    category_summary: dict[str, dict[str, Any]] = {}
    for category in categories:
        validation_profile = _category_validation_profile(profile, category)
        accepted = []
        rejected_stale = 0
        rejected_validation = 0
        rejected_relevance = 0
        for original in rows:
            item = dict(original)
            is_recent, recency_reason = _is_recent_reputation_item(item)
            if not is_recent:
                rejected_stale += 1
                continue
            is_valid, validation_reason = _validate_article_against_resolved_entity(
                item,
                validation_profile,
            )
            if not is_valid:
                rejected_validation += 1
                continue
            score, relevance_reason = _reputation_relevance_score(
                item,
                validation_profile,
                category,
            )
            if score < 0.5:
                rejected_relevance += 1
                continue
            item.update({
                "reputation_relevance_score": score,
                "reputation_relevance_reason": relevance_reason,
                "recency_reason": recency_reason,
                "entity_validation_reason": validation_reason,
                "validation_mode": validation_profile.get("entity_type") or "",
                "validation_target": validation_profile.get("competitor_name") or "",
                "matched_company": validation_profile.get("competitor_company") or "",
                "matched_product": validation_profile.get("competitor_product") or "",
                "product_aliases": validation_profile.get("product_aliases") or [],
            })
            accepted.append(item)
        evidence[category] = dedupe_items(accepted, category_limit)
        category_summary[category] = {
            "rows_considered": len(rows),
            "accepted": len(evidence[category]),
            "rejected_stale": rejected_stale,
            "rejected_entity_validation": rejected_validation,
            "rejected_relevance": rejected_relevance,
        }
    summary = {
        **load_summary,
        "categories": category_summary,
        "accepted_total": sum(len(items) for items in evidence.values()),
        "accepted_unique": len({
            _stored_evidence_key(item)
            for items in evidence.values()
            for item in items
            if _stored_evidence_key(item)
        }),
        "samples": [
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "source": item.get("source") or "",
                "source_name": item.get("source_name") or "",
                "published_at": item.get("published_at") or "",
            }
            for item in rows[:10]
        ],
    }
    print(
        "[REPUTATION][STORED] "
        f"loaded={summary['rows_loaded']} "
        f"accepted_unique={summary['accepted_unique']}"
    )
    return evidence, summary


def _category_validation_profile(profile: dict[str, Any], category: str) -> dict[str, Any]:
    subjects = _subjects(profile)
    company = subjects.get("company") or ""
    product = subjects.get("product") or ""
    if not product:
        return profile

    category_profile = dict(profile)
    product_aliases = _product_aliases(product, company)
    if category in PRODUCT_VALIDATED_CATEGORIES:
        category_profile["entity_type"] = "product"
        category_profile["competitor_name"] = product
        category_profile["competitor_product"] = product
        category_profile["competitor_company"] = company or profile.get("competitor_company") or ""
        category_profile["product_names"] = list(dict.fromkeys([
            product,
            *product_aliases,
            *(profile.get("product_names") or []),
        ]))
        category_profile["product_aliases"] = product_aliases
        category_profile["aliases"] = list(dict.fromkeys([
            product,
            *product_aliases,
            *(profile.get("aliases") or []),
        ]))
        category_profile["_reputation_subjects"] = {
            "company": company,
            "product": product,
            "primary": product,
        }
        return category_profile

    category_profile["entity_type"] = "company"
    category_profile["competitor_name"] = company or profile.get("competitor_company") or profile.get("competitor_name") or ""
    category_profile["competitor_company"] = category_profile["competitor_name"]
    category_profile["competitor_product"] = ""
    category_profile["product_names"] = []
    category_profile["service_names"] = []
    category_profile["_reputation_subjects"] = {
        "company": category_profile["competitor_company"],
        "product": "",
        "primary": category_profile["competitor_company"],
    }
    return category_profile


def _item_age_days(item: dict[str, Any]) -> float | None:
    raw_date = str(item.get("published_at") or item.get("publishedAt") or "").strip()
    if not raw_date:
        return None
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw_date)
        except Exception:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return max(0.0, (datetime.utcnow() - parsed).total_seconds() / 86400)


def _is_recent_reputation_item(item: dict[str, Any]) -> tuple[bool, str]:
    max_age_days = int(os.getenv("REPUTATION_MAX_ARTICLE_AGE_DAYS", "365"))
    if max_age_days <= 0:
        return True, "recency_filter_disabled"
    age_days = _item_age_days(item)
    if age_days is None:
        return True, "missing_or_unparseable_date"
    if age_days > max_age_days:
        return False, f"stale_article:{round(age_days, 1)}d>{max_age_days}d"
    return True, f"recent_article:{round(age_days, 1)}d"


async def _google_news_search_with_page(page, query: str, timeout_ms: int) -> list[dict[str, Any]]:
    encoded = quote(query)
    search_url = (
        "https://news.google.com/search"
        f"?q={encoded}&hl=en-IN&gl=IN&ceid=IN%3Aen"
    )
    await page.goto(search_url, timeout=timeout_ms, wait_until="domcontentloaded")
    await page.wait_for_timeout(1800)
    try:
        await page.wait_for_selector("a.WwrzSb, a.JtKRv", timeout=min(timeout_ms, 5000))
    except Exception:
        pass
    for _ in range(3):
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(350)

    raw = await page.evaluate(
        """
        () => {
            const results = [];
            const seen = new Set();

            function fixHref(href) {
                if (!href) return null;
                href = href.trim();
                if (href.startsWith('./')) return 'https://news.google.com' + href.slice(1);
                if (href.startsWith('/')) return 'https://news.google.com' + href;
                if (href.startsWith('http')) return href;
                return null;
            }

            function getMeta(container) {
                const srcEl = container.querySelector('.vr1PYe');
                const timeEl = container.querySelector('time.hvbAAd') || container.querySelector('time');
                return {
                    source: srcEl ? (srcEl.innerText || '').trim() : 'Google News',
                    published: timeEl
                        ? (timeEl.getAttribute('datetime') || (timeEl.innerText || '').trim() || null)
                        : null,
                };
            }

            const anchors = Array.from(document.querySelectorAll('a.JtKRv'));
            for (const a of anchors) {
                if (results.length >= 30) break;
                const title = (a.innerText || a.textContent || '').trim();
                if (!title || title.length < 5) continue;
                const card = a.closest('.IFHyqb') || a.closest('.XlKvRb') || a.closest('article') || a.closest('.m5k28');
                const overlayEl = card ? card.querySelector('a.WwrzSb') : null;
                const href = fixHref((overlayEl?.getAttribute('href')) || a.getAttribute('href'));
                if (!href || seen.has(href)) continue;
                seen.add(href);
                const meta = card ? getMeta(card) : { source: 'Google News', published: null };
                results.push({ title, url: href, source_name: meta.source, published_at: meta.published });
            }
            return results;
        }
        """
    )
    return [
        {
            "title": (item.get("title") or "").strip(),
            "url": (item.get("url") or "").strip(),
            "source_name": item.get("source_name") or "Google News",
            "published_at": item.get("published_at"),
        }
        for item in raw
        if (item.get("title") or "").strip() and (item.get("url") or "").strip()
    ]


async def _google_news_batch_async(queries: list[str]) -> dict[str, dict[str, Any]]:
    from playwright.async_api import async_playwright

    timeout_ms = int(os.getenv("REPUTATION_GOOGLE_NEWS_TIMEOUT_MS", "15000"))
    results: dict[str, dict[str, Any]] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            viewport={"width": 1280, "height": 900},
        )
        worker_count = min(
            max(1, int(os.getenv("REPUTATION_GOOGLE_NEWS_WORKERS", "3"))),
            len(queries),
        )
        queue: asyncio.Queue[str] = asyncio.Queue()
        for query in queries:
            queue.put_nowait(query)

        async def run_worker(worker_number: int) -> None:
            page = await context.new_page()
            try:
                while not queue.empty():
                    try:
                        query = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    started = time.perf_counter()
                    error = ""
                    items: list[dict[str, Any]] = []
                    try:
                        items = await _google_news_search_with_page(page, query, timeout_ms)
                    except Exception as exc:
                        error = str(exc)
                        print(
                            "[REPUTATION][GOOGLE_NEWS] "
                            f"worker={worker_number} query failed for {query}: {exc}"
                        )
                    results[query] = {
                        "items": items,
                        "run": {
                            "source": "google_news",
                            "query": query,
                            "status": "error" if error else "success",
                            "returned": len(items),
                            "used": 0,
                            "error": error,
                            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                            "worker": worker_number,
                        },
                    }
                    queue.task_done()
            finally:
                await page.close()

        try:
            await asyncio.gather(*[
                run_worker(worker_number)
                for worker_number in range(1, worker_count + 1)
            ])
        finally:
            await browser.close()
    return results


def _prefetch_google_news(queries: list[str]) -> dict[str, dict[str, Any]]:
    if not queries:
        return {}
    started = time.perf_counter()
    try:
        cache = asyncio.run(_google_news_batch_async(queries))
        print(
            f"[REPUTATION][GOOGLE_NEWS] Reused one browser for {len(queries)} queries "
            f"in {round(time.perf_counter() - started, 2)}s"
        )
        return cache
    except Exception as exc:
        print(f"[REPUTATION][GOOGLE_NEWS] batch browser failed; falling back per query: {exc}")
        return {}


async def _reddit_browser_posts_for_reputation_async(query: str) -> list[dict[str, Any]]:
    from playwright.async_api import async_playwright

    from app.api.reddit.reddit_scraper import (
        close_consent_popup,
        extract_post,
        extract_post_links,
    )

    results: list[dict[str, Any]] = []
    search_url = f"https://www.reddit.com/search/?q={quote(query)}"
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
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                print(f"[REPUTATION][REDDIT] domcontentloaded failed for {query}: {exc}")
                await page.goto(search_url, wait_until="load", timeout=30000)

            await close_consent_popup(page)
            for _ in range(4):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(700)

            post_links = (await extract_post_links(page))[:5]
            print(f"[REPUTATION][REDDIT] Browser links for '{query}': {len(post_links)}")
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
                    "sentiment_label": post.get("sentiment_label") or "",
                    "sentiment_score": post.get("sentiment_score"),
                })
                if len(results) >= 5:
                    break
        finally:
            await browser.close()
    return results


async def _reddit_browser_search_with_context(context, page, query: str) -> list[dict[str, Any]]:
    from app.api.reddit.reddit_scraper import (
        close_consent_popup,
        extract_post,
        extract_post_links,
    )

    results: list[dict[str, Any]] = []
    search_url = f"https://www.reddit.com/search/?q={quote(query)}"
    try:
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"[REPUTATION][REDDIT] domcontentloaded failed for {query}: {exc}")
            await page.goto(search_url, wait_until="load", timeout=30000)

        await close_consent_popup(page)
        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(700)

        post_links = (await extract_post_links(page))[:5]
        print(f"[REPUTATION][REDDIT] Browser links for '{query}': {len(post_links)}")
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
                "sentiment_label": post.get("sentiment_label") or "",
                "sentiment_score": post.get("sentiment_score"),
            })
            if len(results) >= 5:
                break
    except Exception as exc:
        print(f"[REPUTATION][REDDIT] Browser search failed for {query}: {exc}")
    return results


async def _reddit_browser_batch_async(queries: list[str]) -> dict[str, dict[str, Any]]:
    from playwright.async_api import async_playwright

    results: dict[str, dict[str, Any]] = {}
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
            for query in queries:
                started = time.perf_counter()
                items = await _reddit_browser_search_with_context(context, page, query)
                results[query] = {
                    "items": items,
                    "run": {
                        "source": "reddit",
                        "query": query,
                        "status": "success",
                        "returned": len(items),
                        "used": 0,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "reused_browser": True,
                    },
                }
        finally:
            await browser.close()
            print("[REPUTATION][REDDIT] Reused browser closed")
    return results


def _prefetch_reddit_posts(queries: list[str]) -> dict[str, dict[str, Any]]:
    if not queries:
        return {}
    started = time.perf_counter()
    try:
        cache = asyncio.run(_reddit_browser_batch_async(queries))
        print(
            f"[REPUTATION][REDDIT] Reused one browser for {len(queries)} queries "
            f"in {round(time.perf_counter() - started, 2)}s"
        )
        return cache
    except Exception as exc:
        print(f"[REPUTATION][REDDIT] batch browser failed; falling back per query: {exc}")
        return {}


def _reddit_posts_for_reputation(query: str) -> list[dict[str, Any]]:
    try:
        return asyncio.run(_reddit_browser_posts_for_reputation_async(query))
    except Exception as exc:
        print(f"[REPUTATION][REDDIT] Browser Reddit fetch failed for {query}: {exc}")
        return []


def _newsapi_articles_for_reputation(query: str) -> list[dict[str, Any]]:
    disabled_until = get_newsapi_disabled_until()
    if time.time() < disabled_until:
        remaining = round(disabled_until - time.time(), 2)
        print(
            "[REPUTATION][NEWSAPI] skipped: "
            f"rate-limit cooldown active for '{query}' ({remaining}s remaining)"
        )
        return []

    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        print("[REPUTATION][NEWSAPI] skipped: NEWS_API_KEY missing")
        return []

    import requests

    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    try:
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": week_ago.isoformat(),
                "to": today.isoformat(),
                "sortBy": "popularity",
                "apiKey": api_key,
                "language": "en",
                "pageSize": 20,
            },
            timeout=int(os.getenv("REPUTATION_NEWSAPI_TIMEOUT_SECONDS", "8")),
        )
        payload = response.json()
    except Exception as exc:
        print(f"[REPUTATION][NEWSAPI] request failed for '{query}': {exc}")
        return []

    if isinstance(payload, dict) and payload.get("code") == "rateLimited":
        cooldown_seconds = int(os.getenv("REPUTATION_NEWSAPI_RATE_LIMIT_COOLDOWN_SECONDS", "43200"))
        set_newsapi_disabled_until(time.time() + cooldown_seconds)
        print(
            "[REPUTATION][NEWSAPI] rateLimited detected; "
            f"skipping NewsAPI for {cooldown_seconds}s"
        )
        return []

    if not isinstance(payload, dict) or payload.get("status") != "ok":
        print(
            f"[REPUTATION][NEWSAPI] no usable response for '{query}': "
            f"{payload.get('code') if isinstance(payload, dict) else 'invalid'} "
            f"{payload.get('message') if isinstance(payload, dict) else ''}"
        )
        return []

    return [
        {
            "title": article.get("title") or "",
            "body_text": article.get("description") or article.get("content") or "",
            "source": "newsapi",
            "source_name": (article.get("source") or {}).get("name") or "NewsAPI",
            "published_at": article.get("publishedAt") or "",
            "url": article.get("url") or "",
        }
        for article in payload.get("articles") or []
    ]


def _fetch_query(
    query: str,
    category: str,
    google_news_cache: dict[str, dict[str, Any]] | None = None,
    reddit_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    source_runs: list[dict[str, Any]] = []
    per_source_limit = max(1, int(os.getenv("REPUTATION_RESULTS_PER_SOURCE", str(DEFAULT_RESULTS_PER_SOURCE))))
    enabled_sources = REPUTATION_SOURCES_BY_CATEGORY.get(
        category,
        {"google_news", "newsapi", "reddit", "youtube"},
    )

    if "google_news" not in enabled_sources:
        source_runs.append({
            "source": "google_news",
            "query": query,
            "status": "skipped",
            "returned": 0,
            "used": 0,
            "reason": f"disabled_for_{category}",
            "duration_ms": 0,
        })
    else:
        google_cached = (google_news_cache or {}).get(query)
        if google_cached is not None:
            fetched = google_cached.get("items") or []
            for item in fetched[:per_source_limit]:
                items.append({
                    **item,
                    "source": item.get("source") or "google_news",
                    "query": query,
                })
            run = {
                **(google_cached.get("run") or {}),
                "used": min(len(fetched), per_source_limit),
            }
            print(
                f"[REPUTATION][SOURCE] google_news cached {category}: "
                f"returned={len(fetched)} used={run['used']} query='{query}'"
            )
            source_runs.append(run)
        else:
            source_started = time.perf_counter()
            try:
                print(f"[REPUTATION][SOURCE] START google_news {category}: {query}")
                fetched = _google_news_search_for_competitor(query) or []
                for item in fetched[:per_source_limit]:
                    items.append({
                        **item,
                        "source": item.get("source") or "google_news",
                        "query": query,
                    })
                duration_ms = round((time.perf_counter() - source_started) * 1000, 2)
                print(
                    f"[REPUTATION][SOURCE] DONE google_news {category}: "
                    f"returned={len(fetched)} used={min(len(fetched), per_source_limit)} "
                    f"took={round(duration_ms / 1000, 2)}s"
                )
                source_runs.append({
                    "source": "google_news",
                    "query": query,
                    "status": "success",
                    "returned": len(fetched),
                    "used": min(len(fetched), per_source_limit),
                    "duration_ms": duration_ms,
                })
            except Exception as exc:
                print(f"[REPUTATION] google_news fetch skipped for {query}: {exc}")
                source_runs.append({
                    "source": "google_news",
                    "query": query,
                    "status": "error",
                    "returned": 0,
                    "used": 0,
                    "error": str(exc),
                    "duration_ms": round((time.perf_counter() - source_started) * 1000, 2),
                })

    def run_source(source: str, fetcher) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if source == "youtube" and os.getenv("REPUTATION_ENABLE_YOUTUBE", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            print(f"[REPUTATION][SOURCE] SKIP youtube {category}: disabled by REPUTATION_ENABLE_YOUTUBE")
            return [], {
                "source": source,
                "query": query,
                "status": "skipped",
                "returned": 0,
                "used": 0,
                "reason": "disabled_by_REPUTATION_ENABLE_YOUTUBE",
                "duration_ms": 0,
            }

        if source not in enabled_sources:
            print(f"[REPUTATION][SOURCE] SKIP {source} {category}: disabled for this category")
            return [], {
                "source": source,
                "query": query,
                "status": "skipped",
                "returned": 0,
                "used": 0,
                "reason": f"disabled_for_{category}",
                "duration_ms": 0,
            }

        if source == "reddit" and reddit_cache is not None and query in reddit_cache:
            cached = reddit_cache.get(query) or {}
            fetched = cached.get("items") or []
            limited = [
                {
                    **item,
                    "source": item.get("source") or source,
                    "query": query,
                }
                for item in fetched[:per_source_limit]
            ]
            run = {
                **(cached.get("run") or {}),
                "used": min(len(fetched), per_source_limit),
            }
            print(
                f"[REPUTATION][SOURCE] reddit cached {category}: "
                f"returned={len(fetched)} used={run['used']} query='{query}'"
            )
            return limited, run

        source_started = time.perf_counter()
        try:
            print(f"[REPUTATION][SOURCE] START {source} {category}: {query}")
            fetched = fetcher(query) or []
            if source == "youtube":
                min_subscribers = int(os.getenv("REPUTATION_YOUTUBE_MIN_SUBSCRIBERS", "1000"))
                before_youtube_filter = len(fetched)
                fetched = [
                    item for item in fetched
                    if int(item.get("subscriber_count") or 0) >= min_subscribers
                ]
                if before_youtube_filter != len(fetched):
                    print(
                        f"[REPUTATION][YOUTUBE] authority filter: "
                        f"{before_youtube_filter}->{len(fetched)} "
                        f"min_subscribers={min_subscribers}"
                    )
            limited = [
                {
                    **item,
                    "source": item.get("source") or source,
                    "query": query,
                }
                for item in fetched[:per_source_limit]
            ]
            duration_ms = round((time.perf_counter() - source_started) * 1000, 2)
            print(
                f"[REPUTATION][SOURCE] DONE {source} {category}: "
                f"returned={len(fetched)} used={min(len(fetched), per_source_limit)} "
                f"took={round(duration_ms / 1000, 2)}s"
            )
            return limited, {
                "source": source,
                "query": query,
                "status": "success",
                "returned": len(fetched),
                "used": min(len(fetched), per_source_limit),
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            print(f"[REPUTATION] {source} fetch skipped for {query}: {exc}")
            return [], {
                "source": source,
                "query": query,
                "status": "error",
                "returned": 0,
                "used": 0,
                "error": str(exc),
                "duration_ms": round((time.perf_counter() - source_started) * 1000, 2),
            }

    parallel_sources = [
        ("newsapi", _newsapi_articles_for_reputation),
        ("reddit", _reddit_posts_for_reputation),
        ("youtube", _youtube_videos_for_competitor),
    ]
    max_workers = max(1, int(os.getenv("REPUTATION_SOURCE_WORKERS", str(DEFAULT_REPUTATION_SOURCE_WORKERS))))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(run_source, source, fetcher)
            for source, fetcher in parallel_sources
        ]
        for future in concurrent.futures.as_completed(futures):
            fetched_items, run = future.result()
            items.extend(fetched_items)
            source_runs.append(run)
    return items, source_runs


def _collect_evidence(brand_id: str, profile: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    retrieval_started = time.perf_counter()
    query_map = _queries(profile)
    category_limit = max(
        1,
        int(os.getenv(
            "REPUTATION_CATEGORY_EVIDENCE_LIMIT",
            str(DEFAULT_CATEGORY_EVIDENCE_LIMIT),
        )),
    )
    merged_category_limit = max(
        category_limit,
        int(os.getenv(
            "REPUTATION_MERGED_CATEGORY_EVIDENCE_LIMIT",
            str(category_limit * 2),
        )),
    )
    stored_evidence, stored_summary = _collect_stored_evidence(
        brand_id,
        profile,
        list(query_map),
        category_limit,
    )
    print(
        f"[REPUTATION][RETRIEVAL] START brand_id={brand_id} "
        f"categories={len(query_map)}"
    )
    all_queries = [
        query
        for queries in query_map.values()
        for query in queries
        if query
    ]
    print(f"[REPUTATION][RETRIEVAL] Google News prefetch queries={len(set(all_queries))}")
    google_news_cache = _prefetch_google_news(list(dict.fromkeys(all_queries)))
    reddit_queries_available = [
        query
        for category, queries in query_map.items()
        if "reddit" in REPUTATION_SOURCES_BY_CATEGORY.get(category, set())
        for query in queries
        if query
    ]
    reddit_queries_all = list(dict.fromkeys(reddit_queries_available))
    reddit_query_limit = max(0, int(os.getenv("REPUTATION_REDDIT_QUERY_LIMIT", "3")))
    reddit_queries = reddit_queries_all[:reddit_query_limit] if reddit_query_limit else reddit_queries_all
    print(
        "[REPUTATION][RETRIEVAL] Reddit prefetch queries="
        f"{len(reddit_queries)} of {len(reddit_queries_all)} limit={reddit_query_limit or 'none'}"
    )
    reddit_cache = _prefetch_reddit_posts(reddit_queries)
    evidence: dict[str, list[dict[str, Any]]] = {}
    runs: dict[str, list[dict[str, Any]]] = {}
    category_timings: dict[str, dict[str, Any]] = {}
    source_runs: list[dict[str, Any]] = []
    query_workers = max(1, int(os.getenv("REPUTATION_QUERY_WORKERS", str(DEFAULT_REPUTATION_QUERY_WORKERS))))
    category_workers = max(
        1,
        int(os.getenv("REPUTATION_CATEGORY_WORKERS", str(DEFAULT_REPUTATION_CATEGORY_WORKERS))),
    )
    print(
        f"[REPUTATION][RETRIEVAL] query_workers={query_workers} "
        f"category_workers={category_workers} "
        f"source_workers={os.getenv('REPUTATION_SOURCE_WORKERS', str(DEFAULT_REPUTATION_SOURCE_WORKERS))}"
    )

    def fetch_query_for_category(category: str, query: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], float]:
        query_started = time.perf_counter()
        try:
            print(f"[REPUTATION][QUERY] START {category}: {query}")
            raw_items, query_source_runs = _fetch_query(
                query,
                category,
                google_news_cache=google_news_cache,
                reddit_cache=reddit_cache,
            )
            duration_ms = round((time.perf_counter() - query_started) * 1000, 2)
            print(
                f"[REPUTATION][QUERY] DONE {category}: '{query}' "
                f"raw={len(raw_items)} took={round(duration_ms / 1000, 2)}s"
            )
            return query, raw_items, query_source_runs, duration_ms
        except Exception as exc:
            duration_ms = round((time.perf_counter() - query_started) * 1000, 2)
            print(
                f"[REPUTATION][QUERY] ERROR {category}: '{query}' "
                f"after={round(duration_ms / 1000, 2)}s error={exc}"
            )
            return query, [], [{
                "source": "query_worker",
                "query": query,
                "status": "error",
                "returned": 0,
                "used": 0,
                "error": str(exc),
                "duration_ms": duration_ms,
            }], duration_ms

    def collect_category(category: str, queries: list[str]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        category_started = time.perf_counter()
        print(f"[REPUTATION][CATEGORY] START {category}: queries={len(queries)}")
        validation_profile = _category_validation_profile(profile, category)
        category_items: list[dict[str, Any]] = []
        category_runs: list[dict[str, Any]] = []
        category_source_runs: list[dict[str, Any]] = []
        seen = set()
        query_results: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]], float]] = {}

        if query_workers <= 1:
            for query in queries:
                query, raw_items, query_source_runs, query_duration_ms = fetch_query_for_category(category, query)
                query_results[query] = (raw_items, query_source_runs, query_duration_ms)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(query_workers, max(1, len(queries)))) as executor:
                futures = [
                    executor.submit(fetch_query_for_category, category, query)
                    for query in queries
                ]
                for future in concurrent.futures.as_completed(futures):
                    query, raw_items, query_source_runs, query_duration_ms = future.result()
                    query_results[query] = (raw_items, query_source_runs, query_duration_ms)

        for query in queries:
            raw_items, query_source_runs, query_duration_ms = query_results.get(query, ([], [], 0.0))
            category_source_runs.extend([
                {**run, "category": category}
                for run in query_source_runs
            ])
            accepted = []
            rejected = 0
            rejected_validation = 0
            rejected_stale = 0
            rejection_samples = []
            for item in raw_items:
                is_recent, recency_reason = _is_recent_reputation_item(item)
                if not is_recent:
                    rejected_stale += 1
                    if len(rejection_samples) < 8:
                        rejection_samples.append({
                            "title": item.get("title") or "",
                            "url": item.get("url") or "",
                            "category": category,
                            "validation_result": "rejected",
                            "reason": recency_reason,
                        })
                    continue
                is_valid_entity, validation_reason = _validate_article_against_resolved_entity(item, validation_profile)
                if not is_valid_entity:
                    rejected_validation += 1
                    if len(rejection_samples) < 8:
                        rejection_samples.append({
                            "title": item.get("title") or "",
                            "url": item.get("url") or "",
                            "category": category,
                            "validation_result": "rejected",
                            "reason": validation_reason,
                            "validation_mode": validation_profile.get("entity_type") or "",
                            "validation_target": validation_profile.get("competitor_name") or "",
                        })
                    continue
                score, reason = _reputation_relevance_score(item, validation_profile, category)
                if score < 0.5:
                    rejected += 1
                    if len(rejection_samples) < 8:
                        rejection_samples.append({
                            "title": item.get("title") or "",
                            "url": item.get("url") or "",
                            "category": category,
                            "validation_result": "rejected",
                            "reason": reason,
                            "validation_mode": validation_profile.get("entity_type") or "",
                            "validation_target": validation_profile.get("competitor_name") or "",
                            "relevance_score": score,
                        })
                    continue
                key = item.get("url") or normalize(item.get("title") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                item["reputation_relevance_score"] = score
                item["reputation_relevance_reason"] = reason
                item["recency_reason"] = recency_reason
                item["entity_validation_reason"] = validation_reason
                item["validation_mode"] = validation_profile.get("entity_type") or ""
                item["validation_target"] = validation_profile.get("competitor_name") or ""
                item["matched_company"] = validation_profile.get("competitor_company") or ""
                item["matched_product"] = validation_profile.get("competitor_product") or ""
                item["product_aliases"] = validation_profile.get("product_aliases") or []
                item["evidence_origin"] = "live"
                item["stored_evidence"] = False
                item["live_evidence"] = True
                accepted.append(item)
                category_items.append(item)
                if len(category_items) >= category_limit:
                    break
            category_runs.append({
                "query": query,
                "validation_entity_type": validation_profile.get("entity_type") or "",
                "validation_target": validation_profile.get("competitor_name") or "",
                "validation_company": validation_profile.get("competitor_company") or "",
                "validation_product": validation_profile.get("competitor_product") or "",
                "raw_found": len(raw_items),
                "accepted": len(accepted),
                "rejected_entity_validation": rejected_validation,
                "rejected_relevance": rejected,
                "rejected_stale": rejected_stale,
                "rejection_samples": rejection_samples,
                "duration_ms": query_duration_ms,
            })
            if len(category_items) >= category_limit:
                break
        deduped_items = dedupe_items(category_items, category_limit)
        category_duration_ms = round((time.perf_counter() - category_started) * 1000, 2)
        timing = {
            "duration_ms": category_duration_ms,
            "queries": len(queries),
            "accepted": len(deduped_items),
        }
        print(
            f"[REPUTATION][CATEGORY] {category}: "
            f"{round(category_duration_ms / 1000, 2)}s, accepted={len(deduped_items)}"
        )
        return category, deduped_items, category_runs, category_source_runs, timing

    if category_workers <= 1:
        category_results = [
            collect_category(category, queries)
            for category, queries in query_map.items()
        ]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(category_workers, len(query_map))) as executor:
            futures = [
                executor.submit(collect_category, category, queries)
                for category, queries in query_map.items()
            ]
            category_results = [future.result() for future in concurrent.futures.as_completed(futures)]

    merge_summary: dict[str, dict[str, int]] = {}
    for category, deduped_items, category_runs, category_source_runs, timing in category_results:
        merged_items, category_merge = _merge_category_evidence(
            stored_evidence.get(category) or [],
            deduped_items,
            merged_category_limit,
        )
        evidence[category] = merged_items
        merge_summary[category] = category_merge
        runs[category] = category_runs
        source_runs.extend(category_source_runs)
        category_timings[category] = {
            **timing,
            "stored_accepted": len(stored_evidence.get(category) or []),
            "merged_accepted": len(merged_items),
        }

    live_unique_keys = {
        _stored_evidence_key(item)
        for _, items, _, _, _ in category_results
        for item in items
        if _stored_evidence_key(item)
    }
    merged_unique_keys = {
        _stored_evidence_key(item)
        for items in evidence.values()
        for item in items
        if _stored_evidence_key(item)
    }
    stored_unique_keys = {
        _stored_evidence_key(item)
        for items in stored_evidence.values()
        for item in items
        if _stored_evidence_key(item)
    }

    summary = {
        "queries": query_map,
        "runs": runs,
        "category_timings": category_timings,
        "source_runs": source_runs,
        "query_workers": query_workers,
        "category_workers": category_workers,
        "category_evidence_limit": category_limit,
        "merged_category_evidence_limit": merged_category_limit,
        "reddit_prefetch_queries": len(reddit_queries),
        "reddit_prefetch_queries_available": len(reddit_queries_all),
        "reddit_query_limit": reddit_query_limit,
        "reddit_prefetch_hits": len(reddit_cache),
        "stored_evidence": stored_summary,
        "evidence_merge": {
            "stored_articles_loaded": int(stored_summary.get("rows_loaded") or 0),
            "stored_articles_validated": len(stored_unique_keys),
            "live_articles_loaded": len(live_unique_keys),
            "merged_articles": len(stored_unique_keys) + len(live_unique_keys),
            "deduped_articles": len(merged_unique_keys),
            "validated_articles": len(merged_unique_keys),
            "category_details": merge_summary,
        },
        "duration_ms": round((time.perf_counter() - retrieval_started) * 1000, 2),
    }
    retrieval_payload = {
        "stage": "temporary_reputation_retrieval",
        "competitor_profile": profile,
        "summary": summary,
        "evidence_examples": {
            category: [
                {
                    "title": item.get("title") or "",
                    "url": item.get("url") or "",
                    "source": item.get("source") or "",
                    "source_name": item.get("source_name") or "",
                    "published_at": item.get("published_at") or "",
                    "evidence_origin": item.get("evidence_origin") or "",
                    "validation_mode": item.get("validation_mode") or "",
                    "validation_target": item.get("validation_target") or "",
                }
                for item in items[:5]
            ]
            for category, items in evidence.items()
        },
    }
    log_path = write_reputation_log("retrieval", brand_id, retrieval_payload)
    print(
        f"[REPUTATION][RETRIEVAL] DONE total={round(summary['duration_ms'] / 1000, 2)}s "
        f"stored={summary['evidence_merge']['stored_articles_validated']} "
        f"live={summary['evidence_merge']['live_articles_loaded']} "
        f"deduped={summary['evidence_merge']['deduped_articles']} "
        f"log={log_path}"
    )
    return evidence, summary
