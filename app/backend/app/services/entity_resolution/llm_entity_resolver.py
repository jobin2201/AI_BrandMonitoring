import os
import json
import re
import requests
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env'))

def groq_resolve(query):
    from groq import Groq, GroqError
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    if not api_key:
        raise GroqError("GROQ_API_KEY not set in environment or .env file")
    client = Groq(api_key=api_key)

    prompt = f"""
You are resolving a user search into a brand/company profile for a brand monitoring system.

User searched: "{query}"

Return ONLY valid JSON with this exact shape:
{{
  "entity_name": "Most likely official brand/company name",
  "entity_type": "company | product | vehicle | service",
  "industry": "specific industry",
  "primary_category": "main category, e.g. smartphones, SUV, cloud platform",
  "subcategory": "more specific category/segment, e.g. android smartphones, mid-size SUV",
  "competitor_category": "the category to compare competitors within",
  "manufacturer": "owning company/manufacturer if this is a product, otherwise empty string",
  "categories": ["important categories this company/product participates in"],
  "description": "one sentence company context",
  "aliases": ["known aliases or product-family terms"],
  "search_terms": ["high precision search terms for this company/brand"],
  "positive_terms": ["industry/context terms that indicate relevance"],
  "ignore_terms": ["terms to exclude for ambiguity/noise"],
  "negative_terms": ["terms that indicate wrong entity meanings"]
}}

Rules:
- Resolve ambiguous nouns to the company/brand when one exists.
- Do not return generic nouns as entity_name.
- For broad companies, include their major categories in categories.
- For specific products/vehicles/services, identify manufacturer and competitor_category.
- competitor_category must be narrow enough for comparison, e.g. "smartphones", "mid-size SUV", "cloud AI platforms".
- Include terms that separate the company from songs, animals, fruit, movies, memes, libraries, and unrelated meanings.
- Keep arrays concise: 4 to 10 items each.
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    content = response.choices[0].message.content or ""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def print_groq_limits():
    api_key = os.getenv("GROQ_API_KEY")
    base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    if not api_key:
        print("--- LIVE GROQ LIMITS ---")
        print("GROQ_API_KEY missing")
        return

    print("--- LIVE GROQ LIMITS ---")
    try:
        response = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        print(f"Status: {response.status_code}")
        header_names = [
            "x-ratelimit-limit-requests",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ]
        for name in header_names:
            print(f"{name}: {response.headers.get(name, 'unavailable')}")
    except Exception as exc:
        print(f"Could not fetch Groq limits: {exc}")
