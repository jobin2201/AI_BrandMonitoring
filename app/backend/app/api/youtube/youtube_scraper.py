from fastapi import APIRouter, Query
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime
import os
import socket
import time
from dotenv import load_dotenv
from app.services.entity_resolution.embedding_matcher import score_semantic_similarity
from app.services.observability.monitoring_logger import log_source_run
load_dotenv()

router = APIRouter()

API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    raise RuntimeError("YOUTUBE_API_KEY not set in environment or .env file")

youtube = build("youtube", "v3", developerKey=API_KEY)
_CHANNEL_STATS_CACHE = {}
_YOUTUBE_QUOTA_BLOCKED_UNTIL = 0.0


def is_youtube_quota_error(exc) -> bool:
    text = str(exc).lower()
    status = getattr(getattr(exc, "resp", None), "status", None)
    return (
        status in {403, 429}
        and any(term in text for term in ["quota", "ratelimit", "rate limit", "daily limit"])
    )


def execute_with_retry(request, retries=3, label="youtube"):
    global _YOUTUBE_QUOTA_BLOCKED_UNTIL
    if time.time() < _YOUTUBE_QUOTA_BLOCKED_UNTIL:
        print(f"[YOUTUBE] {label} skipped: quota/rate-limit cooldown active")
        return None

    for attempt in range(retries):
        try:
            return request.execute()
        except (socket.gaierror, HttpError, Exception) as exc:
            print(f"[YOUTUBE] {label} attempt {attempt + 1}/{retries} failed: {exc}")
            if is_youtube_quota_error(exc):
                cooldown_seconds = int(os.getenv("YOUTUBE_QUOTA_COOLDOWN_SECONDS", "3600"))
                _YOUTUBE_QUOTA_BLOCKED_UNTIL = time.time() + cooldown_seconds
                print(
                    f"[YOUTUBE] {label} quota/rate limit detected; "
                    f"skipping YouTube calls for {cooldown_seconds}s"
                )
                return None
            if attempt == retries - 1:
                return None
            time.sleep(2 * (attempt + 1))

def search_videos(brand, max_results=50, channel_id=None, order="viewCount"):
    search_query = brand.replace("_", " ")
    videos = []
    nextPageToken = None
    while len(videos) < max_results:
        params = {
            "q": search_query,
            "part": "snippet",
            "type": "video",
            "maxResults": min(max_results - len(videos), 50),
            "order": order,
            "pageToken": nextPageToken,
        }
        if channel_id:
            params["channelId"] = channel_id
        request = youtube.search().list(
            **params
        )
        response = execute_with_retry(request, label="search_videos")
        if not response:
            return videos
        for item in response["items"]:
            video_obj = {
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "published": item["snippet"].get("publishedAt"),
                "channelTitle": item["snippet"].get("channelTitle", ""),
                "channelId": item["snippet"].get("channelId", "")
            }
            videos.append(video_obj)
        nextPageToken = response.get('nextPageToken')
        if not nextPageToken:
            break
    return videos


def discover_official_channel_ids(brand, max_channels=2):
    try:
        request = youtube.search().list(
            q=brand,
            part="snippet",
            type="channel",
            maxResults=5,
            order="relevance",
        )
        response = execute_with_retry(request, label="discover_official_channel_ids")
        if not response:
            return []
    except Exception as exc:
        print(f"[YOUTUBE] Official channel discovery failed for {brand}: {exc}")
        return []

    brand_lower = brand.strip().lower()
    channel_ids = []
    official_patterns = [
        "official", "motors", "cars", "auto", "inc", "corp",
        "company", "global", "tv", "technology", "technologies",
    ]
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        title = (snippet.get("title") or "").strip()
        description = (snippet.get("description") or "").lower()
        channel_id = item.get("id", {}).get("channelId")
        title_lower = title.lower()
        is_exact = title_lower == brand_lower
        has_brand = brand_lower in title_lower or brand_lower in description
        has_official_pattern = any(pattern in title_lower for pattern in official_patterns)
        if channel_id and has_brand and (is_exact or has_official_pattern):
            channel_ids.append(channel_id)
        if len(channel_ids) >= max_channels:
            break
    return channel_ids


def get_channel_stats(channel_ids):
    """Return subscriber metadata for channel authority ranking."""
    unique_ids = [channel_id for channel_id in dict.fromkeys(channel_ids) if channel_id]
    missing = [channel_id for channel_id in unique_ids if channel_id not in _CHANNEL_STATS_CACHE]
    for offset in range(0, len(missing), 50):
        batch = missing[offset:offset + 50]
        if not batch:
            continue
        try:
            request = youtube.channels().list(
                part="snippet,statistics",
                id=",".join(batch),
                maxResults=len(batch),
            )
            response = execute_with_retry(request, label="get_channel_stats")
            if not response:
                for channel_id in batch:
                    _CHANNEL_STATS_CACHE[channel_id] = {
                        "channel_title": "",
                        "subscriber_count": 0,
                        "channel_verified": False,
                    }
                continue
            for item in response.get("items", []):
                channel_id = item.get("id")
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                hidden_subs = bool(stats.get("hiddenSubscriberCount"))
                subscriber_count = 0
                if not hidden_subs:
                    try:
                        subscriber_count = int(stats.get("subscriberCount") or 0)
                    except (TypeError, ValueError):
                        subscriber_count = 0
                _CHANNEL_STATS_CACHE[channel_id] = {
                    "channel_title": snippet.get("title") or "",
                    "subscriber_count": subscriber_count,
                    "channel_verified": False,  # YouTube Data API does not expose badge state.
                }
        except Exception as exc:
            print(f"[YOUTUBE] Channel stats lookup failed: {exc}")
            for channel_id in batch:
                _CHANNEL_STATS_CACHE[channel_id] = {
                    "channel_title": "",
                    "subscriber_count": 0,
                    "channel_verified": False,
                }
    return {channel_id: _CHANNEL_STATS_CACHE.get(channel_id, {}) for channel_id in unique_ids}

def get_video_comments(video_id, max_results=10):
    print(f"[YOUTUBE] Comment fetching disabled for monitoring: {video_id}")
    return []


def normalize_term(value: str) -> str:
    return " ".join((value or "").lower().split())


def sanitize_ignore_terms(ignore_terms: str | None, protected_terms: list[str]) -> list[str]:
    protected = {normalize_term(term) for term in protected_terms if normalize_term(term)}
    cleaned = []
    for term in (ignore_terms or "").split(","):
        term = term.strip()
        key = normalize_term(term)
        if not key:
            continue
        if key in protected:
            print(f"[YOUTUBE][DEBUG] Removed self-ignore term: {term}")
            continue
        cleaned.append(key)
    return list(dict.fromkeys(cleaned))


def parse_csv_terms(value: str | None) -> list[str]:
    return [term.strip() for term in (value or "").split(",") if term.strip()]


def subscriber_authority_score(subscriber_count: int) -> float:
    if subscriber_count >= 1_000_000:
        return 0.35
    if subscriber_count >= 100_000:
        return 0.25
    if subscriber_count >= 10_000:
        return 0.15
    if subscriber_count and subscriber_count < 1_000:
        return -0.3
    return 0.0

@router.post("/scrape-store-youtube")
def scrape_and_store_youtube(
    brand: str = Query(..., description="Brand name to search on YouTube"),
    specific_term: str = Query(None, description="Resolved brand/company name to search on YouTube (optional)"),
    entity_name: str = Query(None, description="Entity name for post-filtering (optional)"),
    ignore_terms: str = Query(None, description="Comma-separated terms to ignore (optional)"),
    official_channels: str = Query(None, description="Comma-separated official channel names (optional)"),
    request_id: int | None = Query(None, description="Monitor request id for structured logs")
):
    # Use the most specific resolved term if provided
    search_brand = specific_term if specific_term else brand
    results = []
    try:
        videos = search_videos(search_brand, max_results=50)
        for channel_id in discover_official_channel_ids(search_brand):
            videos.extend(search_videos(search_brand, max_results=10, channel_id=channel_id, order="date"))
    except Exception as exc:
        print(f"[YOUTUBE] Search failed for {search_brand}: {exc}")
        videos = []

    seen_video_ids = set()
    videos = [
        video
        for video in videos
        if not (video["video_id"] in seen_video_ids or seen_video_ids.add(video["video_id"]))
    ]
    channel_stats = get_channel_stats([video.get("channelId") for video in videos])
    print("[YOUTUBE][DEBUG] Raw videos:")
    for video in videos:
        print(f"  - {video['title']} | https://www.youtube.com/watch?v={video['video_id']}")
    for video in videos:
        video_url = f"https://www.youtube.com/watch?v={video['video_id']}"
        stats = channel_stats.get(video.get("channelId"), {})
        video_data = {
            "brand": brand,
            "video_id": video["video_id"],
            "video_url": video_url,
            "title": video["title"],
            "published": video["published"],
            "youtuber": video.get("channelTitle", ""),
            "channel_id": video.get("channelId", ""),
            "subscriber_count": stats.get("subscriber_count", 0),
            "channel_verified": bool(stats.get("channel_verified", False)),
            "comments": [],
        }
        results.append(video_data)
    print("[YOUTUBE][DEBUG] Before filtering:")
    for r in results:
        print(f"  - {r['title']} | {r['video_url']} | {r['youtuber']}")

    # --- Automatic post-filtering ---
    import re
    def is_exact_brand_match(text, brand):
        # Whole word, case-insensitive match
        return re.search(rf'\\b{re.escape(brand)}\\b', text, re.IGNORECASE) is not None

    # Use resolved entity_name for filtering
    brand_filter = entity_name if entity_name else search_brand
    brand_filter_lower = brand_filter.lower()
    import re
    def is_exact_brand_match(text, brand):
        # Only match as a whole word, not as hashtag or substring
        return re.search(rf'(?<![#@])\b{re.escape(brand)}\b', text, re.IGNORECASE) is not None

    dynamic_exclusions = sanitize_ignore_terms(
        ignore_terms,
        protected_terms=[brand, search_brand, brand_filter],
    )
    official_channel_names = {normalize_term(term) for term in parse_csv_terms(official_channels)}
    discard_reasons = {
        "ignore_term_match": 0,
        "low_confidence": 0,
        "duplicate": 0,
        "duplicate_title_channel": 0,
        "hard_noise_match": 0,
        "promotional_penalty": 0,
    }
    top_discarded = []

    def remember_discard(result, reason):
        discard_reasons[reason] = discard_reasons.get(reason, 0) + 1
        if len(top_discarded) < 15:
            top_discarded.append({
                "title": result.get("title", ""),
                "channel": result.get("youtuber", ""),
                "reason": reason,
            })

    hard_noise_terms = [
        "official music video",
        "lyrics",
        "love song",
        "audio",
        "topic",
        "rapper",
        "album",
        "feat.",
        "feat ",
        "ft.",
        "capo plaza",
        "didine canon",
        "christmas",
        "gift",
        "got a tesla",
    ]

    promotional_terms = [
        "official",
        "official video",
        "promo",
        "promotional",
        "commercial",
        "book now",
        "buy now",
        "launch",
        "launched",
        "reveal",
        "revealed",
        "event",
        "keynote",
        "livestream",
        "live stream",
        "stream",
        "trailer",
        "teaser",
        "tvc",
        "ad",
        "advertisement",
        "campaign",
        "sponsored",
        "shorts",
        *dynamic_exclusions,
    ]

    product_context_terms = [
        "ai",
        "autopilot",
        "automotive",
        "battery",
        "business",
        "car",
        "cars",
        "cybertruck",
        "deliver",
        "delivers",
        "delivery",
        "earnings",
        "electric vehicle",
        "ev",
        "factory",
        "fsd",
        "market",
        "model 3",
        "model s",
        "model x",
        "model y",
        "news",
        "price",
        "recall",
        "review",
        "revealed",
        "roadster",
        "sales",
        "semi",
        "software",
        "stock",
        "supercharger",
        "u-turn",
        "vehicle",
        "vehicles",
    ]

    trusted_media_channels = [
        "autocar",
        "car dekho",
        "cardekho",
        "carwow",
        "cnbc",
        "bloomberg",
        "faisal khan",
        "motor octane",
        "motoroctane",
        "overdrive",
        "reuters",
        "rushlane",
        "the verge",
        "top gear",
    ]

    def channel_authority_score(result):
        channel_lower = normalize_term(result.get("youtuber", ""))
        subscriber_count = int(result.get("subscriber_count") or 0)
        exact_official = channel_lower in official_channel_names
        likely_official = bool(
            brand_filter_lower
            and brand_filter_lower in channel_lower
            and subscriber_count >= 100_000
        )
        trusted_media = any(name in channel_lower for name in trusted_media_channels)

        score = 0.0
        if exact_official:
            score += 0.6
        elif likely_official:
            score += 0.35
        if result.get("channel_verified"):
            score += 0.25
        score += subscriber_authority_score(subscriber_count)
        if trusted_media:
            score += 0.2
        if channel_lower == brand_filter_lower and subscriber_count < 10_000 and not exact_official:
            score -= 0.25
        return max(-0.35, min(1.0, score))

    def youtube_entity_score(result):
        title = result.get("title", "")
        channel = result.get("youtuber", "")
        combined = f"{title} {channel}"
        if is_exact_brand_match(title, brand_filter):
            return 1.0
        if is_exact_brand_match(combined, brand_filter):
            return 0.8
        if normalize_term(brand_filter) in normalize_term(combined):
            return 0.6
        return 0.2

    def youtube_semantic_score(result):
        title = result.get("title", "")
        channel = result.get("youtuber", "")
        try:
            semantic = score_semantic_similarity(
                brand_name=brand_filter,
                title=title,
                text=channel,
                aliases=[brand, search_brand],
                brand_context=f"{brand_filter} {brand} company brand product review",
                threshold=0.35,
            )
            return float(semantic.get("semantic_score") or 0.0)
        except Exception as exc:
            print(f"[YOUTUBE][DEBUG] Semantic score failed for '{title[:60]}': {exc}")
            return 0.0

    def promotional_penalty(title_lower: str) -> float:
        hits = [term for term in promotional_terms if term and term in title_lower]
        penalty = min(0.35, 0.1 * len(hits))
        return round(penalty, 4)

    def youtube_relevance_score(result):
        title = result.get("title", "")
        title_lower = title.lower()

        if any(term in title_lower for term in hard_noise_terms):
            result["hard_noise_match"] = True
            return 0.0

        authority = channel_authority_score(result)
        semantic = youtube_semantic_score(result)
        entity = youtube_entity_score(result)
        context_bonus = 0.08 if any(term in title_lower for term in product_context_terms) else 0.0
        promo_penalty = promotional_penalty(title_lower)
        result["authority_score"] = round(authority, 4)
        result["semantic_score"] = round(semantic, 4)
        result["entity_score"] = round(entity, 4)
        result["promo_penalty"] = promo_penalty

        score = (
            0.5 * semantic
            + 0.3 * max(0.0, min(1.0, authority))
            + 0.2 * entity
            + context_bonus
            - promo_penalty
        )
        if re.search(r"^\s*[^|:\n]{2,80}\s+-\s+[^|:\n]{2,80}\s*$", title) and not any(term in title_lower for term in product_context_terms):
            score -= 0.35
        final_score = max(0.0, min(1.0, score))
        result["final_score"] = round(final_score, 4)
        return final_score

    def passes_final_youtube_filter(result, min_score=0.45):
        score = youtube_relevance_score(result)
        result["match_confidence"] = round(score, 4)
        if score < min_score:
            print(f"[YOUTUBE][DEBUG] Excluded by low confidence ({score:.2f}): {result.get('title', '')}")
            return False
        return True

    # Only true noise is hard-excluded. Promotional/official terms are penalties.
    HARD_EXCLUDE_TERMS = [
        "song", "music", "live session", "animal", "cat", "puma concolor",
        "black pumas", "mv", "band", "singer", "lyrics",
        "cover", "remix", "house cat", "dog", "wildlife", "nature", "zoo",
        "el puma", "puma blue", "official audio", "love song",
        "instrumental", "album", "rapper", "capo plaza", "didine canon",
    ]

    scored_candidates = []
    fallback_candidates = []
    seen = set()
    for r in results:
        title = r.get("title", "")
        video_id = r.get("video_id")
        if video_id in seen:
            remember_discard(r, "duplicate")
            continue
        seen.add(video_id)
        if any(term in title.lower() for term in HARD_EXCLUDE_TERMS):
            print(f"[YOUTUBE][DEBUG] Excluded by hard noise term: {title}")
            remember_discard(r, "hard_noise_match")
            continue
        score = youtube_relevance_score(r)
        r["match_confidence"] = round(score, 4)
        if r.get("promo_penalty", 0) > 0:
            discard_reasons["promotional_penalty"] += 1
        fallback_candidates.append(r)
        if r.get("hard_noise_match"):
            remember_discard(r, "hard_noise_match")
            continue
        if score >= 0.45:
            scored_candidates.append(r)
        else:
            print(f"[YOUTUBE][DEBUG] Excluded by low confidence ({score:.2f}): {title}")
            remember_discard(r, "low_confidence")

    ranked = sorted(
        scored_candidates,
        key=lambda item: (
            item.get("final_score", item.get("match_confidence", 0)),
            item.get("authority_score", 0),
            item.get("subscriber_count", 0),
        ),
        reverse=True,
    )

    if len(ranked) < 5:
        existing = {item.get("video_id") for item in ranked}
        rescue = sorted(
            [
                item
                for item in fallback_candidates
                if item.get("video_id") not in existing
                and item.get("final_score", item.get("match_confidence", 0)) >= 0.35
            ],
            key=lambda item: (
                item.get("final_score", item.get("match_confidence", 0)),
                item.get("authority_score", 0),
                item.get("subscriber_count", 0),
            ),
            reverse=True,
        )
        ranked.extend(rescue[: 5 - len(ranked)])

    final_videos = []
    seen_title_channel = set()
    for video in ranked:
        key = (
            normalize_term(video.get("title", "")),
            normalize_term(video.get("youtuber", "")),
        )
        if key in seen_title_channel:
            remember_discard(video, "duplicate_title_channel")
            continue
        seen_title_channel.add(key)
        final_videos.append(video)
        if len(final_videos) >= 5:
            break

    results = final_videos
    print("[YOUTUBE][DEBUG] After filtering:")
    for r in results:
        print(
            f"  - {r['title']} | {r['video_url']} | {r['youtuber']} "
            f"| subs={r.get('subscriber_count', 0)} score={r.get('final_score', 0)}"
        )
    if request_id:
        log_source_run(request_id, "youtube", {
            "brand": brand,
            "query": search_brand,
            "videos_found": len(videos),
            "videos_after_filter": len(results),
            "discarded": max(0, len(videos) - len(results)),
            "discard_reasons": {key: value for key, value in discard_reasons.items() if value},
            "top_discarded": top_discarded,
            "kept_titles": [r.get("title") for r in results],
            "kept_videos": [
                {
                    "title": r.get("title"),
                    "channel": r.get("youtuber"),
                    "verified": bool(r.get("channel_verified")),
                    "subscribers": r.get("subscriber_count", 0),
                    "authority_score": r.get("authority_score", 0),
                    "semantic_score": r.get("semantic_score"),
                    "entity_score": r.get("entity_score", 0),
                    "promo_penalty": r.get("promo_penalty", 0),
                    "final_score": r.get("final_score", r.get("match_confidence", 0)),
                }
                for r in results
            ],
        })
    # --- Kafka publishing ---
    try:
        if results:
            from kafka import KafkaProducer
            import json
            import os
            KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            producer.send("brand.youtube.global", {"videos": results})
            producer.flush()
            producer.close()
            print(f"[KAFKA] Published {len(results)} YouTube videos to brand.youtube.global")
    except Exception as kafka_e:
        print(f"[KAFKA ERROR] Could not publish to Kafka: {kafka_e}")
    return results
