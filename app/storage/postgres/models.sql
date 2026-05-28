CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS articles (
    article_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name VARCHAR(255),
    url TEXT UNIQUE,
    title TEXT,
    body_text TEXT,
    author VARCHAR(255),
    published_at TIMESTAMP,
    ingested_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sentiment_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID REFERENCES articles(article_id),
    sentiment_label VARCHAR(50),
    compound_score FLOAT,
    processed_at TIMESTAMP DEFAULT NOW()
);
