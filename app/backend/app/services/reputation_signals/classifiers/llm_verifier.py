from __future__ import annotations

import json
import os
import re
import time
from typing import Any


LABELS = [
    "environmental",
    "social",
    "governance",
    "product_success",
    "product_failure",
    "product_launch",
    "product_review",
    "product_comparison",
    "product_feature",
    "investment",
    "withdrawal",
    "regulatory_action",
    "none",
]

REGULATORY_BASES = {
    "regulator_involvement",
    "government_action",
    "legal_action",
    "enforcement_action",
    "compliance_action",
}

CUSTOMER_COMPLAINT_BASES = {
    "direct_customer_account",
    "reported_customer_complaint",
    "aggregated_customer_complaints",
}


def _parse_json_object(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        decoded_values = []
        for match in re.finditer(r"[\{\[]", text):
            try:
                value, _ = decoder.raw_decode(text[match.start():])
                decoded_values.append(value)
            except json.JSONDecodeError:
                continue
        if not decoded_values:
            raise
        for value in decoded_values:
            if isinstance(value, dict) and (
                "results" in value
                or "relevant" in value
                or "signals" in value
                or "category" in value
            ):
                return value
        return decoded_values[0]


def _response_usage(
    response: Any,
    model: str,
    duration_ms: float,
    *,
    requests: int = 1,
    rate_limit_retries: int = 0,
) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    return {
        "requests": requests,
        "cached_hits": 0,
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "duration_ms": round(duration_ms, 2),
        "model": model,
        "timeout_seconds": max(1.0, float(os.getenv("REPUTATION_GROQ_TIMEOUT_SECONDS", "8"))),
        "max_retries": max(0, int(os.getenv("REPUTATION_GROQ_MAX_RETRIES", "1"))),
        "rate_limit_retries": rate_limit_retries,
        "success": True,
    }


def _failed_usage(
    model: str,
    duration_ms: float,
    error: str,
    *,
    requests: int = 1,
    rate_limit_retries: int = 0,
) -> dict[str, Any]:
    return {
        "requests": requests,
        "cached_hits": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "duration_ms": round(duration_ms, 2),
        "model": model,
        "timeout_seconds": max(1.0, float(os.getenv("REPUTATION_GROQ_TIMEOUT_SECONDS", "8"))),
        "max_retries": max(0, int(os.getenv("REPUTATION_GROQ_MAX_RETRIES", "1"))),
        "rate_limit_retries": rate_limit_retries,
        "success": False,
        "error": error,
    }


def _groq_client(api_key: str):
    from groq import Groq

    timeout_seconds = max(1.0, float(os.getenv("REPUTATION_GROQ_TIMEOUT_SECONDS", "8")))
    return Groq(
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=0,
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    message = str(exc).lower()
    return (
        status_code == 429
        or response_status == 429
        or "429" in message
        or "rate limit" in message
        or "rate_limit" in message
    )


def _retry_after_seconds(exc: Exception) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw_value = headers.get("retry-after") or headers.get("Retry-After")
    fallback = max(0.1, float(os.getenv("REPUTATION_GROQ_RETRY_DELAY_SECONDS", "2")))
    maximum = max(fallback, float(os.getenv("REPUTATION_GROQ_MAX_RETRY_DELAY_SECONDS", "15")))
    try:
        return min(maximum, max(0.1, float(raw_value)))
    except (TypeError, ValueError):
        return min(maximum, fallback)


def _create_completion_with_rate_limit_retry(
    client: Any,
    *,
    model: str,
    prompt: str,
) -> tuple[Any, int, int]:
    max_retries = max(0, int(os.getenv("REPUTATION_GROQ_MAX_RETRIES", "1")))
    attempts = 0
    rate_limit_retries = 0
    while True:
        attempts += 1
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return response, attempts, rate_limit_retries
        except Exception as exc:
            if not _is_rate_limit_error(exc) or rate_limit_retries >= max_retries:
                try:
                    setattr(exc, "_reputation_groq_attempts", attempts)
                    setattr(exc, "_reputation_groq_rate_limit_retries", rate_limit_retries)
                except Exception:
                    pass
                raise
            delay = _retry_after_seconds(exc)
            rate_limit_retries += 1
            print(
                "[REPUTATION][GROQ] Rate limited "
                f"(429); retry {rate_limit_retries}/{max_retries} in {delay:.1f}s"
            )
            time.sleep(delay)


def _compact_entity_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_type": context.get("entity_type") or "",
        "company": context.get("company") or "",
        "product": context.get("product") or "",
        "validation_mode": context.get("validation_mode") or "",
        "validation_modes": list(context.get("validation_modes") or [])[:2],
        "aliases": list(context.get("aliases") or [])[:4],
        "product_aliases": list(context.get("product_aliases") or [])[:4],
    }


def _compact_prior_signal(prior_signal: dict[str, Any] | None) -> dict[str, Any]:
    prior = prior_signal or {}
    embedding = prior.get("embedding") or {}
    return {
        "signal": prior.get("signal") or "",
        "confidence": prior.get("confidence") or 0.0,
        "embedding_score": embedding.get("score") or 0.0,
        "embedding_category": embedding.get("best_category") or "",
    }


def _batch_result_id(value: dict[str, Any]) -> str:
    for key in ("id", "article_id", "request_id", "result_id"):
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _batch_result_signals(value: dict[str, Any]) -> list[Any]:
    raw_signals = value.get("signals")
    if isinstance(raw_signals, list):
        return raw_signals
    signal = value.get("signal") or value.get("category")
    if signal:
        return [{
            "signal": signal,
            "confidence": value.get("confidence") or 0.0,
            "reason": value.get("reason") or "",
            "semantic_basis": value.get("semantic_basis") or "",
            "concepts": value.get("concepts") or [],
        }]
    return []


def _build_batch_result(
    request_id: str,
    request: dict[str, Any],
    article_payload: dict[str, Any],
    result_present: bool,
) -> dict[str, Any]:
    allowed = {
        signal
        for signal in request.get("allowed_signals") or []
        if signal and signal != "none"
    }
    raw_signals = _batch_result_signals(article_payload)
    relevant_value = article_payload.get("relevant")
    relevant = (
        relevant_value.strip().lower() in {"1", "true", "yes"}
        if isinstance(relevant_value, str)
        else (
            any(
                isinstance(value, dict)
                and str(value.get("signal") or "none").strip().lower() not in {"", "none"}
                for value in raw_signals
            )
            if relevant_value is None
            else bool(relevant_value)
        )
    )

    classifications_by_signal: dict[str, dict[str, Any]] = {}
    semantic_rejections = []
    for value in raw_signals:
        if not isinstance(value, dict):
            continue
        candidate = str(value.get("signal") or "none").strip().lower().replace(" ", "_")
        if not relevant or candidate not in allowed:
            continue
        semantic_basis = str(value.get("semantic_basis") or "").strip().lower()
        if candidate == "regulatory_action" and semantic_basis not in REGULATORY_BASES:
            semantic_rejections.append({
                "signal": candidate,
                "reason": "regulatory_signal_missing_valid_semantic_basis",
                "semantic_basis": semantic_basis or "missing",
            })
            continue
        if candidate == "customer_complaint" and semantic_basis not in CUSTOMER_COMPLAINT_BASES:
            semantic_rejections.append({
                "signal": candidate,
                "reason": "customer_complaint_missing_valid_semantic_basis",
                "semantic_basis": semantic_basis or "missing",
            })
            continue
        try:
            confidence = float(value.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        classification = {
            "signal": candidate,
            "confidence": round(min(0.95, max(0.0, confidence)), 3),
            "reason": value.get("reason") or "LLM batch verification",
            "semantic_basis": semantic_basis,
            "concepts": [
                str(concept).strip()
                for concept in value.get("concepts") or []
                if str(concept).strip()
            ][:8],
        }
        current = classifications_by_signal.get(candidate)
        if current is None or classification["confidence"] > current["confidence"]:
            classifications_by_signal[candidate] = classification

    classifications = sorted(
        classifications_by_signal.values(),
        key=lambda value: value["confidence"],
        reverse=True,
    )
    primary = classifications[0] if classifications else {
        "signal": "none",
        "confidence": 0.0,
        "reason": (
            article_payload.get("reason")
            or (
                "No supported reputation signal"
                if result_present
                else "Groq omitted this article from the batch response"
            )
        ),
        "concepts": [],
    }
    return {
        "signal": primary["signal"],
        "confidence": primary["confidence"],
        "reason": primary["reason"],
        "concepts": primary.get("concepts") or [],
        "classifications": classifications,
        "semantic_rejections": semantic_rejections,
        "source": "groq_batch_verifier",
        "llm_verified": result_present,
        "llm_available": True,
        "batch_result_present": result_present,
    }


def verify_with_llm(text: str, prior_signal: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            **(prior_signal or {}),
            "llm_verified": False,
            "llm_available": False,
            "llm_reason": "GROQ_API_KEY missing",
        }

    prompt = f"""
Classify this article into ONE category:

Environmental
Social
Governance
Product Success
Product Failure
Investment
Withdrawal
Regulatory Action
None

Return JSON only:
{{
  "category": "Environmental|Social|Governance|Product Success|Product Failure|Investment|Withdrawal|Regulatory Action|None",
  "confidence": 0.0,
  "reason": "short evidence-based reason"
}}

Article:
{text[:700]}
"""
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    started = time.perf_counter()
    attempts = 0
    rate_limit_retries = 0
    try:
        client = _groq_client(api_key)
        response, attempts, rate_limit_retries = _create_completion_with_rate_limit_retry(
            client,
            model=model,
            prompt=prompt,
        )
        raw_response = response.choices[0].message.content or "{}"
        payload = _parse_json_object(raw_response)
    except Exception as exc:
        print(f"[REPUTATION] LLM verifier skipped: {exc}")
        attempts = int(getattr(exc, "_reputation_groq_attempts", attempts or 1))
        rate_limit_retries = int(
            getattr(exc, "_reputation_groq_rate_limit_retries", rate_limit_retries)
        )
        return {
            **(prior_signal or {}),
            "llm_verified": False,
            "llm_available": False,
            "llm_reason": str(exc),
            "groq_usage": _failed_usage(
                model,
                (time.perf_counter() - started) * 1000,
                str(exc),
                requests=attempts,
                rate_limit_retries=rate_limit_retries,
            ),
        }

    category = str(payload.get("category") or "none").strip().lower().replace(" ", "_")
    if category not in LABELS:
        category = "none"
    return {
        "signal": category,
        "confidence": round(min(0.95, float(payload.get("confidence") or 0.0)), 3),
        "reason": payload.get("reason") or "LLM verifier classification",
        "source": "groq_verifier",
        "llm_verified": True,
        "groq_usage": _response_usage(
            response,
            model,
            (time.perf_counter() - started) * 1000,
            requests=attempts,
            rate_limit_retries=rate_limit_retries,
        ),
    }


def verify_category_with_llm(
    text: str,
    *,
    category: str,
    allowed_signals: list[str],
    entity_context: dict[str, Any] | None = None,
    prior_signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            **(prior_signal or {}),
            "signal": "none",
            "confidence": 0.0,
            "reason": "GROQ_API_KEY missing",
            "source": "groq_category_verifier",
            "llm_verified": False,
            "llm_available": False,
        }

    allowed = [signal for signal in allowed_signals if signal and signal != "none"]
    context = _compact_entity_context(entity_context or {})
    compact_prior = _compact_prior_signal(prior_signal)
    article_limit = max(300, int(os.getenv("REPUTATION_GROQ_ARTICLE_CHARS", "750")))
    prompt = f"""
You are a reputation intelligence analyst.
Classify all material signals about the entity. Reject incidental, hypothetical,
unrelated, or keyword-only matches. Regulatory requires actual regulator,
government, legal, enforcement, or compliance action; awards, CSR, rankings,
recognition, and sustainability claims are not regulatory. Complaints require a
direct user account or reported complaints. Accidental damage is not product
failure without a defect or malfunction.

Entity: {json.dumps(context, separators=(",", ":"), default=str)}
Allowed: {json.dumps(allowed, separators=(",", ":"))}
Advisory: {json.dumps(compact_prior, separators=(",", ":"), default=str)}
Article: {text[:article_limit]}

JSON only:
{{"relevant":true,"signals":[{{"signal":"exact allowed signal","confidence":0.85,"reason":"factual reason","semantic_basis":"specific allowed basis","concepts":["concept"]}}]}}
Return each signal once; use [] when none apply. Regulatory basis must be one of
regulator_involvement, government_action, legal_action, enforcement_action,
compliance_action. Complaint basis must be direct_customer_account,
reported_customer_complaint, or aggregated_customer_complaints.
Confidence must be a reasoned number from 0.01 to 1.0 for every returned signal;
never copy the example value mechanically. A negative customer account may
support customer_complaint and product_failure together when both are evidenced.
"""
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    started = time.perf_counter()
    attempts = 0
    rate_limit_retries = 0
    try:
        client = _groq_client(api_key)
        response, attempts, rate_limit_retries = _create_completion_with_rate_limit_retry(
            client,
            model=model,
            prompt=prompt,
        )
        raw_response = response.choices[0].message.content or "{}"
        payload = _parse_json_object(raw_response)
        if isinstance(payload, list):
            print(
                f"[REPUTATION] Category LLM verifier list payload count={len(payload)} "
                f"payload={payload}"
            )
            payload = {
                "relevant": len(payload) > 0,
                "signals": payload,
            }
        elif not isinstance(payload, dict):
            print(
                f"[REPUTATION] Category LLM verifier unexpected payload type={type(payload).__name__} "
                f"payload={payload}"
            )
            payload = {"relevant": False, "signals": []}
    except Exception as exc:
        print(f"[REPUTATION] Category LLM verifier skipped: {exc}")
        attempts = int(getattr(exc, "_reputation_groq_attempts", attempts or 1))
        rate_limit_retries = int(
            getattr(exc, "_reputation_groq_rate_limit_retries", rate_limit_retries)
        )
        return {
            **(prior_signal or {}),
            "signal": "none",
            "confidence": 0.0,
            "reason": str(exc),
            "source": "groq_category_verifier",
            "llm_verified": False,
            "llm_available": False,
            "groq_usage": _failed_usage(
                model,
                (time.perf_counter() - started) * 1000,
                str(exc),
                requests=attempts,
                rate_limit_retries=rate_limit_retries,
            ),
        }

    raw_signals = payload.get("signals")
    if not isinstance(raw_signals, list):
        raw_signals = [{
            "signal": payload.get("signal") or "none",
            "confidence": payload.get("confidence") or 0.0,
            "reason": payload.get("reason") or "",
            "concepts": payload.get("concepts") or [],
        }]
    relevant_value = payload.get("relevant")
    if isinstance(relevant_value, str):
        relevant = relevant_value.strip().lower() in {"1", "true", "yes"}
    elif relevant_value is None:
        relevant = any(
            isinstance(value, dict)
            and str(value.get("signal") or "none").strip().lower() not in {"", "none"}
            for value in raw_signals
        )
    else:
        relevant = bool(relevant_value)
    classifications_by_signal: dict[str, dict[str, Any]] = {}
    semantic_rejections_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    for value in raw_signals:
        if not isinstance(value, dict):
            continue
        candidate = str(value.get("signal") or "none").strip().lower().replace(" ", "_")
        if not relevant or candidate not in allowed:
            continue
        semantic_basis = str(value.get("semantic_basis") or "").strip().lower()
        if candidate == "regulatory_action" and semantic_basis not in REGULATORY_BASES:
            rejection = {
                "signal": candidate,
                "reason": "regulatory_signal_missing_valid_semantic_basis",
                "semantic_basis": semantic_basis or "missing",
            }
            semantic_rejections_by_key[(
                rejection["signal"],
                rejection["reason"],
                rejection["semantic_basis"],
            )] = rejection
            continue
        if candidate == "customer_complaint" and semantic_basis not in CUSTOMER_COMPLAINT_BASES:
            rejection = {
                "signal": candidate,
                "reason": "customer_complaint_missing_valid_semantic_basis",
                "semantic_basis": semantic_basis or "missing",
            }
            semantic_rejections_by_key[(
                rejection["signal"],
                rejection["reason"],
                rejection["semantic_basis"],
            )] = rejection
            continue
        try:
            candidate_confidence = float(value.get("confidence") or payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            candidate_confidence = 0.0
        candidate_concepts = [
            str(concept).strip()
            for concept in value.get("concepts") or []
            if str(concept).strip()
        ]
        classification = {
            "category": str(value.get("category") or "").strip().lower(),
            "signal": candidate,
            "confidence": round(min(0.95, max(0.0, candidate_confidence)), 3),
            "reason": value.get("reason") or payload.get("reason") or "LLM category verification",
            "semantic_basis": semantic_basis,
            "concepts": candidate_concepts[:8],
        }
        current = classifications_by_signal.get(candidate)
        if current is None or classification["confidence"] > current["confidence"]:
            classifications_by_signal[candidate] = classification
    classifications = list(classifications_by_signal.values())
    classifications.sort(key=lambda value: value["confidence"], reverse=True)
    primary = classifications[0] if classifications else {
        "signal": "none",
        "confidence": 0.0,
        "reason": payload.get("reason") or "No supported reputation signal",
        "concepts": [],
    }
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    concepts = [
        str(value).strip()
        for value in payload.get("concepts") or []
        if str(value).strip()
    ]
    return {
        "signal": primary["signal"],
        "confidence": primary["confidence"],
        "reason": primary["reason"],
        "concepts": primary["concepts"] or concepts[:8],
        "classifications": classifications,
        "semantic_rejections": list(semantic_rejections_by_key.values()),
        "source": "groq_category_verifier",
        "llm_verified": True,
        "llm_available": True,
        "groq_usage": _response_usage(
            response,
            model,
            (time.perf_counter() - started) * 1000,
            requests=attempts,
            rate_limit_retries=rate_limit_retries,
        ),
    }


def verify_batch_with_llm(
    requests: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not requests:
        return {}, {
            "requests": 0,
            "cached_hits": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "duration_ms": 0.0,
            "rate_limit_retries": 0,
            "success": True,
        }

    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    if not api_key:
        return {
            str(request["id"]): {
                **(request.get("prior_signal") or {}),
                "signal": "none",
                "confidence": 0.0,
                "reason": "GROQ_API_KEY missing",
                "classifications": [],
                "semantic_rejections": [],
                "source": "groq_batch_verifier",
                "llm_verified": False,
                "llm_available": False,
            }
            for request in requests
        }, {
            "requests": 0,
            "cached_hits": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "duration_ms": 0.0,
            "rate_limit_retries": 0,
            "success": False,
            "error": "GROQ_API_KEY missing",
        }

    articles = []
    request_by_id: dict[str, dict[str, Any]] = {}
    for request in requests:
        request_id = str(request["id"])
        request_by_id[request_id] = request
        articles.append({
            "id": request_id,
            "entity": _compact_entity_context(request.get("entity_context") or {}),
            "allowed": [
                signal
                for signal in request.get("allowed_signals") or []
                if signal and signal != "none"
            ],
            "advisory": _compact_prior_signal(request.get("prior_signal")),
            "article": str(request.get("text") or "")[
                :max(300, int(os.getenv("REPUTATION_GROQ_ARTICLE_CHARS", "750")))
            ],
        })

    prompt = f"""
You are a reputation intelligence analyst. Classify each article independently.
Reject incidental, unrelated, hypothetical, or keyword-only matches. Never copy
signals between articles. Return only signals allowed for that article.
You MUST return exactly one result object for every input article id. Do not omit
irrelevant articles. For irrelevant articles, return the same id with
relevant=false, signals=[], and a short reason.

Rules:
- Regulatory requires actual regulator, government, court, legal, enforcement,
  or compliance action.
- Complaints require a direct negative user account or reported complaints.
- Accidental damage is not product failure without a defect or malfunction.
- Product launch, review, comparison, and feature are distinct from broad
  product success. Use product_success only for demonstrated positive reception,
  awards, adoption, sales, or strong market performance.
- Confidence must be reasoned from 0.01 to 1.0.

Articles:
{json.dumps(articles, separators=(",", ":"), default=str)}

JSON only:
{{"results":[{{"id":"exact id","relevant":true,"signals":[{{"signal":"exact allowed signal","confidence":0.85,"reason":"factual reason","semantic_basis":"specific basis","concepts":["concept"]}}]}},{{"id":"exact id","relevant":false,"reason":"No supported reputation signal","signals":[]}}]}}
Return exactly {len(articles)} result objects because exactly {len(articles)}
articles were provided. Use an empty signals array when none apply.
Regulatory basis: regulator_involvement, government_action, legal_action,
enforcement_action, or compliance_action. Complaint basis:
direct_customer_account, reported_customer_complaint, or
aggregated_customer_complaints.
"""
    started = time.perf_counter()
    attempts = 0
    rate_limit_retries = 0
    try:
        client = _groq_client(api_key)
        response, attempts, rate_limit_retries = _create_completion_with_rate_limit_retry(
            client,
            model=model,
            prompt=prompt,
        )
        payload = _parse_json_object(response.choices[0].message.content or "{}")
    except Exception as exc:
        attempts = int(getattr(exc, "_reputation_groq_attempts", attempts or 1))
        rate_limit_retries = int(
            getattr(exc, "_reputation_groq_rate_limit_retries", rate_limit_retries)
        )
        usage = _failed_usage(
            model,
            (time.perf_counter() - started) * 1000,
            str(exc),
            requests=attempts,
            rate_limit_retries=rate_limit_retries,
        )
        return {
            request_id: {
                **(request.get("prior_signal") or {}),
                "signal": "none",
                "confidence": 0.0,
                "reason": str(exc),
                "classifications": [],
                "semantic_rejections": [],
                "source": "groq_batch_verifier",
                "llm_verified": False,
                "llm_available": False,
            }
            for request_id, request in request_by_id.items()
        }, usage

    if isinstance(payload, list):
        raw_results = payload
    elif isinstance(payload, dict):
        raw_results = payload.get("results")
        if isinstance(raw_results, dict):
            raw_results = [
                {"id": result_id, **value}
                if isinstance(value, dict)
                else {"id": result_id, "signals": value}
                for result_id, value in raw_results.items()
            ]
        elif not isinstance(raw_results, list):
            raw_results = [payload]
    else:
        raw_results = []

    raw_results = [value for value in raw_results if isinstance(value, dict)]
    payload_type = type(payload).__name__
    raw_by_id = {
        _batch_result_id(value): value
        for value in raw_results
        if _batch_result_id(value)
    }
    id_order = [str(request["id"]) for request in requests]
    missing_ids = [request_id for request_id in id_order if request_id not in raw_by_id]
    if missing_ids and len(raw_results) == len(id_order):
        used_indexes = {
            index
            for index, value in enumerate(raw_results)
            if _batch_result_id(value) in id_order
        }
        next_index = 0
        for request_id in missing_ids:
            if request_id in raw_by_id:
                continue
            while next_index in used_indexes and next_index + 1 < len(raw_results):
                next_index += 1
            value = raw_results[next_index]
            raw_by_id[request_id] = {"id": request_id, **value}
            used_indexes.add(next_index)
    results: dict[str, dict[str, Any]] = {}
    for request_id, request in request_by_id.items():
        article_payload = raw_by_id.get(request_id) or {}
        result_present = request_id in raw_by_id
        results[request_id] = _build_batch_result(
            request_id,
            request,
            article_payload,
            result_present,
        )

    retry_enabled = (
        len(request_by_id) > 1
        and os.getenv("REPUTATION_GROQ_RETRY_OMITTED", "true").lower()
        in {"1", "true", "yes"}
    )
    retry_usage_totals = {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "duration_ms": 0.0,
        "rate_limit_retries": 0,
        "failed_requests": 0,
    }
    retry_attempted_ids: list[str] = []
    retry_recovered_ids: list[str] = []
    if retry_enabled:
        omitted_ids = [
            request_id
            for request_id, result in results.items()
            if not result.get("batch_result_present")
        ]
        for omitted_id in omitted_ids:
            retry_attempted_ids.append(omitted_id)
            retry_results, retry_usage = verify_batch_with_llm([request_by_id[omitted_id]])
            for field in [
                "requests",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "rate_limit_retries",
            ]:
                retry_usage_totals[field] += int(retry_usage.get(field) or 0)
            retry_usage_totals["duration_ms"] += float(retry_usage.get("duration_ms") or 0.0)
            if retry_usage.get("success") is False:
                retry_usage_totals["failed_requests"] += 1
            retry_result = retry_results.get(omitted_id)
            if retry_result and retry_result.get("batch_result_present"):
                retry_result["retried_after_batch_omission"] = True
                results[omitted_id] = retry_result
                retry_recovered_ids.append(omitted_id)

    usage = _response_usage(
        response,
        model,
        (time.perf_counter() - started) * 1000,
        requests=attempts,
        rate_limit_retries=rate_limit_retries,
    )
    for field in [
        "requests",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "rate_limit_retries",
    ]:
        usage[field] += int(retry_usage_totals[field])
    usage["duration_ms"] = round(
        float(usage.get("duration_ms") or 0.0) + retry_usage_totals["duration_ms"],
        2,
    )
    if retry_usage_totals["failed_requests"]:
        usage["failed_requests"] = int(usage.get("failed_requests") or 0) + retry_usage_totals["failed_requests"]
    usage["missing_results"] = len([
        request_id
        for request_id in request_by_id
        if not results.get(request_id, {}).get("batch_result_present")
    ])
    usage["parsed_results"] = len(raw_by_id)
    usage["batch_mapping"] = {
        "sent_count": len(request_by_id),
        "returned_count": len(raw_results),
        "matched_count": len([
            request_id
            for request_id in request_by_id
            if results.get(request_id, {}).get("batch_result_present")
        ]),
        "sent_ids": list(request_by_id.keys()),
        "returned_ids": [_batch_result_id(value) for value in raw_results],
        "matched_ids": [
            request_id
            for request_id in request_by_id
            if results.get(request_id, {}).get("batch_result_present")
        ],
        "unmatched_ids": [
            request_id
            for request_id in request_by_id
            if not results.get(request_id, {}).get("batch_result_present")
        ],
        "retry_attempted_ids": retry_attempted_ids,
        "retry_recovered_ids": retry_recovered_ids,
    }
    return results, usage
