from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STORAGE_DIR = Path(__file__).resolve().parents[4] / "storage" / "bw"
STORAGE_LOCK = threading.RLock()

CSV_SCHEMAS = {
    "companies.csv": [
        "company_id",
        "company_name",
        "industry",
        "brands_json",
        "keywords_json",
        "sources_json",
        "created_at",
        "updated_at",
    ],
    "products.csv": [
        "product_id",
        "company_id",
        "product_name",
        "description",
    ],
    "executives.csv": [
        "executive_id",
        "company_id",
        "executive_name",
        "role",
        "is_ceo",
    ],
    "campaigns.csv": [
        "campaign_id",
        "company_id",
        "campaign_name",
    ],
    "hashtags.csv": [
        "hashtag_id",
        "company_id",
        "hashtag",
    ],
    "mentions.csv": [
        "mention_id",
        "company_id",
        "company_name",
        "keyword",
        "keyword_type",
        "search_query",
        "source",
        "title",
        "content",
        "url",
        "author",
        "sentiment",
        "sentiment_score",
        "sentiment_confidence",
        "emotion",
        "emotion_confidence",
        "primary_category",
        "mention_confidence",
        "confidence_label",
        "quality_status",
        "matched_entities_json",
        "matched_because",
        "published_at",
        "collected_at",
    ],
}


def ensure_storage_files() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    for filename, headers in CSV_SCHEMAS.items():
        path = STORAGE_DIR / filename
        if path.exists() and path.stat().st_size:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                current_headers = next(csv.reader(handle), [])
            if current_headers != headers:
                rows = _read_rows(path)
                _write_rows(path, headers, rows)
            continue
        _write_rows(path, headers, [])


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.stat().st_size:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _normalized_name(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("#", " #").split())


def _contains_phrase(text: str, value: str) -> bool:
    phrase = _compact_text(value)
    return bool(phrase and phrase in text)


def _last_name(value: str) -> str:
    parts = [
        part.strip(".,")
        for part in str(value or "").split()
        if part.strip(".,")
    ]
    return parts[-1] if parts else ""


def _clean_strings(values: list[Any] | None) -> list[str]:
    return [
        cleaned
        for value in values or []
        if (cleaned := str(value or "").strip())
    ]


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        return _clean_strings(parsed if isinstance(parsed, list) else [])
    except (TypeError, json.JSONDecodeError):
        return []


def _json_object(value: str) -> dict[str, bool]:
    try:
        parsed = json.loads(value or "{}")
        return {
            str(key): bool(enabled)
            for key, enabled in parsed.items()
        } if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def list_companies() -> list[dict[str, str]]:
    with STORAGE_LOCK:
        ensure_storage_files()
        return [
            {
                "company_id": row.get("company_id") or "",
                "company_name": row.get("company_name") or "",
                "industry": row.get("industry") or "",
                "updated_at": row.get("updated_at") or "",
            }
            for row in _read_rows(STORAGE_DIR / "companies.csv")
        ]


def get_workspace(company_name: str) -> dict[str, Any] | None:
    normalized = _normalized_name(company_name)
    with STORAGE_LOCK:
        ensure_storage_files()
        companies = _read_rows(STORAGE_DIR / "companies.csv")
        company = next(
            (
                row
                for row in companies
                if _normalized_name(row.get("company_name") or "") == normalized
            ),
            None,
        )
        if company is None:
            return None

        company_id = company.get("company_id") or ""
        products = [
            {
                "name": row.get("product_name") or "",
                "description": row.get("description") or "",
            }
            for row in _read_rows(STORAGE_DIR / "products.csv")
            if row.get("company_id") == company_id
        ]
        executive_rows = [
            row
            for row in _read_rows(STORAGE_DIR / "executives.csv")
            if row.get("company_id") == company_id
        ]
        ceo_rows = [
            row
            for row in executive_rows
            if str(row.get("is_ceo") or "").lower() == "true"
        ]
        ceo_row = ceo_rows[0] if ceo_rows else None
        ceos = [
            {
                "name": row.get("executive_name") or "",
                "role": row.get("role") or "",
            }
            for row in ceo_rows
        ]
        executives = [
            {
                "name": row.get("executive_name") or "",
                "role": row.get("role") or "",
            }
            for row in executive_rows
            if str(row.get("is_ceo") or "").lower() != "true"
        ]
        campaigns = [
            row.get("campaign_name") or ""
            for row in _read_rows(STORAGE_DIR / "campaigns.csv")
            if row.get("company_id") == company_id
        ]
        hashtags = [
            row.get("hashtag") or ""
            for row in _read_rows(STORAGE_DIR / "hashtags.csv")
            if row.get("company_id") == company_id
        ]
        return {
            "companyId": company_id,
            "companyName": company.get("company_name") or "",
            "industry": company.get("industry") or "",
            "brands": _json_list(company.get("brands_json") or ""),
            "products": products,
            "ceo": {
                "name": ceo_row.get("executive_name") or "",
                "role": ceo_row.get("role") or "",
            } if ceo_row else {"name": "", "role": ""},
            "ceos": ceos,
            "executives": executives,
            "campaigns": campaigns,
            "hashtags": hashtags,
            "keywords": _json_list(company.get("keywords_json") or ""),
            "sources": _json_object(company.get("sources_json") or ""),
            "createdAt": company.get("created_at") or "",
            "updatedAt": company.get("updated_at") or "",
            "storageLocation": str(STORAGE_DIR),
        }


def save_workspace(payload: dict[str, Any]) -> dict[str, Any]:
    company_name = str(payload.get("companyName") or "").strip()
    if not company_name:
        raise ValueError("Company name is required")

    now = datetime.now(timezone.utc).isoformat()
    normalized = _normalized_name(company_name)
    with STORAGE_LOCK:
        ensure_storage_files()
        company_path = STORAGE_DIR / "companies.csv"
        companies = _read_rows(company_path)
        existing = next(
            (
                row
                for row in companies
                if _normalized_name(row.get("company_name") or "") == normalized
            ),
            None,
        )
        company_id = (existing or {}).get("company_id") or str(uuid.uuid4())
        company_row = {
            "company_id": company_id,
            "company_name": company_name,
            "industry": str(payload.get("industry") or "").strip(),
            "brands_json": json.dumps(_clean_strings(payload.get("brands")), ensure_ascii=False),
            "keywords_json": json.dumps(_clean_strings(payload.get("keywords")), ensure_ascii=False),
            "sources_json": json.dumps(payload.get("sources") or {}, ensure_ascii=False),
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        companies = [
            company_row
            if row.get("company_id") == company_id
            else row
            for row in companies
        ]
        if existing is None:
            companies.append(company_row)
        _write_rows(company_path, CSV_SCHEMAS["companies.csv"], companies)

        products = [
            row
            for row in _read_rows(STORAGE_DIR / "products.csv")
            if row.get("company_id") != company_id
        ]
        products.extend({
            "product_id": str(uuid.uuid4()),
            "company_id": company_id,
            "product_name": str(product.get("name") or "").strip(),
            "description": str(product.get("description") or "").strip(),
        } for product in payload.get("products") or [] if (
            str(product.get("name") or "").strip()
            or str(product.get("description") or "").strip()
        ))
        _write_rows(
            STORAGE_DIR / "products.csv",
            CSV_SCHEMAS["products.csv"],
            products,
        )

        executives = [
            row
            for row in _read_rows(STORAGE_DIR / "executives.csv")
            if row.get("company_id") != company_id
        ]
        ceos = payload.get("ceos") or []
        if not ceos:
            legacy_ceo = payload.get("ceo") or {}
            if (
                str(legacy_ceo.get("name") or "").strip()
                or str(legacy_ceo.get("role") or "").strip()
            ):
                ceos = [legacy_ceo]
        for ceo in ceos:
            if not (
                str(ceo.get("name") or "").strip()
                or str(ceo.get("role") or "").strip()
            ):
                continue
            executives.append({
                "executive_id": str(uuid.uuid4()),
                "company_id": company_id,
                "executive_name": str(ceo.get("name") or "").strip(),
                "role": str(ceo.get("role") or "").strip(),
                "is_ceo": "true",
            })
        executives.extend({
            "executive_id": str(uuid.uuid4()),
            "company_id": company_id,
            "executive_name": str(executive.get("name") or "").strip(),
            "role": str(executive.get("role") or "").strip(),
            "is_ceo": "false",
        } for executive in payload.get("executives") or [] if (
            str(executive.get("name") or "").strip()
            or str(executive.get("role") or "").strip()
        ))
        _write_rows(
            STORAGE_DIR / "executives.csv",
            CSV_SCHEMAS["executives.csv"],
            executives,
        )

        _replace_simple_rows(
            "campaigns.csv",
            company_id,
            "campaign_id",
            "campaign_name",
            payload.get("campaigns"),
        )
        _replace_simple_rows(
            "hashtags.csv",
            company_id,
            "hashtag_id",
            "hashtag",
            payload.get("hashtags"),
        )

    saved = get_workspace(company_name)
    if saved is None:
        raise RuntimeError("Workspace was written but could not be reloaded")
    return saved


def _infer_keyword_type(keyword: str, workspace: dict[str, Any]) -> str:
    normalized = _normalized_name(keyword)
    if not normalized:
        return "keyword"
    if _normalized_name(workspace.get("companyName") or "") == normalized:
        return "company"
    if any(_normalized_name(value) == normalized for value in workspace.get("brands") or []):
        return "brand"
    if any(_normalized_name(item.get("name") or "") == normalized for item in workspace.get("products") or []):
        return "product"
    leaders = [*(workspace.get("ceos") or []), *(workspace.get("executives") or [])]
    if any(_normalized_name(item.get("name") or "") == normalized for item in leaders):
        return "executive"
    if any(_normalized_name(value) == normalized for value in workspace.get("campaigns") or []):
        return "campaign"
    if any(_normalized_name(value) == normalized for value in workspace.get("hashtags") or []):
        return "hashtag"
    return "keyword"


def _confidence_label(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 65:
        return "medium"
    return "low"


def _evaluate_mention_quality(
    mention: dict[str, Any],
    workspace: dict[str, Any],
    title: str,
    content: str,
    source: str,
) -> dict[str, Any]:
    keyword = str(mention.get("keyword") or "").strip()
    keyword_type = str(mention.get("keywordType") or "").strip().casefold()
    if not keyword_type:
        keyword_type = _infer_keyword_type(keyword, workspace)

    text = _compact_text(" ".join([
        title,
        content,
        str(mention.get("author") or ""),
    ]))
    company_terms = _clean_strings([
        workspace.get("companyName"),
        *(workspace.get("brands") or []),
    ])
    product_terms = _clean_strings([
        item.get("name")
        for item in workspace.get("products") or []
    ])
    leader_terms = _clean_strings([
        item.get("name")
        for item in [*(workspace.get("ceos") or []), *(workspace.get("executives") or [])]
    ])
    campaign_terms = _clean_strings(workspace.get("campaigns"))
    hashtag_terms = _clean_strings(workspace.get("hashtags"))

    matched = {
        "company": [term for term in company_terms if _contains_phrase(text, term)],
        "products": [term for term in product_terms if _contains_phrase(text, term)],
        "executives": [],
        "campaigns": [term for term in campaign_terms if _contains_phrase(text, term)],
        "hashtags": [term for term in hashtag_terms if _contains_phrase(text, term)],
    }
    for leader in leader_terms:
        last_name = _last_name(leader)
        if _contains_phrase(text, leader) or (len(last_name) >= 4 and _contains_phrase(text, last_name)):
            matched["executives"].append(leader)

    keyword_matched = _contains_phrase(text, keyword)
    source_score = 10 if source in {"google_news", "newsapi"} else 7 if source == "youtube" else 5
    score = source_score
    reasons: list[str] = []

    if matched["company"]:
        score += 50
        reasons.append(f"Matched company/brand: {', '.join(matched['company'][:3])}")
    if keyword_matched:
        score += 25
        reasons.append(f"Matched monitored {keyword_type}: {keyword}")
    if matched["products"]:
        score += 25
        reasons.append(f"Matched product: {', '.join(matched['products'][:3])}")
    if matched["executives"]:
        score += 25
        reasons.append(f"Matched executive: {', '.join(matched['executives'][:3])}")
    if matched["campaigns"]:
        score += 15
        reasons.append(f"Matched campaign: {', '.join(matched['campaigns'][:3])}")
    if matched["hashtags"]:
        score += 15
        reasons.append(f"Matched hashtag: {', '.join(matched['hashtags'][:3])}")

    if keyword_type == "campaign" and not matched["company"]:
        score = min(score, 45)
        reasons.append("Campaign mention needs a company or brand co-occurrence")
    if keyword_type == "executive" and keyword:
        last_name = _last_name(keyword)
        if len(last_name) >= 4 and not _contains_phrase(text, last_name):
            score = min(score, 45)
            reasons.append("Executive mention needs the normalized last name")

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("Stored as a broad monitored keyword match")

    threshold = int(os.getenv("BW_MENTION_MIN_CONFIDENCE", "60"))
    return {
        "keyword_type": keyword_type or "keyword",
        "score": score,
        "label": _confidence_label(score),
        "quality_status": "verified" if score >= threshold else "filtered",
        "matched_entities": matched,
        "matched_because": "; ".join(reasons),
    }


def save_mentions(company_name: str, mentions: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.sentiment_service import enrich_item_sentiment

    workspace = get_workspace(company_name)
    if workspace is None:
        raise ValueError("Company workspace not found")

    company_id = workspace["companyId"]
    now = datetime.now(timezone.utc).isoformat()
    with STORAGE_LOCK:
        ensure_storage_files()
        path = STORAGE_DIR / "mentions.csv"
        rows = _read_rows(path)
        existing_keys = {
            _mention_key(
                row.get("source") or "",
                row.get("url") or "",
                row.get("title") or "",
            )
            for row in rows
        }
        added = 0
        filtered = 0
        for mention in mentions:
            source = str(mention.get("source") or "").strip()
            title = str(mention.get("title") or "").strip()
            content = str(mention.get("content") or "").strip()
            url = str(mention.get("url") or "").strip()
            if not source or not (title or content or url):
                continue
            quality = _evaluate_mention_quality(mention, workspace, title, content, source)
            if quality["quality_status"] == "filtered":
                filtered += 1
                continue
            key = _mention_key(source, url, title or content)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            enriched = enrich_item_sentiment({
                "title": title,
                "body_text": content,
                "sentiment_label": mention.get("sentiment"),
                "sentiment_score": mention.get("sentimentScore"),
                "sentiment_confidence": mention.get("sentimentConfidence"),
                "emotion": mention.get("emotion"),
                "emotion_confidence": mention.get("emotionConfidence"),
            })
            rows.append({
                "mention_id": str(uuid.uuid4()),
                "company_id": company_id,
                "company_name": workspace["companyName"],
                "keyword": str(mention.get("keyword") or "").strip(),
                "keyword_type": quality["keyword_type"],
                "search_query": str(mention.get("searchQuery") or "").strip(),
                "source": source,
                "title": title,
                "content": content,
                "url": url,
                "author": str(mention.get("author") or "").strip(),
                "sentiment": str(enriched.get("sentiment_label") or "").strip(),
                "sentiment_score": enriched.get("sentiment_score"),
                "sentiment_confidence": enriched.get("sentiment_confidence"),
                "emotion": str(enriched.get("emotion") or "").strip(),
                "emotion_confidence": enriched.get("emotion_confidence"),
                "primary_category": str(mention.get("primaryCategory") or "").strip(),
                "mention_confidence": quality["score"],
                "confidence_label": quality["label"],
                "quality_status": quality["quality_status"],
                "matched_entities_json": json.dumps(quality["matched_entities"], ensure_ascii=False),
                "matched_because": quality["matched_because"],
                "published_at": str(mention.get("publishedAt") or "").strip(),
                "collected_at": now,
            })
            added += 1
        _write_rows(path, CSV_SCHEMAS["mentions.csv"], rows)

    return {
        "received": len(mentions),
        "added": added,
        "filtered": filtered,
        "duplicates": max(0, len(mentions) - added - filtered),
        "total": sum(1 for row in rows if row.get("company_id") == company_id),
        "storageLocation": str(path),
    }


def get_mentions(company_name: str) -> list[dict[str, str]]:
    from app.services.sentiment_service import enrich_item_sentiment

    workspace = get_workspace(company_name)
    if workspace is None:
        raise ValueError("Company workspace not found")
    company_id = workspace["companyId"]
    with STORAGE_LOCK:
        ensure_storage_files()
        path = STORAGE_DIR / "mentions.csv"
        rows = _read_rows(path)
        changed = False
        for row in rows:
            if row.get("company_id") != company_id:
                continue
            if (
                row.get("sentiment")
                and row.get("sentiment_score") not in {None, ""}
                and row.get("emotion")
            ):
                continue
            enriched = enrich_item_sentiment({
                "title": row.get("title") or "",
                "body_text": row.get("content") or "",
                "sentiment_label": row.get("sentiment") or "",
                "sentiment_score": _optional_float(row.get("sentiment_score")),
                "sentiment_confidence": _optional_float(row.get("sentiment_confidence")),
                "emotion": row.get("emotion") or "",
                "emotion_confidence": _optional_float(row.get("emotion_confidence")),
            })
            row["sentiment"] = enriched.get("sentiment_label") or "neutral"
            row["sentiment_score"] = enriched.get("sentiment_score")
            row["sentiment_confidence"] = enriched.get("sentiment_confidence")
            row["emotion"] = enriched.get("emotion") or "indifference"
            row["emotion_confidence"] = enriched.get("emotion_confidence")
            changed = True
        if changed:
            _write_rows(path, CSV_SCHEMAS["mentions.csv"], rows)
        return [row for row in rows if row.get("company_id") == company_id]


def _mention_key(source: str, url: str, title: str) -> str:
    normalized_source = _normalized_name(source)
    normalized_url = str(url or "").strip().casefold().rstrip("/")
    normalized_title = _normalized_name(title)
    return f"{normalized_source}|{normalized_url or normalized_title}"


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _replace_simple_rows(
    filename: str,
    company_id: str,
    id_field: str,
    value_field: str,
    values: list[Any] | None,
) -> None:
    rows = [
        row
        for row in _read_rows(STORAGE_DIR / filename)
        if row.get("company_id") != company_id
    ]
    rows.extend({
        id_field: str(uuid.uuid4()),
        "company_id": company_id,
        value_field: value,
    } for value in _clean_strings(values))
    _write_rows(STORAGE_DIR / filename, CSV_SCHEMAS[filename], rows)
