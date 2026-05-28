"""
Brand Monitoring Service.

The scheduler uses run_monitoring_cycle() for due brands only.
The UI/API uses run_single_brand_monitor() so a new search never reruns every
active brand and burns source quotas.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2
import requests
from dotenv import load_dotenv

from app.services.entity_resolution.brand_matcher import (
    BrandProfile,
    load_brand_profile,
    match_brand_profile,
    unique_terms,
)
from app.services.entity_resolution.embedding_matcher import score_semantic_similarity
from app.services.entity_resolution.entity_detector import has_company_entity
from app.services.sentiment_service import enrich_item_sentiment
from app.services.source_quota_service import can_use_source, increment_source_usage

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
MONITOR_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MINUTES", "15"))
_MENTION_MATCH_COLUMNS_READY = False
_MONITOR_RUNTIME_COLUMNS_READY = False

MIN_SOURCE_RESULTS = {
    "newsapi": 10,
    "google_news": 10,
    "reddit": 10,
    "youtube": 5,
}

FALLBACK_SOURCE_THRESHOLDS = {
    "newsapi": 0.25,
    "google_news": 0.25,
    "reddit": 0.25,
    "youtube": 0.72,
}

TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "gbraid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ocid",
    "ref",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
    "utm_id",
}


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def normalize_url(url: str | None) -> str:
    if not url:
        return ""

    try:
        parts = urlsplit(url.strip())
        netloc = parts.netloc.lower()
        query_params = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_PARAMS
        ]
        return urlunsplit(
            (
                parts.scheme.lower() or "https",
                netloc,
                parts.path,
                urlencode(query_params, doseq=True),
                "",
            )
        )
    except Exception:
        return url.strip()


def ensure_monitor_runtime_columns(cur):
    global _MONITOR_RUNTIME_COLUMNS_READY
    if _MONITOR_RUNTIME_COLUMNS_READY:
        return

    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS last_status TEXT")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS last_error TEXT")
    cur.execute("ALTER TABLE monitored_brands ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ")
    cur.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.brand_mentions') IS NOT NULL
               AND to_regclass('public.monitored_brands') IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_brand_mentions_brand'
            ) THEN
                ALTER TABLE brand_mentions
                ADD CONSTRAINT fk_brand_mentions_brand
                FOREIGN KEY (brand_id)
                REFERENCES monitored_brands(id)
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """
    )
    cur.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.monitor_runs') IS NOT NULL
               AND to_regclass('public.monitored_brands') IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_monitor_runs_brand'
            ) THEN
                ALTER TABLE monitor_runs
                ADD CONSTRAINT fk_monitor_runs_brand
                FOREIGN KEY (brand_id)
                REFERENCES monitored_brands(id)
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """
    )
    cur.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.sentiment_results') IS NOT NULL
               AND to_regclass('public.articles') IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_sentiment_article'
            ) THEN
                ALTER TABLE sentiment_results
                ADD CONSTRAINT fk_sentiment_article
                FOREIGN KEY (article_id)
                REFERENCES articles(article_id)
                ON DELETE CASCADE
                NOT VALID;
            END IF;
        END $$;
        """
    )
    _MONITOR_RUNTIME_COLUMNS_READY = True


def get_table_columns(cur, table_name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    return {row[0] for row in cur.fetchall()}


def start_monitor_run(brand_id: str) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        columns = get_table_columns(cur, "monitor_runs")
        if not columns:
            return None

        insert_values = {}
        if "brand_id" in columns:
            insert_values["brand_id"] = brand_id
        if "status" in columns:
            insert_values["status"] = "running"
        if "started_at" in columns:
            insert_values["started_at"] = datetime.now(timezone.utc)

        if not insert_values:
            return None

        names = list(insert_values.keys())
        placeholders = ", ".join(["%s"] * len(names))
        returning = " RETURNING id" if "id" in columns else ""
        cur.execute(
            f"INSERT INTO monitor_runs ({', '.join(names)}) VALUES ({placeholders}){returning}",
            tuple(insert_values[name] for name in names),
        )
        row = cur.fetchone() if "id" in columns else None
        conn.commit()
        return str(row[0]) if row else None
    except Exception as exc:
        conn.rollback()
        print(f"[MONITOR_RUNS] Could not create run log: {exc}")
        return None
    finally:
        cur.close()
        conn.close()


def finish_monitor_run(run_id: str | None, status: str, mentions_found: int = 0, error_message: str | None = None):
    if not run_id:
        return

    conn = get_conn()
    cur = conn.cursor()
    try:
        columns = get_table_columns(cur, "monitor_runs")
        updates = {}
        if "status" in columns:
            updates["status"] = status
        if "mentions_found" in columns:
            updates["mentions_found"] = mentions_found
        if "error_message" in columns:
            updates["error_message"] = error_message
        if "completed_at" in columns:
            updates["completed_at"] = datetime.now(timezone.utc)

        if not updates or "id" not in columns:
            return

        set_sql = ", ".join([f"{name} = %s" for name in updates])
        cur.execute(
            f"UPDATE monitor_runs SET {set_sql} WHERE id = %s",
            (*updates.values(), run_id),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[MONITOR_RUNS] Could not update run log: {exc}")
    finally:
        cur.close()
        conn.close()


def _fetch_brand_profiles(where_sql: str, params: tuple = ()) -> list[BrandProfile]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id
        FROM monitored_brands
        WHERE {where_sql}
        ORDER BY COALESCE(last_run_at, created_at) ASC
        """,
        params,
    )
    brand_ids = [str(row[0]) for row in cur.fetchall()]
    cur.close()

    profiles = [load_brand_profile(conn, brand_id=brand_id) for brand_id in brand_ids]
    conn.close()
    return profiles


def get_active_brand_profiles() -> list[BrandProfile]:
    """Fetch every active monitor. Intended for manual/admin use only."""
    return _fetch_brand_profiles("is_active = TRUE")


def get_due_brand_profiles() -> list[BrandProfile]:
    """Fetch active monitors whose interval has elapsed."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MONITOR_INTERVAL_MINUTES)
    return _fetch_brand_profiles(
        "is_active = TRUE AND (last_run_at IS NULL OR last_run_at <= %s)",
        (cutoff,),
    )


def get_brand_profile(brand_id: str) -> BrandProfile:
    conn = get_conn()
    try:
        return load_brand_profile(conn, brand_id=brand_id)
    finally:
        conn.close()


def get_brand_profile_by_name(brand_name: str) -> BrandProfile:
    conn = get_conn()
    try:
        return load_brand_profile(conn, brand_name=brand_name)
    finally:
        conn.close()


def url_already_collected(url: str) -> bool:
    normalized_url = normalize_url(url)
    if not normalized_url:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM brand_mentions WHERE url = %s LIMIT 1", (normalized_url,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def save_mention(brand_id: str, source: str, item: dict):
    """Save a single mention to brand_mentions table."""
    global _MENTION_MATCH_COLUMNS_READY
    url = normalize_url(item.get("url", ""))
    if url and url_already_collected(url):
        return

    conn = get_conn()
    cur = conn.cursor()
    if not _MENTION_MATCH_COLUMNS_READY:
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS match_confidence DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS match_reason TEXT")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS matched_terms TEXT[]")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS sentiment_confidence DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS emotion_confidence DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS relevance_score DOUBLE PRECISION")
        cur.execute("ALTER TABLE brand_mentions ADD COLUMN IF NOT EXISTS semantic_score DOUBLE PRECISION")
        conn.commit()
        _MENTION_MATCH_COLUMNS_READY = True

    item = enrich_item_sentiment(item)
    cur.execute(
        """
        INSERT INTO brand_mentions (
            brand_id, source, title, url, body_text,
            author, published_at, sentiment_label, sentiment_score,
            primary_category, emotion, match_confidence, match_reason, matched_terms,
            sentiment_confidence, emotion_confidence, relevance_score, semantic_score
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (url) DO NOTHING
        """,
        (
            brand_id,
            source,
            item.get("title"),
            url,
            item.get("body_text") or item.get("text", ""),
            item.get("author"),
            item.get("published_at"),
            item.get("sentiment_label"),
            item.get("sentiment_score"),
            item.get("primary_category"),
            item.get("emotion"),
            item.get("match_confidence"),
            item.get("match_reason"),
            item.get("matched_terms") or [],
            item.get("sentiment_confidence"),
            item.get("emotion_confidence"),
            item.get("relevance_score"),
            item.get("semantic_score"),
        ),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_monitor_success(brand_id: str):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    next_run_at = now + timedelta(minutes=MONITOR_INTERVAL_MINUTES)
    ensure_monitor_runtime_columns(cur)
    cur.execute(
        """
        UPDATE monitored_brands
        SET last_run_at = %s,
            next_run_at = %s,
            last_status = 'success',
            last_error = NULL
        WHERE id = %s
        """,
        (now, next_run_at, brand_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_monitor_failure(brand_id: str, error_message: str):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    next_run_at = now + timedelta(minutes=MONITOR_INTERVAL_MINUTES)
    ensure_monitor_runtime_columns(cur)
    cur.execute(
        """
        UPDATE monitored_brands
        SET last_run_at = %s,
            next_run_at = %s,
            last_status = 'failed',
            last_error = %s
        WHERE id = %s
        """,
        (now, next_run_at, error_message[:2000], brand_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def profile_search_terms(profile: BrandProfile) -> list[str]:
    return unique_terms([profile.brand_name, *profile.aliases])


def is_english_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False

    ascii_chars = sum(1 for char in cleaned if char.isascii())
    letters_or_space = sum(1 for char in cleaned if char.isascii() and (char.isalpha() or char.isspace()))
    if len(cleaned) < 80:
        return ascii_chars / max(len(cleaned), 1) > 0.85 and letters_or_space > 8

    try:
        from langdetect import detect

        return detect(cleaned[:1000]) == "en"
    except Exception:
        return ascii_chars / max(len(cleaned), 1) > 0.85 and letters_or_space > 8


def has_negative_ambiguous_context(profile: BrandProfile, text: str) -> bool:
    negative_terms = profile.exclusions
    if not negative_terms:
        return False
    lowered = text.lower()
    return any(term in lowered for term in negative_terms)


def source_quality_score(source: str, item: dict, profile: BrandProfile) -> float:
    source_name = (item.get("author") or item.get("channel_name") or item.get("source_name") or "").lower()
    if any(channel.channel_name.lower() == source_name for channel in profile.official_channels):
        return 0.4

    trusted_publishers = ["reuters", "associated press", "ap news", "bloomberg", "cnbc", "the verge", "techcrunch", "bbc", "cnn"]
    if source in {"newsapi", "google_news"} and any(name in source_name for name in trusted_publishers):
        return 0.25

    spam_terms = ["meme", "lyrics", "topic", "fan", "unofficial"]
    if any(term in source_name for term in spam_terms):
        return -0.2

    return 0.0


def title_body_relevance_bonus(profile: BrandProfile, title: str, body: str) -> float:
    terms = [profile.brand_name, *profile.aliases]
    title_lower = title.lower()
    body_lower = body.lower()
    bonus = 0.0
    if any(term.lower() in title_lower for term in terms if term):
        bonus += 0.12
    if any(term.lower() in body_lower for term in terms if term):
        bonus += 0.06
    if profile.context_keywords and any(term.lower() in title_lower for term in profile.context_keywords):
        bonus += 0.1
    return bonus


def build_newsapi_query(profile: BrandProfile) -> str:
    include_terms = [f'"{term}"' for term in profile_search_terms(profile)]
    query = " OR ".join(include_terms)

    context_terms = profile.context_keywords
    if context_terms:
        context_query = " OR ".join(f'"{term}"' for term in context_terms)
        query = f"({query}) AND ({context_query})"

    exclusion_terms = [f'NOT "{phrase}"' for phrase in profile.exclusions]
    if exclusion_terms:
        query = f"({query}) {' '.join(exclusion_terms)}"

    return query


def score_item_metadata(profile: BrandProfile, source: str, item: dict) -> tuple[dict, dict, dict]:
    title = item.get("title") or ""
    text = item.get("body_text") or item.get("text") or ""
    channel_name = item.get("author") or item.get("channel_name") or ""

    match = match_brand_profile(
        profile,
        source=source,
        title=title,
        text=text,
        channel_name=channel_name,
    )

    semantic_result = {"semantic_score": 0.0, "semantic_match": False}
    rule_confidence = float(match.get("confidence") or 0.0)
    if not match["matched"] and rule_confidence >= 0.2:
        semantic_result = score_semantic_similarity(
            brand_name=profile.brand_name,
            title=title,
            text=text,
            aliases=profile.aliases,
            brand_context=profile.brand_context,
            threshold=0.35,
        )

    semantic_score = float(semantic_result.get("semantic_score") or 0.0)
    quality_score = source_quality_score(source, item, profile)
    relevance_score = max(rule_confidence, semantic_score)
    relevance_score += quality_score
    relevance_score += title_body_relevance_bonus(profile, title, text)
    if has_negative_ambiguous_context(profile, " ".join([title, text, channel_name])):
        relevance_score -= 0.35
    relevance_score = max(0.0, min(1.0, round(relevance_score, 4)))
    item["match_confidence"] = rule_confidence
    item["match_reason"] = match["reason"]
    item["matched_terms"] = match["matched_terms"]
    item["semantic_score"] = semantic_score
    item["relevance_score"] = relevance_score
    item["source_quality_score"] = quality_score
    return item, match, semantic_result


def filter_items(profile: BrandProfile, source: str, items: list[dict]) -> list[dict]:
    filtered = []
    fallback_candidates = []
    minimum = MIN_SOURCE_RESULTS.get(source, 0)
    fallback_threshold = FALLBACK_SOURCE_THRESHOLDS.get(source, 0.25)

    for item in items:
        combined_text = " ".join(
            value
            for value in [
                item.get("title") or "",
                item.get("body_text") or item.get("text") or "",
                item.get("author") or item.get("channel_name") or "",
            ]
            if value
        )
        if combined_text and not is_english_text(combined_text):
            print(f"[FILTER] Dropped non-English ({source}): {(item.get('title') or '')[:60]}")
            continue

        scored_item, rule_result, semantic_result = score_item_metadata(profile, source, item)
        is_relevant = rule_result["matched"] or semantic_result["semantic_match"]
        title = scored_item.get("title") or ""
        has_negative_context = has_negative_ambiguous_context(profile, combined_text)

        if has_negative_context and scored_item.get("semantic_score", 0) < 0.45 and scored_item.get("relevance_score", 0) < 0.85:
            print(
                f"[FILTER] Dropped ambiguous negative ({source}): "
                f"rel={scored_item.get('relevance_score', 0):.2f} sem={scored_item.get('semantic_score', 0):.2f} | {title[:60]}"
            )
            continue

        if is_relevant:
            if (
                profile.context_keywords
                and scored_item.get("relevance_score", 0) < 0.85
                and has_company_entity(combined_text, profile.brand_name, profile.aliases)
            ):
                scored_item["relevance_score"] = max(scored_item.get("relevance_score", 0), 0.85)
                scored_item["match_reason"] = f"{scored_item.get('match_reason', '')} + gliner_company_entity"
            filtered.append(scored_item)
            continue

        if scored_item.get("relevance_score", 0) >= fallback_threshold:
            fallback_candidates.append(scored_item)
            continue

        print(
            f"[FILTER] Dropped ({source}): rule={scored_item.get('match_confidence', 0):.2f} "
            f"sem={scored_item.get('semantic_score', 0):.2f} | {title[:60]}"
        )

    if len(filtered) < minimum and fallback_candidates:
        needed = minimum - len(filtered)
        fallback_candidates = sorted(
            fallback_candidates,
            key=lambda item: item.get("relevance_score", 0),
            reverse=True,
        )
        filtered.extend(fallback_candidates[:needed])
        print(f"[FILTER] {source}: added {min(needed, len(fallback_candidates))} ranked fallback items")

    print(f"[FILTER] {source}: {len(filtered)}/{len(items)} kept")
    return sorted(filtered, key=lambda item: item.get("relevance_score", 0), reverse=True)


def collect_newsapi(profile: BrandProfile) -> list[dict]:
    if not NEWS_API_KEY:
        print("[MONITOR][NewsAPI] NEWS_API_KEY missing; skipping NewsAPI.")
        return []

    try:
        res = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": build_newsapi_query(profile),
                "apiKey": NEWS_API_KEY,
                "pageSize": 30,
                "language": "en",
                "sortBy": "publishedAt",
            },
            timeout=15,
        )
        articles = res.json().get("articles", []) if res.ok else []
        items = [
            {
                "title": article.get("title"),
                "url": article.get("url"),
                "body_text": article.get("description") or "",
                "author": article.get("source", {}).get("name") or article.get("author"),
                "published_at": article.get("publishedAt"),
            }
            for article in articles
        ]
        return filter_items(profile, "newsapi", items)
    except Exception as exc:
        print(f"[MONITOR][NewsAPI] Error for '{profile.brand_name}': {exc}")
        return []


def collect_reddit(profile: BrandProfile) -> list[dict]:
    try:
        res = requests.post(
            "http://localhost:8000/api/reddit/scrape-store-reddit",
            params={"brand": profile.brand_name},
            timeout=60,
        )
        posts = res.json() if res.ok else []
        items = [
            {
                "title": post.get("content") or post.get("title", ""),
                "url": post.get("url"),
                "body_text": post.get("content", ""),
                "author": post.get("username"),
                "published_at": post.get("date"),
                "sentiment_label": post.get("sentiment_label"),
                "sentiment_score": post.get("sentiment_score"),
            }
            for post in posts
        ]
        return filter_items(profile, "reddit", items)
    except Exception as exc:
        print(f"[MONITOR][Reddit] Error for '{profile.brand_name}': {exc}")
        return []


def collect_youtube(profile: BrandProfile) -> list[dict]:
    try:
        res = requests.post(
            "http://localhost:8000/api/youtube/scrape-store-youtube",
            params={
                "brand": profile.brand_name,
                "entity_name": profile.brand_name,
                "ignore_terms": ",".join(profile.exclusions),
            },
            timeout=60,
        )
        videos = res.json() if res.ok else []
        items = [
            {
                "title": video.get("title"),
                "url": video.get("video_url") or video.get("url"),
                "author": video.get("youtuber") or video.get("channelTitle"),
                "channel_name": video.get("youtuber") or video.get("channelTitle"),
                "published_at": video.get("published"),
            }
            for video in videos
        ]
        return filter_items(profile, "youtube", items)
    except Exception as exc:
        print(f"[MONITOR][YouTube] Error for '{profile.brand_name}': {exc}")
        return []


def collect_google_news(profile: BrandProfile) -> list[dict]:
    try:
        res = requests.get(
            "http://localhost:8000/api/google-news/search",
            params={"brand": profile.brand_name},
            timeout=60,
        )
        raw_items = res.json() if res.ok else []
        items = [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "body_text": item.get("body_text") or item.get("description") or "",
                "author": item.get("source_name") or item.get("author"),
                "published_at": item.get("published_at"),
            }
            for item in raw_items
        ]
        return filter_items(profile, "google_news", items)
    except Exception as exc:
        print(f"[MONITOR][GoogleNews] Error for '{profile.brand_name}': {exc}")
        return []


SOURCE_COLLECTORS: tuple[tuple[str, Callable[[BrandProfile], list[dict]]], ...] = (
    ("newsapi", collect_newsapi),
    ("google_news", collect_google_news),
    ("reddit", collect_reddit),
    ("youtube", collect_youtube),
)


def collect_with_quota(source: str, collector: Callable[[BrandProfile], list[dict]], profile: BrandProfile) -> list[dict]:
    if not can_use_source(source):
        print(f"[MONITOR][QUOTA] {source} quota exceeded; skipping {profile.brand_name}.")
        return []

    items = collector(profile)
    increment_source_usage(source)
    return items


def run_single_brand_monitor(brand_id: str) -> dict:
    """Run all collectors for one brand only."""
    profile = get_brand_profile(brand_id)
    counts = {}
    run_id = start_monitor_run(profile.brand_id)
    total_mentions = 0

    print(f"[MONITOR] Starting single-brand cycle for {profile.brand_name}...")
    print(f"[MONITOR] Terms: {profile_search_terms(profile)}")

    try:
        for source, collector in SOURCE_COLLECTORS:
            items = collect_with_quota(source, collector, profile)
            for item in items:
                save_mention(profile.brand_id, source, item)
            counts[source] = len(items)
            total_mentions += len(items)
            print(f"[MONITOR]   {source}: {len(items)} matched items")

        update_monitor_success(profile.brand_id)
        finish_monitor_run(run_id, "success", mentions_found=total_mentions)
        print(f"[MONITOR] Done: {profile.brand_name}\n")

        return {
            "brand_id": profile.brand_id,
            "brand_name": profile.brand_name,
            "counts": counts,
        }
    except Exception as exc:
        error_message = str(exc)
        update_monitor_failure(profile.brand_id, error_message)
        finish_monitor_run(run_id, "failed", mentions_found=total_mentions, error_message=error_message)
        print(f"[MONITOR] Failed: {profile.brand_name}: {error_message}\n")
        raise


def run_brand_monitor_by_name(brand_name: str) -> dict:
    profile = get_brand_profile_by_name(brand_name)
    return run_single_brand_monitor(profile.brand_id)


def run_monitoring_cycle():
    """
    Scheduler entrypoint.

    Only due brands are refreshed. UI-triggered refreshes must use
    run_single_brand_monitor() instead.
    """
    profiles = get_due_brand_profiles()
    if not profiles:
        print("[MONITOR] No due active brands to monitor.")
        return {"status": "no_due_brands", "brands": 0}

    print(f"[MONITOR] Starting scheduled cycle for {len(profiles)} due brand(s)...")
    results = []
    for profile in profiles:
        try:
            results.append(run_single_brand_monitor(profile.brand_id))
        except Exception as exc:
            results.append({
                "brand_id": profile.brand_id,
                "brand_name": profile.brand_name,
                "status": "failed",
                "error": str(exc),
            })

    print("[MONITOR] Scheduled cycle complete.\n")
    return {"status": "cycle completed", "brands": len(results), "results": results}
