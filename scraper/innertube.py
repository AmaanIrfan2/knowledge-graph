import re
import json
import logging
import time

import requests

from config.settings import REQUEST_DELAY_SECONDS

logger = logging.getLogger(__name__)

_HEADERS_API  = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
_HEADERS_PAGE = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_CLIENT       = {"clientName": "WEB", "clientVersion": "2.20231219.04.00"}


def fetch_suggested_video_ids(video_id: str) -> list[str]:
    """
    Fetch sidebar suggested video IDs via the Innertube /next endpoint.
    Returns a list of YouTube video ID strings.
    """
    try:
        resp = requests.post(
            "https://www.youtube.com/youtubei/v1/next",
            headers=_HEADERS_API,
            json={"videoId": video_id, "context": {"client": _CLIENT}},
            timeout=10,
        )
        resp.raise_for_status()
        results = (
            resp.json()
            .get("contents", {})
            .get("twoColumnWatchNextResults", {})
            .get("secondaryResults", {})
            .get("secondaryResults", {})
            .get("results", [])
        )
        ids = [
            item["lockupViewModel"]["contentId"]
            for item in results
            if "lockupViewModel" in item and item["lockupViewModel"].get("contentId")
        ]
        time.sleep(REQUEST_DELAY_SECONDS)
        return ids
    except Exception as exc:
        logger.warning("[%s] fetch_suggested_video_ids failed: %s", video_id, exc)
        return []


def fetch_end_screen_video_ids(video_id: str) -> list[str]:
    """
    Fetch end screen video IDs by scraping ytInitialPlayerResponse from the watch page.
    Only returns elements of style VIDEO (skips CHANNEL, WEBSITE, etc.).
    Returns a list of YouTube video ID strings.
    """
    try:
        resp = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers=_HEADERS_PAGE,
            timeout=10,
        )
        resp.raise_for_status()
        match = re.search(
            r"ytInitialPlayerResponse\s*=\s*(\{.*?\});\s*(?:var|window|</script)",
            resp.text,
            re.DOTALL,
        )
        if not match:
            return []
        player_data = json.loads(match.group(1))
        elements = (
            player_data
            .get("endscreen", {})
            .get("endscreenRenderer", {})
            .get("elements", [])
        )
        ids = []
        for el in elements:
            renderer = el.get("endscreenElementRenderer", {})
            if renderer.get("style") != "VIDEO":
                continue
            vid = renderer.get("endpoint", {}).get("watchEndpoint", {}).get("videoId")
            if vid:
                ids.append(vid)
        time.sleep(REQUEST_DELAY_SECONDS)
        return ids
    except Exception as exc:
        logger.warning("[%s] fetch_end_screen_video_ids failed: %s", video_id, exc)
        return []
