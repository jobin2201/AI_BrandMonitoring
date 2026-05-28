import os
import json
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
    The platform monitors ONLY brands and companies.

    User searched: "{query}"

    Determine:
    1. Most likely company/brand
    2. Industry
    3. Related search terms
    4. Terms to ignore

    Return ONLY valid JSON.
    """

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    content = response.choices[0].message.content
    return json.loads(content)
