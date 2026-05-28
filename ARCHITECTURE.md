# Brand Monitoring Platform — Architecture & Data Flow (2026)

---

## 1. High-Level Architecture Diagram


```mermaid
graph TD
  U[User searches for a brand<br/>(Frontend: MentionsPage.jsx)] -->|calls fetchArticles(brand)| A[FastAPI Backend<br/>(/api/articles)]
  A -->|Loads config from .env| ENV[.env file]
  A -->|SQL query using env vars| DB[(Postgres DB)]
  DB -->|Articles + Sentiment| A
  A -->|Returns JSON| U
  U -->|Displays all fields| CARD[ArticleCard.jsx]
  subgraph Ingestion & Classification
    ING[Ingestion Scripts] -->|Raw data| KAFKA[Redpanda/Kafka]
    KAFKA -->|Batch| CONS[Kafka Consumer]
    CONS -->|Classify| CLF[hybrid_classifier.py]
    CLF -->|Enrich| CONS
    CONS -->|Save| DB
    CONS -->|Detect signals| SIG[reputation_signals.py]
    SIG -->|Save signals| DB
  end
```

---

## 2. Data Flow: What Goes In & Out of Redpanda

- **INTO Redpanda (Kafka):**
  - Raw articles/posts from each ingester (NewsAPI, Reddit, YouTube, etc)
  - Example message:
    ```json
    { "articles": [ { "title": "...", "url": "...", ... } ] }
    { "posts":    [ { "title": "...", "url": "...", ... } ] }
    { "videos":   [ { "title": "...", "url": "...", ... } ] }
    ```
- **OUT OF Redpanda:**
  - Each message is consumed by `kafka_consumer.py`
  - For each item:
    - Normalized and classified by `hybrid_classifier.py`
    - Enriched with: `sentiment`, `sentiment_confidence`, `emotion`, `emotion_confidence`, `primary_category`, etc.
    - Saved to DB (Postgres):
      - `articles` table (core info)
      - `sentiment_results` table (all classifier fields)
    - Reputation signals detected by `reputation_signals.py` and saved to `reputation_signals` table

---

## 3. File/Module Responsibilities

- **Ingestion Scripts**
  - `app/backend/app/api/reddit/reddit_scraper.py`
  - `app/backend/app/api/youtube/youtube_scraper.py`
  - `app/backend/app/api/newsapi/newsapi_ingester.py`
  - ...others
  - **Role:** Scrape/fetch data, publish to Redpanda/Kafka topic

- **Redpanda (Kafka/Redpanda cluster)**
  - **Role:** Message queue for all ingested data

- **Kafka Consumer**
  - `app/ai_pipeline/pipelines/kafka_consumer.py`
  - **Role:**
    - Consumes from Redpanda topics
    - Normalizes and classifies each item
    - Calls `hybrid_classifier.py` for sentiment/category/emotion
    - Calls `reputation_signals.py` for signal detection
    - Saves all results to Postgres

- **Classifier**
  - `app/ai_pipeline/sentiment/hybrid_classifier.py`
  - **Role:**
    - Returns all classifier fields for each item
    - Robust to API rate limits

- **Reputation Signal Detector**
  - `app/ai_pipeline/reputation_scoring/reputation_signals.py`
  - **Role:**
    - Detects signals (fraud, layoffs, crisis, etc.)
    - Assigns severity, tone, confidence
    - Saves to `reputation_signals` table

- **Database**
  - Tables: `articles`, `sentiment_results`, `reputation_signals`

- **FastAPI Backend**
  - `app/backend/app/api/routes/articles.py` (for /api/articles)
  - `app/backend/app/api/routes/reputation.py` (for /api/reputation/signals)
  - **Role:**
    - Serves all data to frontend

- **Frontend (React/Vite)**
  - `src/pages/MentionsPage.jsx` (all articles)
  - `src/pages/Reputation/index.jsx` (all signals)
  - **Role:**
    - Displays all classifier fields and reputation signals

---

## 4. Where You Are Now

- **Ingestion, classification, and DB save are working.**
- **Redpanda is receiving and queuing all ingested data.**
- **Kafka consumer is classifying and saving all fields (see terminal output).**
- **Frontend is patched to show all classifier fields (no dashes if data is present in DB/API).**
- **You are ready to build and display reputation signals.**

---

## 5. What You Can Do Now

- Ingest new data from any source (NewsAPI, Reddit, YouTube, etc)
- See all classifier fields (sentiment, confidence, emotion, etc) in the frontend
- Detect and display reputation signals (fraud, layoffs, crisis, etc) in a new Reputation tab
- Filter, search, and analyze all signals and articles in the UI

---

## 6. Next Steps: Reputation Signals

- Create the `reputation_signals` table (see SQL in your plan)
- Add `reputation_signals.py` and wire it into `kafka_consumer.py`
- Add `/api/reputation/signals` route
- Add a new Reputation tab/page in the frontend
- You will then have a full end-to-end pipeline for reputation event detection and display

---

## 7. Sidebar Tab Suggestion

Add a new tab:
- **Reputation**
  - Shows all detected signals, breakdowns, and filters
  - Route: `/reputation`

---

*This file documents the full architecture and current state of your brand monitoring platform as of May 2026.*
