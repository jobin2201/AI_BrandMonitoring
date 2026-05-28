# What Happens When You Search a Brand (Behind the Scenes)

This document explains the full flow and tools used when you search for a brand in the platform, including how data is fetched from NewsAPI, Reddit, and YouTube, how it is processed, and how it is displayed back in the frontend. It also covers the role of the Mentions page, the tools used at each layer, and the infrastructure (Redpanda, Postgres, Docker Compose).

---

## 1. User Action: Search for a Brand (Frontend)
- **Where:** `frontend/src/pages/MentionsPage.jsx`
- **What happens:**
  - User enters a brand and clicks search.
  - The frontend calls `fetchArticles(brand)` (in `src/api/newsApi.js`).
  - This sends a GET request to `/api/articles?brand=...` on the FastAPI backend.

---

## 2. Backend: How Data is Fetched
- **Where:** `backend/app/api/routes/articles.py`
- **What happens:**
  - The backend loads config from `.env` (Postgres, API keys, Kafka, etc).
  - Connects to Postgres and runs a SQL query to fetch articles and their sentiment for the brand.
  - Returns all fields (title, source, published_at, sentiment, emotion, confidence, etc).

### How Data Gets Into the Database
- **Ingestion Scripts:**
  - `app/backend/app/api/newsapi/newsapi_ingester.py` (NewsAPI)
  - `app/backend/app/api/reddit/reddit_scraper.py` (Reddit)
  - `app/backend/app/api/youtube/youtube_scraper.py` (YouTube)
  - These scripts fetch data from their respective APIs using API keys from `.env`.
  - They publish raw data to Redpanda (Kafka-compatible message queue).

- **Redpanda (Kafka):**
  - Runs as a container (see `kafka/docker-compose.yml`).
  - Queues all ingested data for processing.

- **Kafka Consumer:**
  - `app/ai_pipeline/pipelines/kafka_consumer.py`
  - Consumes messages from Redpanda.
  - Calls `hybrid_classifier.py` to classify sentiment, emotion, etc.
  - Calls `reputation_signals.py` to detect reputation events.
  - Saves all results to Postgres.

---

## 3. How Data is Displayed Back (Frontend)
- **Where:** `frontend/src/pages/MentionsPage.jsx`, `frontend/src/components/cards/ArticleCard.jsx`
- **What happens:**
  - The frontend receives the JSON response from the backend.
  - Merges results from NewsAPI, Reddit, and YouTube.
  - Displays all classifier fields (sentiment, confidence, emotion, etc) in cards.

---

## 4. The Mentions Page
- **File:** `frontend/src/pages/MentionsPage.jsx`
- **Role:**
  - Aggregates and displays all articles/posts/videos for the searched brand.
  - Shows a summary bar (positive/negative/neutral counts).
  - Renders each result using `ArticleCard.jsx`.

---

## 5. Tools Used at Each Layer

### Frontend
- **React (Vite):** UI framework
- **Axios:** For API requests
- **Custom hooks/context:** For state management

### Backend
- **FastAPI:** API server
- **psycopg2:** Postgres database access
- **dotenv:** Loads environment variables
- **Kafka-python:** Kafka/Redpanda integration
- **Hybrid Classifier:** RoBERTa + Groq for sentiment/emotion

### Data Pipeline
- **Redpanda:** Kafka-compatible message queue (see Docker Compose)
- **Postgres:** Database for articles, sentiment, reputation signals

### Infrastructure
- **Docker Compose:**
  - Orchestrates Redpanda, Redpanda Console, Postgres, Minio
  - (See `kafka/docker-compose.yml`)

---

## 6. Docker Compose (kafka/docker-compose.yml)
- **redpanda:** Main message queue for ingestion pipeline
- **redpanda-console:** Web UI for inspecting topics/messages
- **postgres:** Database for all articles and results
- **minio:** (Optional) Object storage for large files/assets

---

## 7. Project Structure (Key Parts)
- **app/ai_pipeline/**: All ML, classification, and signal detection code
- **app/backend/app/api/**: All API routes and ingestion scripts
- **app/backend/app/core/**: Config, DB, and core backend logic
- **frontend/src/pages/**: All main UI pages (Mentions, Reputation, etc)
- **frontend/src/components/cards/**: UI cards for displaying articles
- **kafka/docker-compose.yml**: Infrastructure for Redpanda, Postgres, etc

---

## 8. Frontend Structure (Key Parts)
- **src/pages/MentionsPage.jsx**: Main mentions/search page
- **src/api/newsApi.js**: Fetches articles from backend
- **src/components/cards/ArticleCard.jsx**: Displays each article/post
- **src/pages/Reputation/**: (For reputation signals)

---

## 9. Summary
- When you search for a brand, the frontend calls the backend, which fetches from Postgres (populated by the ingestion/classification pipeline). All tools and infrastructure (Redpanda, Postgres, Docker Compose) work together to ingest, classify, store, and display the data in real time.
