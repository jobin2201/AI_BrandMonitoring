import os
from dotenv import load_dotenv

# Load .env before using os.getenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../../app/backend/.env'))

import requests
from kafka import KafkaProducer
import json

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
print("Loaded NEWS_API_KEY:", NEWS_API_KEY)
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = "brand.news.global"

def fetch_news(query="Apple"):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "apiKey": NEWS_API_KEY
    }
    print(f"[NewsAPI] Querying NewsAPI with: {query}")
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    if 'articles' in data:
        print(f"Total articles fetched: {len(data['articles'])}")
    else:
        print("No 'articles' key found in response.")
    return data

def publish_to_kafka(data, topic=KAFKA_TOPIC):
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    producer.send(topic, data)
    producer.flush()
    producer.close()

if __name__ == "__main__":
    import sys
    # Accept both brand and resolved entity_name as arguments
    if len(sys.argv) < 2:
        print("ERROR: Brand argument required.")
        sys.exit(1)
    brand = sys.argv[1]
    # If entity_name is provided, use it for NewsAPI query
    entity_name = sys.argv[2] if len(sys.argv) > 2 else brand
    print(f"[NewsAPI] Using entity_name for NewsAPI query: {entity_name}")
    data = fetch_news(entity_name)
    print(data)
    publish_to_kafka(data)
    print(f"Published news data for '{entity_name}' to Kafka topic '{KAFKA_TOPIC}'")
    # Print total number of articles at the end for clear visibility
    if data and 'articles' in data:
        print(f"\nTotal articles fetched and published: {len(data['articles'])}")
    else:
        print("\nNo articles found or published.")
