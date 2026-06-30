from __future__ import annotations

import os
from typing import Any


DEFAULT_COMPANY_SCOPE_LIMITS = {
    "brand": 2,
    "product": 2,
    "executive": 1,
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return " ".join(_clean(value).casefold().split())


def _scope_limits() -> dict[str, int]:
    return {
        "brand": max(0, int(os.getenv("BW_COMPANY_SCOPE_BRAND_LIMIT", "2"))),
        "product": max(0, int(os.getenv("BW_COMPANY_SCOPE_PRODUCT_LIMIT", "2"))),
        "executive": max(0, int(os.getenv("BW_COMPANY_SCOPE_EXECUTIVE_LIMIT", "1"))),
    }


def _push_entry(
    entries: list[dict[str, Any]],
    seen: set[str],
    value: Any,
    entry_type: str,
    label: str,
    priority: int,
) -> None:
    cleaned = _clean(value)
    key = _normalized(cleaned)
    if not cleaned or key in seen:
        return
    seen.add(key)
    entries.append({
        "value": cleaned,
        "type": entry_type,
        "label": label,
        "priority": priority,
    })


def build_workspace_monitoring_entries(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    _push_entry(entries, seen, workspace.get("companyName"), "company", "Company", 1000)

    for index, brand in enumerate(workspace.get("brands") or []):
        _push_entry(entries, seen, brand, "brand", "Brand", 800 - index)

    for index, product in enumerate(workspace.get("products") or []):
        _push_entry(entries, seen, product.get("name") if isinstance(product, dict) else product, "product", "Product", 700 - index)

    for index, ceo in enumerate(workspace.get("ceos") or []):
        _push_entry(entries, seen, ceo.get("name") if isinstance(ceo, dict) else ceo, "executive", "Executive", 900 - index)

    for index, executive in enumerate(workspace.get("executives") or []):
        _push_entry(entries, seen, executive.get("name") if isinstance(executive, dict) else executive, "executive", "Executive", 600 - index)

    for index, campaign in enumerate(workspace.get("campaigns") or []):
        _push_entry(entries, seen, campaign, "campaign", "Campaign", 500 - index)

    for index, hashtag in enumerate(workspace.get("hashtags") or []):
        _push_entry(entries, seen, hashtag, "hashtag", "Hashtag", 400 - index)

    for index, keyword in enumerate(workspace.get("keywords") or []):
        _push_entry(entries, seen, keyword, "keyword", "Keyword", 300 - index)

    return entries


def _with_search_query(entry: dict[str, Any], company_name: str) -> dict[str, Any]:
    value = _clean(entry.get("value"))
    company = _clean(company_name)
    entry_type = _clean(entry.get("type")) or "keyword"
    needs_company_context = entry_type in {"campaign", "executive", "product", "hashtag"}
    should_append_company = (
        needs_company_context
        and company
        and _normalized(company) not in _normalized(value)
    )
    return {
        "value": value,
        "type": entry_type,
        "label": _clean(entry.get("label")) or entry_type,
        "searchQuery": f"{value} {company}" if should_append_company else value,
    }


def resolve_monitoring_scope(
    workspace: dict[str, Any],
    selected_keywords: list[str],
) -> dict[str, Any]:
    entries = build_workspace_monitoring_entries(workspace)
    selected = {_normalized(value) for value in selected_keywords if _clean(value)}
    selected_entries = [
        entry for entry in entries
        if _normalized(entry.get("value")) in selected
    ]
    company_selected = any(entry.get("type") == "company" for entry in selected_entries)

    if company_selected:
        limits = _scope_limits()
        selected_keys = {_normalized(entry.get("value")) for entry in selected_entries}
        company_scope = [
            entry for entry in entries
            if entry.get("type") == "company"
        ]
        for entry_type, limit in limits.items():
            candidates = sorted(
                (entry for entry in entries if entry.get("type") == entry_type),
                key=lambda entry: int(entry.get("priority") or 0),
                reverse=True,
            )
            company_scope.extend(candidates[:limit])

        scoped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in [*company_scope, *selected_entries]:
            key = _normalized(entry.get("value"))
            if not key or key in seen:
                continue
            seen.add(key)
            scoped.append(entry)
        mode = "focused_company_scope"
    else:
        scoped = selected_entries
        selected_keys = {_normalized(entry.get("value")) for entry in selected_entries}
        limits = _scope_limits()
        mode = "explicit_selection"

    company_name = _clean(workspace.get("companyName"))
    effective_entries = [_with_search_query(entry, company_name) for entry in scoped]

    return {
        "mode": mode,
        "companySelected": company_selected,
        "selectedCount": len(selected_keys),
        "effectiveCount": len(effective_entries),
        "limits": limits,
        "entries": effective_entries,
    }
