import requests, os
from dotenv import load_dotenv
load_dotenv('app/backend/.env')
key = os.getenv('NEWS_API_KEY')
print(f'Loaded NEWS_API_KEY: {key}')
q = '"lays"'
url = 'https://newsapi.org/v2/everything'
params = {
    'q': q, 
    'from': '2026-05-16', 
    'to': '2026-05-23', 
    'sortBy': 'popularity', 
    'apiKey': key, 
    'language': 'en'
}
r = requests.get(url, params=params)
print(f'Status: {r.status_code}')
print(f'Response: {r.text[:1000]}')
