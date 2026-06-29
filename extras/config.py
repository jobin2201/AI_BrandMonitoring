"""
Reputation Intelligence — Configuration
Hybrid: RoBERTa (local) for sentiment + Your LLM for categories/emotions/aspects
"""

# ── YOUR LOCAL LLM ──
import os

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8081")

# ── DEFAULT APP SETTINGS ──
TARGET_APP_ID = "com.google.android.apps.maps"
NUM_REVIEWS_TO_FETCH = 200
DAYS_TO_ANALYZE = 30

# ── PLATFORM CONFIGS ──
# Social media APIs SKIPPED per your request
PLATFORMS = {
    "google_play":       {"enabled": True,  "max_reviews": 200, "label": "Google Play"},
    "apple_app_store":   {"enabled": True,  "max_reviews": 200, "label": "Apple App Store"},
    "google_business":   {"enabled": True,  "max_reviews": 100, "label": "Google Business"},
    "yelp":              {"enabled": True,  "max_reviews": 100, "label": "Yelp"},
    "tripadvisor":       {"enabled": True,  "max_reviews": 100, "label": "TripAdvisor"},
    "trustpilot":        {"enabled": True,  "max_reviews": 100, "label": "Trustpilot"},
    "glassdoor":         {"enabled": True,  "max_reviews": 100, "label": "Glassdoor"},
    "news_rss":          {"enabled": True,  "max_articles": 50, "label": "News (RSS)"},
    "news_url":          {"enabled": True,  "label": "News (URL)"},
}

# ── REVIEW CATEGORIES (for apps, products, services) ──
REVIEW_CATEGORIES = {
    "performance":       "Bugs, crashes, speed, stability, loading, freezing, battery",
    "ui_ux":             "Design, layout, navigation, interface, fonts, dark mode, intuitive",
    "features":          "Functionality, missing features, updates, tools, capabilities",
    "ads_monetization":  "Ads, popups, subscriptions, pricing, paywalls, cost, premium",
    "support":           "Customer support, developer response, help center, service",
    "security_privacy":  "Data, permissions, login, trust, safety, privacy policy",
    "general":           "General feedback without specific category",
}

# ── NEWS CATEGORIES (for articles, press, media) ──
NEWS_CATEGORIES = {
    "corporate_reputation": "Company reputation, brand image, public perception, trust",
    "product_service":      "Product launches, service quality, features, innovation",
    "leadership":           "CEO, executives, management decisions, leadership changes",
    "financial_performance": "Earnings, revenue, stock price, profits, financial results",
    "legal_regulatory":     "Lawsuits, regulations, compliance, legal issues, policy",
    "esg":                  "Environmental, social, governance, sustainability, CSR",
    "competition":          "Competitors, market share, industry ranking, rivalry",
    "general":              "General news without specific business category",
}

# ── UNIFIED LABELS FOR DISPLAY ──
CATEGORY_LABELS = {
    # Reviews
    "performance":       ("⚡ Performance", "Bugs, crashes, speed, stability"),
    "ui_ux":             ("🎨 UI / UX", "Design, layout, navigation, ease of use"),
    "features":          ("🔧 Features", "Functionality, missing features, updates"),
    "ads_monetization":  ("💰 Ads & Pricing", "Ads, subscriptions, paywalls, cost"),
    "support":           ("🛟 Support", "Customer support, developer response"),
    "security_privacy":  ("🔒 Security & Privacy", "Data, permissions, login, trust"),
    # News
    "corporate_reputation": ("🏢 Corporate Reputation", "Brand image, public perception"),
    "product_service":      ("📦 Product & Service", "Launches, quality, innovation"),
    "leadership":           ("👔 Leadership", "Executives, management decisions"),
    "financial_performance": ("💹 Financial Performance", "Earnings, revenue, stock"),
    "legal_regulatory":     ("⚖️ Legal & Regulatory", "Lawsuits, compliance, policy"),
    "esg":                  ("🌱 ESG", "Environmental, social, governance"),
    "competition":          ("🎯 Competition", "Competitors, market share"),
    # Shared
    "general":           ("💬 General", "Items without a specific category"),
}

VALID_EMOTIONS = ["joy", "anger", "disgust", "frustration", "trust", "indifference"]

# ── DEFAULT RSS NEWS SOURCES ──
DEFAULT_RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://www.reutersagency.com/feed/?taxonomy=markets&post_type=reuters-best",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
]

# ── API KEYS (fill if you have them) ──
GOOGLE_PLACES_API_KEY = ""   # For Google Business reviews
YELP_API_KEY = ""            # For Yelp Fusion API
TRIPADVISOR_API_KEY = ""     # For TripAdvisor Content API
FACEBOOK_ACCESS_TOKEN = ""   # Left empty — social media skipped per request
GLASSDOOR_API_KEY = ""       # Requires partner agreement
