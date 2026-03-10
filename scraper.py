import json
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import trafilatura
from bs4 import BeautifulSoup
from slugify import slugify

logger = logging.getLogger(__name__)

_DATE_PATTERNS = [
    re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})"),  # yyyy/mm/dd
    re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})"),  # dd/mm/yyyy
]

_BYLINE_RE = re.compile(
    r"(?:by|authors?)[:\s]+([A-Z][a-z]+(?: [A-Z][a-z]+)+)",
    re.IGNORECASE,
)

def extract_source_name(url: str) -> str:
    netloc = re.sub(r"^www\.", "", urlparse(url).netloc)
    domain = netloc.split(".")[0]
    return slugify(domain, max_length=40)


def _parse_date(date_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _parse_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    # JSON-LD
    json_ld = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, list):
                data = data[0]
            if isinstance(data, dict) and data.get("@type") in ("NewsArticle", "Article", "BlogPosting"):
                json_ld = data
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    # Headline
    headline = (
        (soup.find("meta", property="og:title") or {}).get("content")
        or (soup.find("meta", attrs={"name": "title"}) or {}).get("content")
        or (soup.find("h1") or BeautifulSoup("", "lxml")).get_text(strip=True)
        or (soup.find("title") or BeautifulSoup("", "lxml")).get_text(strip=True)
        or ""
    )

    # Reporters
    reporters = []
    author = json_ld.get("author")
    if isinstance(author, dict):
        reporters = [author["name"]] if author.get("name") else []
    elif isinstance(author, list):
        reporters = [a["name"] for a in author if isinstance(a, dict) and a.get("name")]
    elif isinstance(author, str):
        reporters = [author]
    if not reporters:
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            reporters = [meta_author["content"].strip()]
    if not reporters:
        # Byline regex — search the first 500 chars of the page text
        match = _BYLINE_RE.search(soup.get_text()[:500])
        if match:
            reporters = [match.group(1).strip()]

    # Publish date
    publish_dt = None
    date_str = json_ld.get("datePublished")
    if not date_str:
        meta = soup.find("meta", property="article:published_time")
        date_str = meta.get("content") if meta else None
    if date_str:
        publish_dt = _parse_date(date_str)
    if not publish_dt:
        for pattern in _DATE_PATTERNS:
            m = pattern.search(url)
            if m:
                g = m.groups()
                try:
                    publish_dt = datetime(int(g[0]), int(g[1]), int(g[2])) if len(g[0]) == 4 \
                        else datetime(int(g[2]), int(g[1]), int(g[0]))
                    break
                except ValueError:
                    continue

    # Media
    media_urls = []
    seen = set()
    article_tag = soup.find("article") or soup.find(class_=re.compile(r"article|content|post", re.I))
    if article_tag:
        for img in article_tag.find_all("img", src=True):
            if img["src"].startswith("http") and img["src"] not in seen:
                media_urls.append({"url": img["src"], "type": "image"})
                seen.add(img["src"])
    for meta_prop, meta_name in [("og:image", None), (None, "twitter:image")]:
        tag = soup.find("meta", property=meta_prop) if meta_prop else soup.find("meta", attrs={"name": meta_name})
        if tag and tag.get("content") and tag["content"] not in seen:
            media_urls.append({"url": tag["content"], "type": "image"})
            seen.add(tag["content"])

    return {
        "headline": headline,
        "reporters": reporters,
        "publish_dt": publish_dt,
        "media_urls": media_urls,
    }


async def scrape(url: str) -> dict:
    """
    Fetch and parse an article. Returns structured content dict.
    Retries up to 3 times with exponential backoff.
    """
    import asyncio
    from playwright.async_api import async_playwright

    html = None
    last_error = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for attempt in range(1, 4):
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_load_state("networkidle", timeout=10_000)
                html = await page.content()
                await context.close()
                break
            except Exception as e:
                last_error = e
                await context.close()
                logger.warning("Scrape attempt %d/3 failed: %s", attempt, e)
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)
        await browser.close()

    if not html:
        raise RuntimeError(f"Failed to fetch {url} after 3 attempts: {last_error}")

    body_text = trafilatura.extract(html, include_comments=False, include_tables=False)
    if not body_text:
        raise RuntimeError(f"trafilatura could not extract body text from {url}")

    metadata = _parse_html(html, url)
    return {
        "source_name": extract_source_name(url),
        "body_text": body_text,
        **metadata,
    }