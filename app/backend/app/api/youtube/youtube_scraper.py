from fastapi import APIRouter, Query
from googleapiclient.discovery import build
from datetime import datetime
import os
from dotenv import load_dotenv
load_dotenv()

router = APIRouter()

API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not API_KEY:
    raise RuntimeError("YOUTUBE_API_KEY not set in environment or .env file")

youtube = build("youtube", "v3", developerKey=API_KEY)

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
        response = request.execute()
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
        response = youtube.search().list(
            q=brand,
            part="snippet",
            type="channel",
            maxResults=5,
            order="relevance",
        ).execute()
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

def get_video_comments(video_id, max_results=10):
    print(f"[YOUTUBE] Comment fetching disabled for monitoring: {video_id}")
    return []

@router.post("/scrape-store-youtube")
def scrape_and_store_youtube(
    brand: str = Query(..., description="Brand name to search on YouTube"),
    specific_term: str = Query(None, description="Resolved brand/company name to search on YouTube (optional)"),
    entity_name: str = Query(None, description="Entity name for post-filtering (optional)"),
    ignore_terms: str = Query(None, description="Comma-separated terms to ignore (optional)")
):
    # Use the most specific resolved term if provided
    search_brand = specific_term if specific_term else brand
    results = []
    videos = search_videos(search_brand, max_results=50)
    for channel_id in discover_official_channel_ids(search_brand):
        videos.extend(search_videos(search_brand, max_results=10, channel_id=channel_id, order="date"))

    seen_video_ids = set()
    videos = [
        video
        for video in videos
        if not (video["video_id"] in seen_video_ids or seen_video_ids.add(video["video_id"]))
    ]
    print("[YOUTUBE][DEBUG] Raw videos:")
    for video in videos:
        print(f"  - {video['title']} | https://www.youtube.com/watch?v={video['video_id']}")
    for video in videos:
        video_url = f"https://www.youtube.com/watch?v={video['video_id']}"
        video_data = {
            "brand": brand,
            "video_id": video["video_id"],
            "video_url": video_url,
            "title": video["title"],
            "published": video["published"],
            "youtuber": video.get("channelTitle", ""),
            "comments": []
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

    dynamic_exclusions = [
        term.strip().lower()
        for term in (ignore_terms or "").split(",")
        if term.strip()
    ]

    blocked_terms = [
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
    ]

    def youtube_relevance_score(result):
        title = result.get("title", "")
        title_lower = title.lower()
        channel_lower = result.get("youtuber", "").strip().lower()

        if any(term in title_lower for term in blocked_terms):
            return 0.0

        score = 0.0
        if is_exact_brand_match(title, brand_filter):
            score += 0.45
        if channel_lower == brand_filter_lower:
            score += 0.4
        elif brand_filter_lower and brand_filter_lower in channel_lower:
            score += 0.3
        if any(term in title_lower for term in product_context_terms):
            score += 0.35
        if re.search(r"^\s*[^|:\n]{2,80}\s+-\s+[^|:\n]{2,80}\s*$", title) and not any(term in title_lower for term in product_context_terms):
            score -= 0.35
        return max(0.0, min(1.0, score))

    def passes_final_youtube_filter(result, min_score=0.72):
        score = youtube_relevance_score(result)
        result["match_confidence"] = round(score, 4)
        if score < min_score:
            print(f"[YOUTUBE][DEBUG] Excluded by low confidence ({score:.2f}): {result.get('title', '')}")
            return False
        return True

    # Exclude animal/music/ambiguous terms
    EXCLUDE_TERMS = [
        "song", "music", "live session", "animal", "cat", "puma concolor",
        "black pumas", "mv", "official video", "band", "singer", "lyrics",
        "cover", "remix", "house cat", "dog", "wildlife", "nature", "zoo",
        "shorts", "el puma", "puma blue", "official audio", "love song",
        "instrumental", "album", "rapper", "capo plaza", "didine canon",
        *dynamic_exclusions,
    ]

    # 1. Try to get only official brand channel videos
    official_channel_videos = [r for r in results if r.get('youtuber','').strip().lower() == brand_filter_lower]
    filtered = []
    if official_channel_videos:
        filtered = [r for r in official_channel_videos if is_exact_brand_match(r.get('title',''), brand_filter) and not any(term in r.get('title','').lower() for term in EXCLUDE_TERMS)]
        # If not enough, fill with more from official channel
        if len(filtered) < 5:
            for r in official_channel_videos:
                if r not in filtered and not any(term in r.get('title','').lower() for term in EXCLUDE_TERMS):
                    filtered.append(r)
                if len(filtered) >= 5:
                    break
    # 2. If not enough, add most viewed videos with brand as whole word in title (not hashtag), not excluded
    if len(filtered) < 5:
        for r in results:
            title = r.get('title','')
            if r in filtered:
                continue
            if any(term in title.lower() for term in EXCLUDE_TERMS):
                print(f"[YOUTUBE][DEBUG] Excluded by term: {title}")
                continue
            if is_exact_brand_match(title, brand_filter):
                filtered.append(r)
            if len(filtered) >= 5:
                break
    # 3. If still not enough, fill with next best (not excluded) videos
    if len(filtered) < 5:
        for r in results:
            title = r.get('title','')
            if r in filtered:
                continue
            if any(term in title.lower() for term in EXCLUDE_TERMS):
                continue
            filtered.append(r)
            if len(filtered) >= 5:
                break
    # Remove duplicates by video_id
    seen = set()
    unique_filtered = []
    for r in filtered:
        if not passes_final_youtube_filter(r):
            continue
        if r['video_id'] not in seen:
            unique_filtered.append(r)
            seen.add(r['video_id'])

    if len(unique_filtered) < 5:
        for r in results:
            if len(unique_filtered) >= 5:
                break
            if r['video_id'] in seen:
                continue
            if not passes_final_youtube_filter(r):
                continue
            unique_filtered.append(r)
            seen.add(r['video_id'])

    results = unique_filtered[:5]
    print("[YOUTUBE][DEBUG] After filtering:")
    for r in results:
        print(f"  - {r['title']} | {r['video_url']} | {r['youtuber']}")
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
