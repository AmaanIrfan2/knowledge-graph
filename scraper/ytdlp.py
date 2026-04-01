import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import yt_dlp

from config.settings import REQUEST_DELAY_SECONDS, NAS_BASE_PATH, VIDEO_QUALITY

logger = logging.getLogger(__name__)


@dataclass
class VideoEntry:
    """Lightweight entry from channel enumeration (Phase A)."""
    video_id: str
    title: str


@dataclass
class VideoMetadata:
    """Full metadata from per-video extraction (Phase B)."""
    video_id: str
    yt_channel_id: str
    title: str
    description: str | None
    duration: int | None
    view_count: int | None
    like_count: int | None
    thumbnail_url: str | None
    upload_date: str | None         # YYYYMMDD — used for ddmmyyyy in internal_id
    upload_timestamp: int | None    # unix timestamp — used for hhmmss in internal_id
    suggested_video_ids: list[str]  # from yt-dlp's related_videos (sidebar suggestions)


def _base_opts() -> dict:
    return {"quiet": True, "no_warnings": True}


def enumerate_channel(channel_url: str, limit: int | None = None) -> Generator[VideoEntry, None, None]:
    """Phase A: yield a VideoEntry for every video in the channel."""
    # Ensure we hit the /videos tab so yt-dlp enumerates uploads, not playlists
    url = channel_url.rstrip("/")
    if not url.endswith("/videos"):
        url = f"{url}/videos"

    opts = {**_base_opts(), "extract_flat": True}
    if limit:
        opts["playlistend"] = limit
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    for entry in (info.get("entries") or []):
        video_id = entry.get("id")
        if not video_id:
            continue
        yield VideoEntry(video_id=video_id, title=entry.get("title", ""))


def get_video_metadata(video_id: str) -> VideoMetadata:
    """Phase B: fetch full metadata for a single video (no download)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    time.sleep(REQUEST_DELAY_SECONDS)

    suggested_video_ids = [
        e["id"] for e in (info.get("related_videos") or []) if e.get("id")
    ]

    return VideoMetadata(
        video_id=info["id"],
        yt_channel_id=info.get("channel_id", ""),
        title=info["title"],
        description=info.get("description"),
        duration=info.get("duration"),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        thumbnail_url=info.get("thumbnail"),
        upload_date=info.get("upload_date"),
        upload_timestamp=info.get("timestamp"),
        suggested_video_ids=suggested_video_ids,
    )


def fetch_captions(video_id: str, channel_id: str, lang: str = "en") -> tuple[str | None, str]:
    """
    Phase B (captions): write subtitle file to NAS, return (text, source).
    Tries manual subs first, falls back to auto-generated.
    source is 'manual' or 'auto'. Returns (None, 'auto') on any error.
    """
    output_dir = Path(NAS_BASE_PATH) / channel_id
    output_dir.mkdir(parents=True, exist_ok=True)
    cap_file = output_dir / f"{video_id}.{lang}.vtt"

    for write_auto, source in [(False, "manual"), (True, "auto")]:
        opts = {
            **_base_opts(),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": write_auto,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception:
            return None, "auto"
        time.sleep(REQUEST_DELAY_SECONDS)

        if cap_file.exists() and cap_file.stat().st_size > 0:
            return cap_file.read_text(encoding="utf-8"), source

    return None, "auto"


def fetch_pinned_comment(video_id: str) -> str | None:
    """
    Fetch the text of the pinned comment for a video, if one exists.
    Uses yt-dlp comment extraction (no API key required).
    Returns None if there is no pinned comment.
    """
    opts = {
        **_base_opts(),
        "getcomments": True,
        "extractor_args": {"youtube": {"max_comments": ["10", "0", "0", "0"]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    time.sleep(REQUEST_DELAY_SECONDS)

    for comment in (info or {}).get("comments") or []:
        if comment.get("pinned"):
            return comment.get("text")
    return None


def download_video(video_id: str, channel_id: str) -> str | None:
    """Phase C: download video to NAS, return final file path."""
    output_dir = Path(NAS_BASE_PATH) / channel_id
    output_dir.mkdir(parents=True, exist_ok=True)

    opts = {
        **_base_opts(),
        "format": f"bestvideo[height<={VIDEO_QUALITY}]+bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=True
        )
        downloads = (info or {}).get("requested_downloads") or []
        absolute_path = downloads[0].get("filepath") if downloads else None

    time.sleep(REQUEST_DELAY_SECONDS)

    if not absolute_path:
        return None

    # Store path relative to NAS_BASE_PATH so it's valid on any machine
    return str(Path(absolute_path).relative_to(NAS_BASE_PATH))
