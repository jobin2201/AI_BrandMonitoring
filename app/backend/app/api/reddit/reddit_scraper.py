from __future__ import annotations

import re
import asyncio
import sys
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from playwright.async_api import async_playwright

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

try:
    from app.api.reddit.emotion_utils import get_emotions
except ImportError:
    def get_emotions(text):
        return {}

try:
    from app.sentiment.vader_sentiment import analyse
except ImportError:
    def analyse(text):
        return {"label": "neutral", "compound": 0.0}

router = APIRouter()


def parse_relative_date(text: str):
    text = text.strip().lower()
    now = datetime.utcnow()
    if text == "just now":
        return now
    match = re.match(r"(\d+)\s*(second|minute|hour|day|week|month|year)s? ago", text)
    if not match:
        return None

    value, unit = int(match.group(1)), match.group(2)
    if unit == "second":
        return now - timedelta(seconds=value)
    if unit == "minute":
        return now - timedelta(minutes=value)
    if unit == "hour":
        return now - timedelta(hours=value)
    if unit == "day":
        return now - timedelta(days=value)
    if unit == "week":
        return now - timedelta(weeks=value)
    if unit == "month":
        return now - timedelta(days=value * 30)
    if unit == "year":
        return now - timedelta(days=value * 365)
    return None


async def close_consent_popup(page):
    try:
        accept = page.locator("button:has-text('Accept')")
        if await accept.count() > 0:
            await accept.first.click()
            print("[REDDIT] Clicked Accept consent button.")
            return

        agree = page.locator("button:has-text('I Agree')")
        if await agree.count() > 0:
            await agree.first.click()
            print("[REDDIT] Clicked I Agree consent button.")
    except Exception as exc:
        print(f"[REDDIT] No consent popup or close failed: {exc}")


async def extract_post_links(page) -> list[str]:
    post_links = []
    posts = page.locator("div[data-testid='post-container']")
    count = await posts.count()
    print(f"[REDDIT] Found {count} post containers")

    for i in range(count):
        try:
            post = posts.nth(i)
            href = None
            body_link = post.locator("a[data-click-id='body']")
            if await body_link.count() > 0:
                href = await body_link.first.get_attribute("href")
            if not href:
                title_link = post.locator("a[data-testid='post_title_link']")
                if await title_link.count() > 0:
                    href = await title_link.first.get_attribute("href")
            if href and href.startswith("/r/"):
                full_url = "https://www.reddit.com" + href
                if full_url not in post_links:
                    post_links.append(full_url)
        except Exception as exc:
            print(f"[REDDIT] Error extracting post URL {i}: {exc}")

    if post_links:
        return post_links

    print("[REDDIT] No post links with main selectors; trying generic anchors.")
    anchors = page.locator("a")
    anchor_count = await anchors.count()
    for i in range(anchor_count):
        try:
            href = await anchors.nth(i).get_attribute("href")
            if href and href.startswith("/r/") and "/comments/" in href:
                full_url = "https://www.reddit.com" + href
                if full_url not in post_links:
                    post_links.append(full_url)
        except Exception:
            continue

    return post_links


async def extract_post(context, brand: str, post_url: str) -> dict | None:
    post_page = await context.new_page()
    try:
        try:
            await post_page.goto(post_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as exc:
            print(f"[REDDIT] Fast load failed for {post_url}: {exc}")
            return None

        await post_page.wait_for_timeout(1000)
        post_container = post_page.locator("div[data-test-id='post-content']").first

        username = "[deleted]"
        author_locator = post_container.locator("a[data-testid='post_author_link']")
        if await author_locator.count() > 0:
            username = await author_locator.first.inner_text()
        else:
            alt_author = post_page.locator(".author-name")
            if await alt_author.count() > 0:
                username = await alt_author.first.inner_text()

        content = ""
        content_locator = post_container.locator("div[data-click-id='text']")
        if await content_locator.count() > 0:
            content = await content_locator.first.inner_text()
        else:
            h1_title = post_page.locator("h1[slot='title']")
            if await h1_title.count() > 0:
                content = await h1_title.first.inner_text()
            else:
                title_locator = post_container.locator("h1, h2, h3")
                if await title_locator.count() > 0:
                    content = await title_locator.first.inner_text()

        if not content:
            content = "[no content found]"

        date = ""
        time_elem = post_page.locator("div#pdp-credit-bar time[datetime]")
        if await time_elem.count() > 0:
            dt_str = await time_elem.first.get_attribute("datetime")
            try:
                date = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).isoformat()
            except Exception:
                date = dt_str
        else:
            date_locator = post_page.locator("a[data-click-id='timestamp']").first
            if await date_locator.count() > 0:
                rel_date = await date_locator.inner_text()
                parsed = parse_relative_date(rel_date)
                date = parsed.isoformat() if parsed else rel_date

        comments_list = []
        try:
            comment_ps = post_page.locator("shreddit-comment p")
            if await comment_ps.count() == 0:
                comment_ps = post_page.locator("#comment-tree-content-anchor- * p")
            for j in range(min(await comment_ps.count(), 20)):
                txt = (await comment_ps.nth(j).inner_text()).strip()
                if txt:
                    comments_list.append({"text": txt, "emotions": get_emotions(txt)})
        except Exception as exc:
            print(f"[REDDIT] Comment extraction skipped for {post_url}: {exc}")

        sentiment = analyse(content)
        return {
            "brand": brand,
            "url": post_url,
            "username": username,
            "content": content,
            "date": date,
            "scraped_at": datetime.utcnow().isoformat(),
            "sentiment_label": sentiment["label"],
            "sentiment_score": sentiment["compound"],
            "comments": comments_list,
        }
    except Exception as exc:
        print(f"[REDDIT] Failed extracting {post_url}: {exc}")
        return None
    finally:
        await post_page.close()


@router.post("/scrape-store-reddit")
async def scrape_and_store_reddit(
    brand: str = Query(..., description="Brand name to search on Reddit"),
    specific_term: str = Query(None, description="Resolved brand/company name to search on Reddit (optional)"),
    entity_name: str = Query(None, description="Entity name for post-filtering (optional)"),
    ignore_terms: str = Query(None, description="Comma-separated terms to ignore (optional)"),
):
    return await asyncio.to_thread(
        lambda: asyncio.run(
            _scrape_and_store_reddit_async(
                brand=brand,
                specific_term=specific_term,
                entity_name=entity_name,
                ignore_terms=ignore_terms,
            )
        )
    )


async def _scrape_and_store_reddit_async(
    brand: str,
    specific_term: str | None = None,
    entity_name: str | None = None,
    ignore_terms: str | None = None,
):
    search_brand = specific_term if specific_term else brand
    results = []
    search_url = f"https://www.reddit.com/search/?q={search_brand}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1024},
            java_script_enabled=True,
            locale="en-US",
        )
        page = await context.new_page()

        try:
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                print(f"[REDDIT] domcontentloaded failed: {exc}")
                await page.goto(search_url, wait_until="load", timeout=60000)

            await close_consent_popup(page)
            for _ in range(8):
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(1500)
            await page.wait_for_timeout(2500)

            post_links = await extract_post_links(page)
            print(f"[REDDIT] Extracted post URLs: {post_links}")

            total_links = min(20, len(post_links))
            for idx, post_url in enumerate(post_links[:20]):
                if len(results) >= 10:
                    break
                post_data = await extract_post(context, brand, post_url)
                if not post_data:
                    continue
                results.append(post_data)
                print(f"[REDDIT] extracted ({idx + 1}/{total_links}) link")

        except Exception as exc:
            print(f"[REDDIT] Search failed for {brand}: {exc}")
        finally:
            await browser.close()

    if entity_name:
        entity_name_lower = entity_name.lower()
        results = [
            item
            for item in results
            if entity_name_lower in (
                item.get("content", "").lower()
                + " "
                + item.get("username", "").lower()
                + " "
                + item.get("url", "").lower()
            )
        ]

    if ignore_terms:
        ignore_list = [term.strip().lower() for term in ignore_terms.split(",") if term.strip()]
        results = [
            item
            for item in results
            if not any(
                term in (item.get("content", "").lower() + " " + item.get("username", "").lower())
                for term in ignore_list
            )
        ]

    try:
        if results:
            from kafka import KafkaProducer
            import json
            import os

            producer = KafkaProducer(
                bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            )
            producer.send("brand.reddit.global", {"posts": results})
            producer.flush()
            producer.close()
            print(f"[KAFKA] Published {len(results)} Reddit posts to brand.reddit.global")
    except Exception as exc:
        print(f"[KAFKA ERROR] Could not publish to Kafka: {exc}")

    return results
