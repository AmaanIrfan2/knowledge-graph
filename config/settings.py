import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL")

# Redis / Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# NAS
NAS_BASE_PATH      = os.getenv("NAS_BASE_PATH", "/Volumes/Downloaded YT Videos")
CAPTIONS_BASE_PATH = os.getenv("CAPTIONS_BASE_PATH", "/Volumes/Captions- YT Videos")

# YouTube Data API
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# Scraping behaviour
REQUEST_DELAY_SECONDS = 3        # delay between yt-dlp requests
MAX_RETRIES = 3                  # retries on failed download
VIDEO_QUALITY = "1080"           # max video height to download
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )
