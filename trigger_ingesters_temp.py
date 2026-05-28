
import requests

BRAND = "oppo"
BASE_URL = "http://localhost:8000/api"

# Trigger Reddit ingestion (POST)
try:
    reddit_url = f"{BASE_URL}/reddit/scrape-store-reddit"
    print(f"Triggering Reddit ingestion: {reddit_url}")
    r_resp = requests.post(reddit_url, params={"brand": BRAND}, timeout=120)
    print(f"Reddit response: {r_resp.status_code} {r_resp.text[:200]}")
except Exception as e:
    print(f"Reddit ingestion failed: {e}")

# Trigger YouTube ingestion (POST)
try:
    yt_url = f"{BASE_URL}/youtube/scrape-store-youtube"
    print(f"Triggering YouTube ingestion: {yt_url}")
    y_resp = requests.post(yt_url, params={"brand": BRAND}, timeout=120)
    print(f"YouTube response: {y_resp.status_code} {y_resp.text[:200]}")
except Exception as e:
    print(f"YouTube ingestion failed: {e}")
