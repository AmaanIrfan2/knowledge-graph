import argparse
import logging
import sys

from config.settings import setup_logging
from db.database import init_db, get_session
from db.models import Channel, Video

setup_logging()
logger = logging.getLogger(__name__)


def cmd_init(_args: argparse.Namespace) -> None:
    """Ensure the database and all tables exist."""
    logger.info("Initialising database...")
    init_db()
    logger.info("Done.")


def cmd_add_channel(args: argparse.Namespace) -> None:
    """Register a channel so it can be scraped."""
    with get_session() as session:
        existing = session.query(Channel).filter_by(channel_id=args.channel_id).first()
        if existing:
            print(f"Channel '{args.channel_id}' already registered as '{existing.name}'.")
            return
        channel = Channel(
            channel_id=args.channel_id,
            name=args.name,
            url=args.url,
        )
        session.add(channel)
    print(f"Added channel: {args.name} ({args.channel_id})")


def cmd_scrape(args: argparse.Namespace) -> None:
    """Queue a scrape_channel task for a registered channel."""
    from workers.tasks import scrape_channel

    with get_session() as session:
        channel = session.query(Channel).filter_by(channel_id=args.channel_id).first()
        if not channel:
            print(
                f"Channel '{args.channel_id}' not found. "
                "Register it first with: main.py add-channel"
            )
            sys.exit(1)
        channel_url = channel.url

    task = scrape_channel.delay(channel_url, limit=args.limit)
    print(f"Queued scrape for '{args.channel_id}' — task ID: {task.id}")


def cmd_status(_args: argparse.Namespace) -> None:
    """Print a summary of all channels and their video statuses."""
    with get_session() as session:
        channels = session.query(Channel).all()
        if not channels:
            print("No channels registered.")
            return

        for ch in channels:
            videos = ch.videos
            total      = len(videos)
            processed  = sum(1 for v in videos if v.status == "processed")
            processing = sum(1 for v in videos if v.status == "processing")
            failed     = sum(1 for v in videos if v.status == "failed")
            pending    = sum(1 for v in videos if v.status == "pending")

            print(
                f"\n{ch.name} ({ch.channel_id})\n"
                f"  total={total}  processed={processed}  "
                f"processing={processing}  failed={failed}  pending={pending}\n"
                f"  last scraped: {ch.last_scraped_at or 'never'}"
            )


def cmd_retry(args: argparse.Namespace) -> None:
    """Re-queue any videos stuck in pending or processing status."""
    from workers.tasks import process_video

    with get_session() as session:
        channel = session.query(Channel).filter_by(channel_id=args.channel_id).first()
        if not channel:
            print(
                f"Channel '{args.channel_id}' not found. "
                "Register it first with: main.py add-channel"
            )
            sys.exit(1)

        stuck = (
            session.query(Video)
            .filter(
                Video.channel_id == channel.id,
                Video.status.in_(["pending", "processing"]),
            )
            .all()
        )

        if not stuck:
            print(f"No stuck videos for {channel.name}.")
            return

        channel_db_id = channel.id

        # Determine sequence numbers from existing internal_ids
        for video in stuck:
            # Reset status to pending so process_video picks it up cleanly
            video.status = "pending"

    # Dispatch outside the session
    for video_yt_id, seq in [(v.yt_video_id, i) for i, v in enumerate(stuck, start=1)]:
        process_video.delay(video_yt_id, channel_db_id, seq)

    print(f"Re-queued {len(stuck)} stuck video(s) for processing.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="YouTube Channel Scraper",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Initialise database and run migrations")

    # add-channel
    p_add = sub.add_parser("add-channel", help="Register a YouTube channel")
    p_add.add_argument("--channel-id", required=True, help="YouTube channel ID (e.g. UCxxxxxx)")
    p_add.add_argument("--name",       required=True, help="Human-readable name (e.g. BBCNews)")
    p_add.add_argument("--url",        required=True, help="Full channel URL")

    # scrape
    p_scrape = sub.add_parser("scrape", help="Queue a channel scrape")
    p_scrape.add_argument("--channel-id", required=True, help="YouTube channel ID to scrape")
    p_scrape.add_argument("--limit", type=int, default=None, help="Max number of videos to queue (oldest first)")

    # status
    sub.add_parser("status", help="Show video processing status per channel")

    # retry
    p_retry = sub.add_parser("retry", help="Re-queue stuck (pending/processing) videos")
    p_retry.add_argument("--channel-id", required=True, help="YouTube channel ID to retry")

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "init":        cmd_init,
        "add-channel": cmd_add_channel,
        "scrape":      cmd_scrape,
        "status":      cmd_status,
        "retry":       cmd_retry,
    }
    commands[args.command](args)
