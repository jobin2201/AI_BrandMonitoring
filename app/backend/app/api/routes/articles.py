
from fastapi import APIRouter, Query
import psycopg2
import os
from dotenv import load_dotenv


router = APIRouter()
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env'))


@router.get("/articles")
def get_articles(brand: str = Query(..., description="Brand to search for")):
    import subprocess, time

    # Resolve brand context using the shared resolver manager.
    from app.services.entity_resolution.resolver_manager import resolve_brand
    brand_info = resolve_brand(brand)
    entity_name = brand_info.get("entity_name") or brand
    brand_normalized = entity_name.replace(" ", "").lower()
    search_terms = brand_info.get("search_terms") or [entity_name]
    exclude_terms = brand_info.get("ignore_terms") or brand_info.get("exclude_terms") or []

    # When calling scrapers, pass the specific_term as a parameter
    # Example for calling Reddit/YouTube scrapers (pseudo-code):
    # reddit_results = call_reddit_scraper(brand=brand, specific_term=specific_term)
    # youtube_results = call_youtube_scraper(brand=brand, specific_term=specific_term)

    # Always fetch NewsAPI results live, never save to DB
    import requests
    import re
    import socket
    import sys
    import platform
    from bs4 import BeautifulSoup
    from datetime import datetime, timedelta
    NEWS_API_KEY = os.getenv("NEWS_API_KEY")
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    url = "https://newsapi.org/v2/everything"
    debug_info = {}
    debug_info["python_executable"] = sys.executable
    debug_info["python_version"] = platform.python_version()
    debug_info["NEWS_API_KEY"] = "set" if NEWS_API_KEY else "missing"
    try:
        debug_info["newsapi_ip"] = socket.gethostbyname("newsapi.org")
    except Exception as e:
        debug_info["newsapi_ip"] = f"DNS error: {e}"
    # Test NewsAPI request
    try:
        test_resp = requests.get("https://newsapi.org/v2/top-headlines", params={"country": "us", "apiKey": NEWS_API_KEY}, timeout=5)
        debug_info["test_status"] = test_resp.status_code
        debug_info["test_json"] = test_resp.json()
    except Exception as e:
        debug_info["test_status"] = f"error: {e}"
        debug_info["test_json"] = None
    # Use the exact NewsAPI query as in the working terminal test
    newsapi_query = f'"{brand}"'
    params = {
        "q": newsapi_query,
        "from": week_ago.isoformat(),
        "to": today.isoformat(),
        "sortBy": "popularity",
        "apiKey": NEWS_API_KEY,
        "language": "en"
    }
    news_data = None
    newsapi_error = None
    debug_source = None
    try:
        response = requests.get(url, params=params, timeout=10)
        news_data = response.json()
    except Exception as e:
        print(f"[NEWSAPI][ERROR] {e}")
        newsapi_error = str(e)
        debug_info["main_newsapi_error"] = str(e)

    def is_english(text):
        # Heuristic: at least 80% ASCII letters or spaces
        if not text:
            return False
        ascii_letters = sum(1 for c in text if c.isascii() and (c.isalpha() or c.isspace()))
        return ascii_letters / max(len(text), 1) > 0.8

    news_results = []
    # If NewsAPI succeeded and returned articles, return all as-is (no filtering)
    if news_data and isinstance(news_data, dict) and "articles" in news_data and news_data.get("status") == "ok":
        print(f"[NEWSAPI][DEBUG] Returning ALL {len(news_data['articles'])} articles from NewsAPI for '{entity_name}' (no filtering)")
        brand_lower = brand.lower()
        count_with_brand = 0
        for idx, article in enumerate(news_data.get("articles", [])):
            title = article.get("title", "")
            print(f"[NEWSAPI][DEBUG][{idx}] Article title: {title}")
            if brand_lower in title.lower():
                count_with_brand += 1
            news_results.append({
                "title": title,
                "source_name": article.get("source", {}).get("name"),
                "url": article.get("url"),
                "published_at": article.get("publishedAt"),
                "sentiment_label": None,
                "sentiment_score": None,
                "primary_category": None,
                "emotion": None,
                "aspect_sentiments": {},
                "sentiment_confidence": None,
                "sentiment_breakdown": None,
                "emotion_confidence": None,
                "llm_used": None,
            })
        print(f"[NEWSAPI][DEBUG] {count_with_brand} articles had the brand name '{brand}' in the title.")
        debug_source = "newsapi"
        print(f"[NEWSAPI][DEBUG] Returned {len(news_results)} articles (no filtering)")
        return {
            "brand_context": brand_info,
            "newsapi_results": news_results,
            "debug_source": debug_source,
            "error": None if news_results else "No NewsAPI articles returned.",
            "debug_info": debug_info
        }
    # If NewsAPI failed, return error and all debug info
    print(f"[NEWSAPI][ERROR] NewsAPI fetch failed or returned no articles. news_data={news_data} error={newsapi_error}")
    return {
        "brand_context": brand_info,
        "newsapi_results": [],
        "debug_source": "newsapi",
        "error": newsapi_error or (news_data.get("message") if isinstance(news_data, dict) and "message" in news_data else "NewsAPI returned no results."),
        "debug_info": debug_info
    }
