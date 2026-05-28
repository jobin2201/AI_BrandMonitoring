import requests

HEADERS = {
    "User-Agent": "BrandMonitorAI/1.0 (jobin@example.com)"
}

def search_wikipedia(query):
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        # Bias search toward company/brand, not animal/fruit
        "srsearch": f"{query} company OR {query} brand OR {query} manufacturer OR {query} corporation OR {query} organization",
        "format": "json"
    }
    response = requests.get(url, params=params, headers=HEADERS)
    return response.json()

def get_summary(title):
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    response = requests.get(url, headers=HEADERS)
    return response.json()

def wikipedia_resolve(query):
    search_results = search_wikipedia(query)
    search_list = search_results.get("query", {}).get("search", [])
    if not search_list:
        return None
    top_title = search_list[0]["title"].replace(" ", "_")
    summary = get_summary(top_title)
    extract = summary.get("extract", "")
    return {
        "entity_name": summary.get("title", query),
        "description": extract,
        "industry": "unknown",
        "search_terms": [query, summary.get("title", query)],
        "ignore_terms": []
    }
