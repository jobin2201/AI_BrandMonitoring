from __future__ import annotations


def share_of_voice(brand_count: int, competitor_count: int) -> dict:
    total = brand_count + competitor_count
    if total <= 0:
        return {
            "brand": 0.0,
            "competitor": 0.0,
            "brand_mentions": brand_count,
            "competitor_mentions": competitor_count,
        }

    return {
        "brand": round((brand_count / total) * 100, 2),
        "competitor": round((competitor_count / total) * 100, 2),
        "brand_mentions": brand_count,
        "competitor_mentions": competitor_count,
    }
