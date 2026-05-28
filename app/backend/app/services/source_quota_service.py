from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DEFAULT_SOURCE_QUOTAS = {
    "newsapi": 1000,
    "google_news": 1000,
    "reddit": 1000,
    "youtube": 1000,
}


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        database=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def initialize_source_usage(source_name: str):
    conn = get_conn()
    cur = conn.cursor()
    quota_limit = DEFAULT_SOURCE_QUOTAS.get(source_name, 1000)
    try:
        cur.execute(
            """
            INSERT INTO source_usage (
                source_name,
                requests_today,
                quota_limit,
                reset_at,
                updated_at
            )
            SELECT %s, 0, %s, NOW() + INTERVAL '1 day', NOW()
            WHERE NOT EXISTS (
                SELECT 1
                FROM source_usage
                WHERE source_name = %s
            )
            """,
            (source_name, quota_limit, source_name),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[QUOTA] Could not initialize usage for {source_name}: {exc}")
    finally:
        cur.close()
        conn.close()


def can_use_source(source_name: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        initialize_source_usage(source_name)
        reset_source_usage_if_needed(source_name)

        cur.execute(
            """
            SELECT requests_today, quota_limit
            FROM source_usage
            WHERE source_name = %s
            """,
            (source_name,),
        )
        row = cur.fetchone()
        if not row:
            return True

        requests_today, quota_limit = row
        if quota_limit is None:
            return True
        return int(requests_today or 0) < int(quota_limit)
    except Exception as exc:
        print(f"[QUOTA] Could not check quota for {source_name}: {exc}")
        return True
    finally:
        cur.close()
        conn.close()


def reset_source_usage_if_needed(source_name: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE source_usage
            SET requests_today = 0,
                reset_at = reset_at + INTERVAL '1 day',
                updated_at = NOW()
            WHERE source_name = %s
              AND reset_at IS NOT NULL
              AND reset_at <= NOW()
            """,
            (source_name,),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[QUOTA] Could not reset usage for {source_name}: {exc}")
    finally:
        cur.close()
        conn.close()


def increment_source_usage(source_name: str):
    conn = get_conn()
    cur = conn.cursor()
    try:
        initialize_source_usage(source_name)
        cur.execute(
            """
            UPDATE source_usage
            SET requests_today = COALESCE(requests_today, 0) + 1,
                updated_at = NOW()
            WHERE source_name = %s
            """,
            (source_name,),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[QUOTA] Could not increment usage for {source_name}: {exc}")
    finally:
        cur.close()
        conn.close()
