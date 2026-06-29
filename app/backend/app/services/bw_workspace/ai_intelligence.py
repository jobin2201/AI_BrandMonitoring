from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.services.bw_workspace.repository import get_mentions, get_workspace


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def generate_workspace_intelligence(company_name: str) -> dict[str, Any]:
    workspace = get_workspace(company_name)
    if workspace is None:
        raise ValueError("Company workspace not found")

    mentions = get_mentions(company_name)
    if not mentions:
        raise ValueError("No stored mentions found. Run Brand Monitoring first.")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing from backend environment")

    source_counts = Counter(row.get("source") or "unknown" for row in mentions)
    sentiment_counts = Counter(row.get("sentiment") or "neutral" for row in mentions)
    keyword_counts = Counter(row.get("keyword") or company_name for row in mentions)
    product_names = [
        str(item.get("name") or "").strip()
        for item in workspace.get("products") or []
        if str(item.get("name") or "").strip()
    ]
    product_counts = Counter()
    for row in mentions:
        keyword = str(row.get("keyword") or "").strip().casefold()
        matched_product = next(
            (name for name in product_names if name.casefold() == keyword),
            None,
        )
        if matched_product:
            product_counts[matched_product] += 1

    evidence = sorted(
        mentions,
        key=lambda row: row.get("published_at") or row.get("collected_at") or "",
        reverse=True,
    )[:15]
    top_headlines = []
    seen_titles = set()
    for row in evidence:
        title = str(row.get("title") or "").strip()
        normalized_title = " ".join(title.casefold().split())
        if not title or normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        top_headlines.append(title[:240])
        if len(top_headlines) >= 10:
            break

    metrics_summary = {
        "total_mentions": len(mentions),
        "sources": dict(source_counts),
        "sentiment": dict(sentiment_counts),
        "top_keywords": keyword_counts.most_common(10),
        "top_products": product_counts.most_common(10),
    }

    prompt = f"""
You are a senior brand intelligence analyst.

Company: {workspace["companyName"]}
Industry: {workspace.get("industry") or "Unknown"}
Brands: {json.dumps(workspace.get("brands") or [])}
Products: {json.dumps([item.get("name") for item in workspace.get("products") or []])}
Executives: {json.dumps([
    item.get("name")
    for item in (workspace.get("ceos") or []) + (workspace.get("executives") or [])
])}

IMPORTANT:

Use the monitoring summary and headlines only.
Do NOT summarize every mention.
Focus on trends, risks, opportunities and emerging topics.
Keep the response concise.

Monitoring Summary:
{json.dumps(metrics_summary, ensure_ascii=False)}

Recent Headlines:
{json.dumps(top_headlines, ensure_ascii=False)}

Return JSON only with this exact structure:
{{
  "executive_summary": "2-4 concise sentences grounded in the evidence",
  "top_risks": [
    {{"title": "", "evidence": "", "impact": "low|medium|high"}}
  ],
  "top_opportunities": [
    {{"title": "", "evidence": "", "impact": "low|medium|high"}}
  ],
  "emerging_topics": [
    {{"topic": "", "trend": "rising|stable|declining", "evidence": ""}}
  ],
  "recommendations": [
    {{"action": "", "priority": "low|medium|high", "reason": ""}}
  ]
}}

Rules:
- Use only the supplied evidence and metrics.
- Do not invent competitors, percentage changes, or events.
- If evidence is insufficient, say so clearly.
- Return at most 5 items per list.
"""

    from groq import Groq

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    client = Groq(api_key=api_key, timeout=25.0)
    print("=" * 80)
    print("BW AI ANALYSIS")
    print("Company:", company_name)
    print("Mentions:", len(mentions))
    print("Headlines:", len(top_headlines))
    print("=" * 80)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
        max_tokens=800,
    )
    content = response.choices[0].message.content or "{}"
    payload = _parse_json_object(content)
    usage = getattr(response, "usage", None)
    if usage:
        print(
            f"Prompt={usage.prompt_tokens} "
            f"Completion={usage.completion_tokens} "
            f"Total={usage.total_tokens}"
        )
    return {
        "company_name": workspace["companyName"],
        "generated_from_mentions": len(mentions),
        "metrics": {
            "source_counts": dict(source_counts),
            "sentiment_counts": dict(sentiment_counts),
            "top_keywords": keyword_counts.most_common(10),
            "top_products": product_counts.most_common(10),
        },
        "analysis": _normalise_analysis(payload),
        "groq_usage": {
            "model": model,
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        },
    }


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("Groq returned invalid JSON")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Groq returned an unexpected response shape")
    return payload


def _normalise_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "executive_summary": str(payload.get("executive_summary") or "").strip(),
        "top_risks": _object_list(payload.get("top_risks")),
        "top_opportunities": _object_list(payload.get("top_opportunities")),
        "emerging_topics": _object_list(payload.get("emerging_topics")),
        "recommendations": _object_list(payload.get("recommendations")),
    }


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)][:5]
