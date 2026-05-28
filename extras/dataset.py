"""
Reputation Intelligence — Multi-Platform Data Fetcher
Supports: Google Play, Apple App Store, News (RSS + URL), 
          Google Business, Yelp, TripAdvisor, Trustpilot, Glassdoor
"""
from google_play_scraper import Sort, reviews
import requests
import json
import re
import feedparser
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from bs4 import BeautifulSoup
import config


# ═══════════════════════════════════════════════════════
# GOOGLE PLAY
# ═══════════════════════════════════════════════════════

def fetch_google_play_reviews(app_id=None, count=None):
    """Fetch reviews from Google Play Store."""
    if app_id is None:
        app_id = config.TARGET_APP_ID
    if count is None:
        count = config.NUM_REVIEWS_TO_FETCH

    print(f"🌐 [Google Play] Fetching {count} reviews for {app_id}...")
    try:
        result, _ = reviews(app_id, lang='en', country='us', sort=Sort.NEWEST, count=count)
        formatted = []
        today = datetime.now()
        for i, r in enumerate(result):
            formatted.append({
                "id": f"gp_{i+1}",
                "text": r['content'],
                "rating": r['score'],
                "platform": "google_play",
                "date": r['at'],
                "days_ago": (today - r['at']).days,
                "author": r.get('userName', 'Anonymous'),
                "helpful_count": r.get('thumbsUpCount', 0),
            })
        print(f"✅ [Google Play] Fetched {len(formatted)} reviews.")
        return formatted
    except Exception as e:
        print(f"❌ [Google Play] Error: {e}")
        return []


def search_google_play_apps(query, limit=5, lang="en", country="us"):
    """
    Search Google Play by app name. Returns a list of candidates with their package IDs.
    Each candidate: {appId, title, developer, score, icon, installs}.
    """
    if not query or not query.strip():
        return []
    try:
        from google_play_scraper import search
        results = search(query.strip(), lang=lang, country=country, n_hits=limit)
        cleaned = []
        for r in results:
            app_id = r.get("appId")
            if not app_id:
                continue
            cleaned.append({
                "appId": app_id,
                "title": r.get("title", "Unknown"),
                "developer": r.get("developer", "Unknown"),
                "score": r.get("score"),
                "icon": r.get("icon"),
                "installs": r.get("installs", ""),
            })
        print(f"🔎 [Google Play Search] '{query}' → {len(cleaned)} match(es)")
        return cleaned
    except Exception as e:
        print(f"❌ [Google Play Search] Error: {e}")
        return []


def search_apple_app_store_apps(query, limit=5, country="us"):
    """
    Search Apple App Store by app name via the public iTunes Search API.
    Each candidate: {appId, title, developer, score, icon, ratings_count}.
    """
    if not query or not query.strip():
        return []
    try:
        url = "https://itunes.apple.com/search"
        params = {
            "term": query.strip(),
            "entity": "software",
            "limit": limit,
            "country": country,
        }
        response = requests.get(url, params=params, timeout=20)
        if response.status_code != 200:
            print(f"❌ [Apple Search] HTTP {response.status_code}")
            return []
        data = response.json()
        cleaned = []
        for r in data.get("results", []):
            track_id = r.get("trackId")
            if not track_id:
                continue
            cleaned.append({
                "appId": str(track_id),
                "title": r.get("trackName", "Unknown"),
                "developer": r.get("artistName", "Unknown"),
                "score": r.get("averageUserRating"),
                "icon": r.get("artworkUrl100"),
                "ratings_count": r.get("userRatingCount", 0),
            })
        print(f"🔎 [Apple Search] '{query}' → {len(cleaned)} match(es)")
        return cleaned
    except Exception as e:
        print(f"❌ [Apple Search] Error: {e}")
        return []


# ═══════════════════════════════════════════════════════
# APPLE APP STORE
# ═══════════════════════════════════════════════════════

def fetch_apple_app_store_reviews(app_id=None, country="us", count=None):
    """Fetch Apple App Store reviews using public RSS feed."""
    if app_id is None:
        app_id = "585027354"
    if count is None:
        count = config.PLATFORMS["apple_app_store"]["max_reviews"]

    print(f"🌐 [Apple App Store] Fetching reviews for app ID {app_id}...")
    formatted = []
    today = datetime.now(tz=timezone.utc)

    try:
        pages_needed = min(10, -(-count // 50))
        for page in range(1, pages_needed + 1):
            rss_url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews"
                f"/page={page}/id={app_id}/sortby=mostrecent/json"
            )
            response = requests.get(rss_url, timeout=30)
            if response.status_code != 200:
                print(f"⚠️ [Apple] Page {page} failed: HTTP {response.status_code}")
                break

            data = response.json()
            entries = data.get('feed', {}).get('entry', [])
            if not entries:
                break

            if page == 1 and entries and 'im:rating' not in entries[0]:
                entries = entries[1:]

            for entry in entries:
                if len(formatted) >= count:
                    break
                try:
                    content = entry.get('content', {}).get('label', '') \
                              or entry.get('summary', {}).get('label', '')
                    rating = int(entry.get('im:rating', {}).get('label', 3))
                    author = entry.get('author', {}).get('name', {}).get('label', 'Anonymous')
                    date_str = entry.get('updated', {}).get('label', '')

                    try:
                        review_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    except Exception:
                        review_date = today - timedelta(days=30)

                    formatted.append({
                        "id": f"ios_{len(formatted)+1}",
                        "text": content,
                        "rating": rating,
                        "platform": "apple_app_store",
                        "date": review_date,
                        "days_ago": (today - review_date).days,
                        "author": author,
                        "helpful_count": 0,
                    })
                except Exception as e:
                    print(f"⚠️ [Apple] Skipped entry: {e}")
                    continue

            if len(formatted) >= count:
                break

        print(f"✅ [Apple App Store] Fetched {len(formatted)} reviews.")
        return formatted
    except Exception as e:
        print(f"❌ [Apple App Store] Error: {e}")
        return []


# ═══════════════════════════════════════════════════════
# NEWS — RSS FEEDS
# ═══════════════════════════════════════════════════════

def fetch_rss_articles(feed_urls, max_per_feed=10):
    """Fetch articles from RSS feeds using feedparser."""
    all_articles = []
    for url in feed_urls:
        try:
            print(f"🌐 [RSS] Parsing feed: {url}...")
            feed = feedparser.parse(url)
            source_name = feed.feed.get('title', url)

            for entry in feed.entries[:max_per_feed]:
                # Extract content
                content = ""
                if 'content' in entry:
                    content = entry.content[0].value
                elif 'summary' in entry:
                    content = entry.summary
                elif 'description' in entry:
                    content = entry.description
                else:
                    content = entry.get('title', '')

                # Clean HTML tags
                soup = BeautifulSoup(content, 'html.parser')
                content = soup.get_text(separator=' ', strip=True)

                # Parse date
                pub_date = datetime.now()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6])

                all_articles.append({
                    "id": f"rss_{len(all_articles)+1}",
                    "text": content[:2500],
                    "title": entry.get('title', 'Untitled'),
                    "url": entry.get('link', ''),
                    "platform": "news_rss",
                    "date": pub_date,
                    "days_ago": (datetime.now() - pub_date).days,
                    "source": source_name,
                    "author": entry.get('author', 'Unknown'),
                    "rating": 3,  # Neutral default for news
                })
            print(f"   ✅ Got {min(len(feed.entries), max_per_feed)} articles from {source_name}")
        except Exception as e:
            print(f"❌ [RSS] Error parsing {url}: {e}")

    print(f"✅ [RSS] Total articles fetched: {len(all_articles)}")
    return all_articles


# ═══════════════════════════════════════════════════════
# NEWS — SINGLE URL SCRAPING
# ═══════════════════════════════════════════════════════

def fetch_news_by_url(url):
    """Scrape a single news article URL. Uses newspaper3k with BS4 fallback."""
    print(f"🌐 [News URL] Scraping: {url}...")

    # Try newspaper3k first
    try:
        from newspaper import Article
        article = Article(url, language='en')
        article.download()
        article.parse()

        pub_date = article.publish_date or datetime.now()
        return [{
            "id": "url_1",
            "text": article.text[:3000],
            "title": article.title,
            "url": url,
            "platform": "news_url",
            "date": pub_date,
            "days_ago": (datetime.now() - pub_date).days,
            "source": article.source_url or url,
            "author": ", ".join(article.authors) if article.authors else "Unknown",
            "rating": 3,
        }]
    except Exception as e:
        print(f"⚠️ [News URL] newspaper3k failed: {e}")
        print(f"   Trying BeautifulSoup fallback...")

    # Fallback: requests + BeautifulSoup
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=30)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title_tag = soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else 'Untitled'

        # Try article tag first
        article_tag = soup.find('article')
        if article_tag:
            text = article_tag.get_text(separator=' ', strip=True)
        else:
            # Fallback to all paragraphs
            paragraphs = soup.find_all('p')
            text = ' '.join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40)

        return [{
            "id": "url_1",
            "text": text[:3000],
            "title": title,
            "url": url,
            "platform": "news_url",
            "date": datetime.now(),
            "days_ago": 0,
            "source": url,
            "author": "Unknown",
            "rating": 3,
        }]
    except Exception as e:
        print(f"❌ [News URL] Fallback also failed: {e}")
        return []


# ═══════════════════════════════════════════════════════
# GOOGLE NEWS — RSS (primary) + GNews (fallback)
# ═══════════════════════════════════════════════════════

def _build_google_news_rss_url(query, language="en", country="US", period=None):
    """Build a Google News RSS search URL.

    period: '1h' | '12h' | '1d' | '7d' | '1m' | None
    """
    hl = f"{language}-{country}"
    ceid = f"{country}:{language}"
    q_parts = [query.strip()]
    if period:
        q_parts.append(f"when:{period}")
    q = " ".join(p for p in q_parts if p)
    return (
        f"https://news.google.com/rss/search?"
        f"q={quote(q)}&hl={hl}&gl={country}&ceid={quote(ceid)}"
    )


def _fetch_google_news_via_rss(query, max_results=20, language="en",
                               country="US", period=None):
    """Primary path: Google News RSS via feedparser. Zero extra deps."""
    url = _build_google_news_rss_url(query, language, country, period)
    print(f"🌐 [Google News / RSS] {url}")

    # Use requests so we can set a UA and surface HTTP errors cleanly
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    if not feed.entries:
        raise RuntimeError("RSS returned 0 entries")

    today = datetime.now()
    articles = []
    for entry in feed.entries[:max_results]:
        # Description/summary
        raw_html = entry.get("summary", "") or entry.get("description", "")
        clean_text = BeautifulSoup(raw_html, "html.parser").get_text(
            separator=" ", strip=True
        )

        # Publication date
        pub_date = today
        if getattr(entry, "published_parsed", None):
            pub_date = datetime(*entry.published_parsed[:6])
        elif getattr(entry, "updated_parsed", None):
            pub_date = datetime(*entry.updated_parsed[:6])

        # Source name lives in entry.source.title for Google News
        source_name = "Google News"
        src = entry.get("source")
        if isinstance(src, dict):
            source_name = src.get("title", source_name)
        elif hasattr(src, "title"):
            source_name = src.title

        articles.append({
            "id": f"gnews_{len(articles)+1}",
            "text": (clean_text or entry.get("title", ""))[:2500],
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "platform": "news_rss",   # reuse existing news pipeline
            "date": pub_date,
            "days_ago": (today - pub_date).days,
            "source": source_name,
            "author": entry.get("author", "Unknown"),
            "rating": 3,
        })

    print(f"   ✅ [Google News / RSS] Got {len(articles)} articles")
    return articles


def _fetch_google_news_via_gnews(query, max_results=20, language="english",
                                 country="US", period="7d"):
    """Fallback path: the `gnews` package. Install with: pip install gnews"""
    from gnews import GNews   # imported lazily so it's optional

    print(f"🌐 [Google News / GNews] query='{query}' country={country}")
    gn = GNews(
        language=language,
        country=country,
        period=period,
        max_results=max_results,
    )
    raw = gn.get_news(query) or []
    if not raw:
        raise RuntimeError("GNews returned 0 results")

    today = datetime.now()
    articles = []
    for item in raw[:max_results]:
        # gnews date format: 'Mon, 12 May 2025 09:00:00 GMT'
        pub_date = today
        date_str = item.get("published date") or item.get("published_date") or ""
        if date_str:
            try:
                pub_date = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
            except Exception:
                pass

        publisher = item.get("publisher") or {}
        if isinstance(publisher, dict):
            source_name = publisher.get("title", "Google News")
        else:
            source_name = str(publisher)

        articles.append({
            "id": f"gnews_{len(articles)+1}",
            "text": (item.get("description") or item.get("title", ""))[:2500],
            "title": item.get("title", "Untitled"),
            "url": item.get("url", ""),
            "platform": "news_rss",
            "date": pub_date,
            "days_ago": (today - pub_date).days,
            "source": source_name,
            "author": "Unknown",
            "rating": 3,
        })

    print(f"   ✅ [Google News / GNews] Got {len(articles)} articles")
    return articles


def fetch_google_news(query, max_results=20, language="en",
                      country="US", period="7d"):
    """
    Fetch news from Google News for a search query.

    Strategy: try the raw Google News RSS feed first (no extra dependency
    and works with what you already have). If that fails — bad network,
    Google rate-limit, zero results — fall back to the `gnews` package.

    Args:
        query (str): keyword(s) to search, e.g. 'Tesla earnings'
        max_results (int): how many articles to return
        language (str): 'en', 'hi', 'fr', ...
        country (str): 'US', 'IN', 'GB', ...
        period (str): '1h' | '12h' | '1d' | '7d' | '1m' | None

    Returns: list of article dicts matching the existing news_rss schema.
    """
    if not query or not query.strip():
        print("⚠️ [Google News] Empty query — skipping.")
        return []

    print(f"\n🔎 [Google News] Searching for: '{query}' "
          f"(country={country}, lang={language}, period={period})")

    # ── PRIMARY: RSS feed ───────────────────────────────
    try:
        return _fetch_google_news_via_rss(
            query=query,
            max_results=max_results,
            language=language,
            country=country,
            period=period,
        )
    except Exception as e:
        print(f"⚠️ [Google News / RSS] Failed: {e}")
        print(f"   ↪ Falling back to GNews package...")

    # ── FALLBACK: gnews package ─────────────────────────
    try:
        # gnews uses full language names ('english') not ISO codes
        lang_map = {
            "en": "english", "hi": "hindi", "fr": "french",
            "de": "german", "es": "spanish", "pt": "portuguese",
            "it": "italian", "ja": "japanese", "ko": "korean",
            "zh": "chinese simplified", "ru": "russian",
        }
        gnews_lang = lang_map.get(language, "english")
        return _fetch_google_news_via_gnews(
            query=query,
            max_results=max_results,
            language=gnews_lang,
            country=country,
            period=period or "7d",
        )
    except ImportError:
        print("❌ [Google News / GNews] Package not installed.")
        print("   Install with:  pip install gnews")
        return []
    except Exception as e:
        print(f"❌ [Google News / GNews] Failed: {e}")
        return []


# ═══════════════════════════════════════════════════════
# REVIEW PLATFORMS (existing code, kept for completeness)
# ═══════════════════════════════════════════════════════

def fetch_google_business_reviews(place_id=None, business_name=None, count=None):
    if count is None:
        count = config.PLATFORMS["google_business"]["max_reviews"]
    print(f"🌐 [Google Business] Fetching reviews...")
    reviews_data = []
    if place_id and config.GOOGLE_PLACES_API_KEY:
        try:
            url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=reviews&key={config.GOOGLE_PLACES_API_KEY}"
            response = requests.get(url, timeout=30)
            data = response.json()
            if data.get('status') == 'OK':
                place_reviews = data['result'].get('reviews', [])
                today = datetime.now()
                for i, r in enumerate(place_reviews[:count]):
                    review_date = datetime.fromtimestamp(r['time'])
                    reviews_data.append({
                        "id": f"gb_{i+1}", "text": r.get('text', ''),
                        "rating": r.get('rating', 3), "platform": "google_business",
                        "date": review_date, "days_ago": (today - review_date).days,
                        "author": r.get('author_name', 'Anonymous'), "helpful_count": 0,
                    })
                print(f"✅ [Google Business] Fetched {len(reviews_data)} reviews.")
                return reviews_data
        except Exception as e:
            print(f"⚠️ [Google Business] API failed: {e}")
    print(f"⚠️ [Google Business] No API key or place_id. Skipping.")
    return []


def fetch_yelp_reviews(business_alias=None, count=None):
    if count is None:
        count = config.PLATFORMS["yelp"]["max_reviews"]
    print(f"🌐 [Yelp] Fetching reviews...")
    if config.YELP_API_KEY and business_alias:
        try:
            business_id = business_alias.replace('https://www.yelp.com/biz/', '').split('?')[0]
            headers = {"Authorization": f"Bearer {config.YELP_API_KEY}"}
            url = f"https://api.yelp.com/v3/businesses/{business_id}/reviews?limit={count}&sort_by=newest"
            response = requests.get(url, headers=headers, timeout=30)
            data = response.json()
            if 'reviews' in data:
                today = datetime.now()
                reviews_data = []
                for i, r in enumerate(data['reviews']):
                    review_date = datetime.strptime(r['time_created'], '%Y-%m-%d %H:%M:%S')
                    reviews_data.append({
                        "id": f"yp_{i+1}", "text": r['text'], "rating": r['rating'],
                        "platform": "yelp", "date": review_date,
                        "days_ago": (today - review_date).days,
                        "author": r['user'].get('name', 'Anonymous'), "helpful_count": 0,
                    })
                print(f"✅ [Yelp] Fetched {len(reviews_data)} reviews.")
                return reviews_data
        except Exception as e:
            print(f"⚠️ [Yelp] API failed: {e}")
    print(f"⚠️ [Yelp] No API key or alias. Skipping.")
    return []


def fetch_tripadvisor_reviews(location_url=None, count=None):
    if count is None:
        count = config.PLATFORMS["tripadvisor"]["max_reviews"]
    print(f"🌐 [Tripadvisor] Fetching reviews...")
    if config.TRIPADVISOR_API_KEY and location_url:
        try:
            location_id = re.search(r'-d(\d+)-', location_url)
            if location_id:
                location_id = location_id.group(1)
                url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/reviews?key={config.TRIPADVISOR_API_KEY}&limit={count}"
                response = requests.get(url, headers={"accept": "application/json"}, timeout=30)
                data = response.json()
                if 'data' in data:
                    today = datetime.now()
                    reviews_data = []
                    for i, r in enumerate(data['data']):
                        review_date = datetime.strptime(r['published_date'], '%Y-%m-%d')
                        reviews_data.append({
                            "id": f"ta_{i+1}", "text": r.get('text', ''), "rating": r.get('rating', 3),
                            "platform": "tripadvisor", "date": review_date,
                            "days_ago": (today - review_date).days,
                            "author": r.get('user', {}).get('username', 'Anonymous'),
                            "helpful_count": r.get('helpful_votes', 0),
                        })
                    print(f"✅ [Tripadvisor] Fetched {len(reviews_data)} reviews.")
                    return reviews_data
        except Exception as e:
            print(f"⚠️ [Tripadvisor] API failed: {e}")
    print(f"⚠️ [Tripadvisor] No API key or URL. Skipping.")
    return []


def fetch_trustpilot_reviews(business_domain=None, count=None):
    if count is None:
        count = config.PLATFORMS["trustpilot"]["max_reviews"]
    print(f"🌐 [Trustpilot] Fetching reviews for {business_domain}...")
    if business_domain:
        try:
            search_url = f"https://www.trustpilot.com/api/businessunits/find?name={quote(business_domain)}"
            response = requests.get(search_url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                unit_id = data.get('id')
                if unit_id:
                    reviews_url = f"https://www.trustpilot.com/api/businessunits/{unit_id}/reviews?perPage={count}&page=1"
                    rev_response = requests.get(reviews_url, timeout=30)
                    rev_data = rev_response.json()
                    today = datetime.now()
                    reviews_data = []
                    for i, r in enumerate(rev_data.get('reviews', [])):
                        review_date = datetime.fromisoformat(r['dates']['publishedDate'].replace('Z', '+00:00'))
                        reviews_data.append({
                            "id": f"tp_{i+1}", "text": r.get('text', ''), "rating": r.get('stars', 3),
                            "platform": "trustpilot", "date": review_date,
                            "days_ago": (today - review_date).days,
                            "author": r.get('consumer', {}).get('displayName', 'Anonymous'), "helpful_count": 0,
                        })
                    print(f"✅ [Trustpilot] Fetched {len(reviews_data)} reviews.")
                    return reviews_data
        except Exception as e:
            print(f"⚠️ [Trustpilot] API failed: {e}")
    print(f"⚠️ [Trustpilot] No domain provided. Skipping.")
    return []


def fetch_glassdoor_reviews(company_name=None, employer_id=None, count=None):
    if count is None:
        count = config.PLATFORMS["glassdoor"]["max_reviews"]
    print(f"🌐 [Glassdoor] Fetching reviews for {company_name}...")
    if config.GLASSDOOR_API_KEY and employer_id:
        try:
            url = f"https://api.glassdoor.com/api/api.htm?v=1&format=json&t.p=1&t.k={config.GLASSDOOR_API_KEY}&action=employer-reviews&id={employer_id}&page=1&limit={count}"
            response = requests.get(url, timeout=30)
            data = response.json()
            if 'response' in data:
                today = datetime.now()
                reviews_data = []
                for i, r in enumerate(data['response'].get('reviews', [])):
                    review_date = datetime.strptime(r['reviewDateTime'], '%Y-%m-%d %H:%M:%S.%f')
                    reviews_data.append({
                        "id": f"gd_{i+1}",
                        "text": r.get('pros', '') + ' ' + r.get('cons', ''),
                        "rating": r.get('overallRating', 3),
                        "platform": "glassdoor",
                        "date": review_date,
                        "days_ago": (today - review_date).days,
                        "author": r.get('reviewer', 'Anonymous'),
                        "helpful_count": 0,
                    })
                print(f"✅ [Glassdoor] Fetched {len(reviews_data)} reviews.")
                return reviews_data
        except Exception as e:
            print(f"⚠️ [Glassdoor] API failed: {e}")
    print(f"⚠️ [Glassdoor] No API key. Skipping.")
    return []


# ═══════════════════════════════════════════════════════
# UNIFIED FETCHER
# ═══════════════════════════════════════════════════════

def fetch_all_data(configs):
    """
    Fetch data from multiple sources based on configuration.
    
    configs = {
        "google_play": {"app_id": "com.whatsapp", "enabled": True, "max_reviews": 50},
        "apple_app_store": {"app_id": "310633997", "enabled": True, "max_reviews": 50},
        "news_rss": {"feed_urls": [...], "enabled": True, "max_per_feed": 10},
        "news_url": {"url": "https://...", "enabled": True},
        "google_business": {"place_id": "...", "enabled": False},
        "yelp": {"business_alias": "...", "enabled": False},
        "tripadvisor": {"location_url": "...", "enabled": False},
        "trustpilot": {"business_domain": "...", "enabled": False},
        "glassdoor": {"company_name": "...", "employer_id": "...", "enabled": False},
    }
    """
    all_items = []
    stats = {}

    for source, cfg in configs.items():
        if not cfg.get("enabled", False):
            continue

        print(f"\n{'─'*50}")
        print(f"  Fetching from: {source.upper()}")
        print(f"{'─'*50}")

        items = []

        if source == "google_play":
            items = fetch_google_play_reviews(
                app_id=cfg.get("app_id"),
                count=cfg.get("max_reviews", 200)
            )
        elif source == "apple_app_store":
            items = fetch_apple_app_store_reviews(
                app_id=cfg.get("app_id"),
                count=cfg.get("max_reviews", 200)
            )
        elif source == "news_rss":
            items = fetch_rss_articles(
                feed_urls=cfg.get("feed_urls", config.DEFAULT_RSS_FEEDS),
                max_per_feed=cfg.get("max_per_feed", 10)
            )
        elif source == "news_url":
            items = fetch_news_by_url(url=cfg.get("url"))
        elif source == "google_news":
            items = fetch_google_news(
                query=cfg.get("query", ""),
                max_results=cfg.get("max_results", 20),
                language=cfg.get("language", "en"),
                country=cfg.get("country", "US"),
                period=cfg.get("period", "7d"),
            )
        elif source == "google_business":
            items = fetch_google_business_reviews(
                place_id=cfg.get("place_id"),
                business_name=cfg.get("business_name"),
                count=cfg.get("max_reviews", 100)
            )
        elif source == "yelp":
            items = fetch_yelp_reviews(
                business_alias=cfg.get("business_alias"),
                count=cfg.get("max_reviews", 100)
            )
        elif source == "tripadvisor":
            items = fetch_tripadvisor_reviews(
                location_url=cfg.get("location_url"),
                count=cfg.get("max_reviews", 100)
            )
        elif source == "trustpilot":
            items = fetch_trustpilot_reviews(
                business_domain=cfg.get("business_domain"),
                count=cfg.get("max_reviews", 100)
            )
        elif source == "glassdoor":
            items = fetch_glassdoor_reviews(
                company_name=cfg.get("company_name"),
                employer_id=cfg.get("employer_id"),
                count=cfg.get("max_reviews", 100)
            )

        all_items.extend(items)
        stats[source] = len(items)

    # Print summary
    print(f"\n{'='*50}")
    print("  FETCH SUMMARY")
    print(f"{'='*50}")
    total = 0
    for source, count in stats.items():
        print(f"  {source:<20}: {count:>4} items")
        total += count
    print(f"  {'TOTAL':<20}: {total:>4} items")
    print(f"{'='*50}")

    return all_items