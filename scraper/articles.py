import re
import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s\)\]\>\"\']+")
_YT_RE  = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})")


def _extract_urls(text: str) -> list[str]:
    # dict.fromkeys preserves order while deduplicating
    return list(dict.fromkeys(_URL_RE.findall(text)))


def _fetch_url_info(url: str, timeout: int = 5) -> tuple[str, str | None]:
    """Follows redirects and returns (final_url, page_title)."""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True, stream=True)
        resp.raise_for_status()
        final_url = resp.url
        chunk = next(resp.iter_content(10_240), b"")
        html  = chunk.decode("utf-8", errors="ignore")
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = match.group(1).strip() if match else None
        return final_url, title
    except Exception:
        return url, None


def parse_linked_articles(text: str | None, found_in: str = "description") -> list[dict]:
    """
    Phase E: extract non-YouTube URLs from text (description or pinned comment).
    Follows redirects to resolve shortened URLs (e.g. bbc.in → full URL).
    Returns list of dicts matching LinkedArticle model fields (excluding video_id FK).
    """
    if not text:
        return []

    def _is_youtube(domain: str) -> bool:
        return "youtube.com" in domain or "youtu.be" in domain

    articles = []
    for url in _extract_urls(text):
        if _is_youtube(urlparse(url).netloc.lstrip("www.")):
            continue
        final_url, title = _fetch_url_info(url)
        final_domain = urlparse(final_url).netloc.lstrip("www.")
        if _is_youtube(final_domain):
            continue
        articles.append({
            "url":      final_url,
            "domain":   final_domain,
            "title":    title,
            "found_in": found_in,
        })

    return articles


def parse_related_videos(description: str | None) -> list[dict]:
    """
    Phase E: extract YouTube video IDs linked in the description.
    Returns list of dicts matching RelatedVideo model fields (excluding video_id FK).
    """
    if not description:
        return []

    seen = set()
    related = []
    for url in _extract_urls(description):
        match = _YT_RE.search(url)
        if match:
            vid_id = match.group(1)
            if vid_id not in seen:
                seen.add(vid_id)
                related.append({
                    "related_video_id": vid_id,
                    "url":              f"https://www.youtube.com/watch?v={vid_id}",
                    "relation_type":    "description-linked",
                })

    return related
