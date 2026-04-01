import logging
from datetime import datetime
from typing import Generator

import requests

from config.settings import YOUTUBE_API_KEY

logger = logging.getLogger(__name__)

_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_comments(video_id: str) -> Generator[dict, None, None]:
    """
    Phase D: fetch all comments + replies for a video via YouTube Data API v3.
    Yields dicts matching the Comment model fields (excluding video_id FK).
    Skips silently if YOUTUBE_API_KEY is not set.
    """
    if not YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY not set — skipping comments for %s", video_id)
        return

    params = {
        "part":        "snippet,replies",
        "videoId":     video_id,
        "maxResults":  100,
        "key":         YOUTUBE_API_KEY,
        "textFormat":  "plainText",
    }

    while True:
        response = requests.get(_COMMENTS_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            top     = item["snippet"]["topLevelComment"]
            snippet = top["snippet"]

            yield {
                "comment_id":   top["id"],
                "author":       snippet.get("authorDisplayName"),
                "text":         snippet.get("textDisplay"),
                "like_count":   snippet.get("likeCount", 0),
                "reply_to":     None,
                "published_at": _parse_dt(snippet.get("publishedAt")),
            }

            for reply in item.get("replies", {}).get("comments", []):
                rs = reply["snippet"]
                yield {
                    "comment_id":   reply["id"],
                    "author":       rs.get("authorDisplayName"),
                    "text":         rs.get("textDisplay"),
                    "like_count":   rs.get("likeCount", 0),
                    "reply_to":     top["id"],
                    "published_at": _parse_dt(rs.get("publishedAt")),
                }

        next_page = data.get("nextPageToken")
        if not next_page:
            break
        params["pageToken"] = next_page
