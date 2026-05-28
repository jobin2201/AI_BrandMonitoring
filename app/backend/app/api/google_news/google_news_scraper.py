from __future__ import annotations

import traceback
import urllib.parse
import asyncio
import sys
from typing import List

from fastapi import APIRouter, Query
from playwright.async_api import async_playwright

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

router = APIRouter()


@router.get("/google-news/search")
async def google_news_search(
    brand: str = Query(..., description="Brand to search for"),
) -> List[dict]:
    return await asyncio.to_thread(lambda: asyncio.run(_google_news_search_async(brand)))


async def _google_news_search_async(brand: str) -> List[dict]:
    results = []
    encoded = urllib.parse.quote(brand)
    search_url = (
        "https://news.google.com/search"
        f"?q={encoded}&hl=en-IN&gl=IN&ceid=IN%3Aen"
    )
    print(f"[GOOGLE NEWS] Search URL: {search_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        try:
            print("[GOOGLE NEWS] Step 1: Navigating...")
            await page.goto(search_url, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3500)
            print(f"[GOOGLE NEWS] Step 1: URL={page.url} | Title='{await page.title()}'")

            print("[GOOGLE NEWS] Step 2: Waiting for article anchors...")
            try:
                await page.wait_for_selector("a.WwrzSb, a.JtKRv", timeout=10000)
                print("[GOOGLE NEWS] Step 2: Anchors visible")
            except Exception:
                print("[GOOGLE NEWS] Step 2: Anchor wait timed out - continuing")

            print("[GOOGLE NEWS] Step 3: Scrolling...")
            for _ in range(5):
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(600)
            await page.wait_for_timeout(1500)

            counts = await page.evaluate(
                """() => ({
                    WwrzSb: document.querySelectorAll('a.WwrzSb').length,
                    JtKRv: document.querySelectorAll('a.JtKRv').length,
                    article: document.querySelectorAll('article').length,
                    XlKvRb: document.querySelectorAll('.XlKvRb').length,
                    IFHyqb: document.querySelectorAll('.IFHyqb').length,
                })"""
            )
            print(f"[GOOGLE NEWS] Step 4: Selector counts -> {counts}")

            print("[GOOGLE NEWS] Step 5: Extracting...")
            raw = await page.evaluate(
                """
                () => {
                    const results = [];
                    const seen = new Set();

                    function fixHref(href) {
                        if (!href) return null;
                        href = href.trim();
                        if (href.startsWith('./')) return 'https://news.google.com' + href.slice(1);
                        if (href.startsWith('/')) return 'https://news.google.com' + href;
                        if (href.startsWith('http')) return href;
                        return null;
                    }

                    function getMeta(container) {
                        const srcEl = container.querySelector('.vr1PYe');
                        const timeEl = container.querySelector('time.hvbAAd') || container.querySelector('time');
                        return {
                            source: srcEl ? (srcEl.innerText || '').trim() : 'Google News',
                            published: timeEl
                                ? (timeEl.getAttribute('datetime') || (timeEl.innerText || '').trim() || null)
                                : null,
                        };
                    }

                    const titleAnchors = Array.from(document.querySelectorAll('a.JtKRv'));
                    for (const a of titleAnchors) {
                        if (results.length >= 30) break;
                        const title = (a.innerText || a.textContent || '').trim();
                        if (!title || title.length < 5) continue;

                        const card = a.closest('.IFHyqb') || a.closest('.XlKvRb') || a.closest('article') || a.closest('.m5k28');
                        const overlayEl = card ? card.querySelector('a.WwrzSb') : null;
                        const href = fixHref((overlayEl?.getAttribute('href')) || a.getAttribute('href'));
                        if (!href || seen.has(href)) continue;
                        seen.add(href);

                        const meta = card ? getMeta(card) : { source: 'Google News', published: null };
                        results.push({ title, url: href, source_name: meta.source, published_at: meta.published });
                    }

                    if (results.length > 0) return results;

                    const containers = Array.from(document.querySelectorAll('.XlKvRb, .IFHyqb, .m5k28, article'));
                    for (const card of containers) {
                        if (results.length >= 30) break;
                        const titleEl = card.querySelector('a.JtKRv, h3 a, h4 a');
                        const overlayEl = card.querySelector('a.WwrzSb');
                        if (!titleEl && !overlayEl) continue;

                        const title = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '';
                        if (!title || title.length < 5) continue;

                        const href = fixHref((overlayEl?.getAttribute('href')) || titleEl?.getAttribute('href'));
                        if (!href || seen.has(href)) continue;
                        seen.add(href);

                        const meta = getMeta(card);
                        results.push({ title, url: href, source_name: meta.source, published_at: meta.published });
                    }

                    if (results.length > 0) return results;

                    const overlays = Array.from(document.querySelectorAll('a.WwrzSb[aria-label]'));
                    for (const a of overlays) {
                        if (results.length >= 30) break;
                        const label = (a.getAttribute('aria-label') || '').trim();
                        const parts = label.split(' - ');
                        if (parts.length < 2) continue;
                        const title = parts[0].trim();
                        const href = fixHref(a.getAttribute('href'));
                        if (!title || title.length < 5 || !href || seen.has(href)) continue;
                        seen.add(href);
                        results.push({
                            title,
                            url: href,
                            source_name: (parts[1] || '').trim() || 'Google News',
                            published_at: (parts[2] || '').trim() || null,
                        });
                    }

                    return results;
                }
                """
            )

            print(f"[GOOGLE NEWS] Step 5: JS returned {len(raw)} raw items")
            for item in raw:
                if len(results) >= 30:
                    break
                title = (item.get("title") or "").strip()
                url = (item.get("url") or "").strip()
                if not title or not url:
                    continue
                results.append(
                    {
                        "title": title,
                        "url": url,
                        "source_name": item.get("source_name") or "Google News",
                        "published_at": item.get("published_at"),
                    }
                )
                print(f"[GOOGLE NEWS] [{len(results)}] {title[:70]} | {item.get('source_name')}")

            if not results:
                snippet = await page.evaluate("() => document.body.innerHTML.slice(0, 4000)")
                print(f"[GOOGLE NEWS] 0 results - HTML snippet:\n{snippet}\n")

        except Exception as exc:
            print(f"[GOOGLE NEWS] Exception: {exc}")
            traceback.print_exc()
        finally:
            await browser.close()
            print("[GOOGLE NEWS] Browser closed")

    print(f"[GOOGLE NEWS] DONE: returning {len(results)} articles for '{brand}'")
    return results
