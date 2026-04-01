import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from workers.celery_app import app
from db.database import get_session
from db.models import Channel, Video, Comment, RelatedVideo, LinkedArticle
from yt_dlp.utils import DownloadError
from scraper.ytdlp import enumerate_channel, get_video_metadata, fetch_captions, download_video, fetch_pinned_comment
from scraper.innertube import fetch_suggested_video_ids, fetch_end_screen_video_ids
from scraper.comments import fetch_comments
from scraper.articles import parse_linked_articles, parse_related_videos
from config.settings import MAX_RETRIES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_internal_id(
    channel_name: str,
    upload_date: str,
    upload_timestamp: int | None,
    sequence: int,
) -> str:
    """Build internal_id in the format cccc-ddmmyyyy-hhmmss-nnnn."""
    source = re.sub(r"[^A-Za-z0-9]", "", channel_name)[:12]

    # upload_date is YYYYMMDD from yt-dlp → reformat to DDMMYYYY
    date_part = upload_date[6:8] + upload_date[4:6] + upload_date[0:4]

    if upload_timestamp:
        dt = datetime.fromtimestamp(upload_timestamp, tz=timezone.utc)
        time_part = dt.strftime("%H%M%S")
    else:
        time_part = "000000"

    return f"{source}-{date_part}-{time_part}-{sequence}"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@app.task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=60)
def process_video(self, yt_video_id: str, channel_db_id: int, sequence: int) -> None:
    """
    Process a single video through all phases:
      B  — fetch metadata
      B  — fetch captions
      C  — download video to NAS
      D  — fetch comments (YouTube Data API)
      E  — extract linked articles + related videos from description
    """
    try:
        # --- Idempotency check + read channel info ---
        with get_session() as session:
            existing = session.query(Video).filter_by(yt_video_id=yt_video_id).first()
            if existing and existing.status == "processed":
                logger.info("Skipping %s — already processed", yt_video_id)
                return

            channel = session.get(Channel, channel_db_id)
            if not channel:
                raise ValueError(f"Channel {channel_db_id} not found in DB")

            channel_name   = channel.name
            channel_yt_id  = channel.channel_id

        # --- Phase B: metadata (network call, outside session) ---
        logger.info("[%s] fetching metadata", yt_video_id)
        meta = get_video_metadata(yt_video_id)

        internal_id = _build_internal_id(
            channel_name,
            meta.upload_date or "01010001",
            meta.upload_timestamp,
            sequence,
        )

        with get_session() as session:
            video = session.query(Video).filter_by(yt_video_id=yt_video_id).first()
            if not video:
                video = Video(
                    internal_id    = internal_id,
                    yt_video_id    = yt_video_id,
                    channel_id     = channel_db_id,
                    title          = meta.title,
                    description    = meta.description,
                    duration       = meta.duration,
                    view_count     = meta.view_count,
                    like_count     = meta.like_count,
                    thumbnail_url  = meta.thumbnail_url,
                    status         = "processing",
                )
                session.add(video)
            else:
                video.internal_id  = internal_id
                video.title        = meta.title
                video.description  = meta.description
                video.duration     = meta.duration
                video.view_count   = meta.view_count
                video.like_count   = meta.like_count
                video.thumbnail_url = meta.thumbnail_url
                video.status       = "processing"

        # --- Phase B (captions): network call, outside session ---
        logger.info("[%s] fetching captions", yt_video_id)
        try:
            caption_path, caption_source = fetch_captions(yt_video_id, channel_yt_id)
            logger.info("[%s] captions: source=%s found=%s", yt_video_id, caption_source, caption_path is not None)
        except Exception as exc:
            logger.warning("[%s] captions failed, continuing without: %s", yt_video_id, exc)
            caption_path, caption_source = None, "auto"

        # --- Phase C: download video, outside session ---
        logger.info("[%s] downloading video", yt_video_id)
        filepath = download_video(yt_video_id, channel_yt_id)
        logger.info("[%s] download complete: %s", yt_video_id, filepath)

        # --- Phase D: fetch comments, outside session ---
        logger.info("[%s] fetching comments", yt_video_id)
        try:
            comments_data = list(fetch_comments(yt_video_id))
            logger.info("[%s] fetched %d comments", yt_video_id, len(comments_data))
        except Exception as exc:
            logger.warning("[%s] comments failed, continuing without: %s", yt_video_id, exc)
            comments_data = []

        # --- Phase E: parse description + pinned comment for articles + related videos ---
        logger.info("[%s] parsing linked articles and related videos", yt_video_id)
        try:
            pinned_text   = fetch_pinned_comment(yt_video_id)
            articles_data = parse_linked_articles(meta.description, found_in="description")
            articles_data += parse_linked_articles(pinned_text, found_in="pinned-comment")
            related_data  = parse_related_videos(meta.description)

            seen_ids = {r["related_video_id"] for r in related_data}
            for vid_id in fetch_suggested_video_ids(yt_video_id):
                if vid_id not in seen_ids:
                    seen_ids.add(vid_id)
                    related_data.append({"related_video_id": vid_id, "url": f"https://www.youtube.com/watch?v={vid_id}", "relation_type": "suggested"})

            for vid_id in fetch_end_screen_video_ids(yt_video_id):
                if vid_id not in seen_ids:
                    seen_ids.add(vid_id)
                    related_data.append({"related_video_id": vid_id, "url": f"https://www.youtube.com/watch?v={vid_id}", "relation_type": "end-screen"})
        except Exception as exc:
            logger.warning("[%s] phase E failed, continuing without articles/related: %s", yt_video_id, exc)
            articles_data = []
            related_data  = []

        # --- Final update: write everything to DB ---
        with get_session() as session:
            video = session.query(Video).filter_by(yt_video_id=yt_video_id).first()
            if not video:
                logger.warning("[%s] video record missing at final write, skipping", yt_video_id)
                return
            video_db_id = video.id

            if caption_path:
                video.caption_nas_path = {"en": caption_path}
            if filepath:
                video.nas_file_path = filepath

            if comments_data:
                session.execute(
                    insert(Comment).on_conflict_do_nothing(index_elements=["comment_id"]),
                    [{"video_id": video_db_id, **c} for c in comments_data],
                )

            if articles_data:
                session.execute(
                    insert(LinkedArticle).on_conflict_do_nothing(
                        index_elements=["video_id", "url"]
                    ),
                    [{"video_id": video_db_id, **a} for a in articles_data],
                )

            if related_data:
                session.execute(
                    insert(RelatedVideo).on_conflict_do_nothing(
                        index_elements=["video_id", "related_video_id"]
                    ),
                    [{"video_id": video_db_id, **r} for r in related_data],
                )

            video.status = "processed"

        logger.info("Processed %s → %s", yt_video_id, internal_id)

    except DownloadError as exc:
        msg = str(exc)
        # Delete the partial record so the next scrape retries it
        with get_session() as session:
            video = session.query(Video).filter_by(yt_video_id=yt_video_id).first()
            if video:
                session.delete(video)
        if "429" in msg or "Too Many Requests" in msg or "ffmpeg" in msg.lower() or "CERTIFICATE_VERIFY_FAILED" in msg or "SSL" in msg:
            raise self.retry(exc=exc, countdown=120)
        # Video is permanently unavailable — log and discard
        logger.warning("[%s] skipping — video unavailable: %s", yt_video_id, exc)

    except Exception as exc:
        # Delete the partial record so the next scrape retries it
        with get_session() as session:
            video = session.query(Video).filter_by(yt_video_id=yt_video_id).first()
            if video:
                session.delete(video)
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=2, default_retry_delay=300)
def scrape_channel(self, channel_url: str, limit: int | None = None) -> None:
    """
    Phase A: enumerate a channel and queue a process_video task for each new video.
    Already-processed videos are skipped. Sequence numbers continue from the
    current count so incremental runs stay in chronological order.
    If limit is set, only the N most recent videos are fetched; they are queued oldest-first.
    """
    try:
        with get_session() as session:
            channel = session.query(Channel).filter_by(url=channel_url).first()
            if not channel:
                raise ValueError(
                    f"Channel not found for URL: {channel_url}. "
                    "Add it to the channels table first."
                )
            channel_db_id = channel.id

            # IDs already in the DB for this channel (any status)
            existing_ids: set[str] = {
                row.yt_video_id
                for row in session.query(Video.yt_video_id).filter_by(channel_id=channel_db_id)
            }

            # Max sequence already assigned — new videos continue from here
            max_seq: int = (
                session.query(func.count(Video.id))
                .filter_by(channel_id=channel_db_id)
                .scalar()
            ) or 0

        # yt-dlp returns newest-first; reverse so sequence reflects upload order
        all_entries = list(enumerate_channel(channel_url, limit=limit))
        all_entries.reverse()

        new_entries = [e for e in all_entries if e.video_id not in existing_ids]

        # Create "pending" records in DB *before* dispatching Celery tasks,
        # so every video is tracked even if Celery drops the task.
        with get_session() as session:
            for i, entry in enumerate(new_entries, start=max_seq + 1):
                session.add(Video(
                    internal_id = f"pending-{entry.video_id}",
                    yt_video_id = entry.video_id,
                    channel_id  = channel_db_id,
                    title       = entry.title or "(pending)",
                    status      = "pending",
                ))

        # Now dispatch Celery tasks — if any are lost, the DB still has the record
        for i, entry in enumerate(new_entries, start=max_seq + 1):
            process_video.delay(entry.video_id, channel_db_id, i)

        # Update last_scraped_at
        with get_session() as session:
            channel = session.get(Channel, channel_db_id)
            channel.last_scraped_at = datetime.now(tz=timezone.utc)

        logger.info(
            "Queued %d new videos for %s (%d already existed)",
            len(new_entries), channel_url, len(existing_ids),
        )

    except Exception as exc:
        raise self.retry(exc=exc)
