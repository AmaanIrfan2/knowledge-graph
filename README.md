# YouTube Channel Scraper

A CLI-driven pipeline that scrapes YouTube channels end-to-end — enumerating videos, downloading them to a NAS, and archiving metadata, captions, comments, and linked articles into PostgreSQL. Built with **yt-dlp**, **Celery + Redis**, **SQLAlchemy**, and **Alembic**.

---

## Architecture

```
CLI (main.py)
  │
  ├── init          → creates DB + runs Alembic migrations
  ├── add-channel   → registers a channel in PostgreSQL
  ├── scrape        → queues a Celery task to process the channel
  └── status        → prints per-channel video processing summary

Celery Worker (workers/tasks.py)
  │
  ├── scrape_channel   → enumerates all videos on a channel (Phase A)
  └── process_video    → per-video pipeline (Phases B–E)
        ├── B  Fetch metadata (yt-dlp)
        ├── B  Fetch captions (manual → auto fallback)
        ├── C  Download video to NAS (≤1080p, .mp4)
        ├── D  Fetch comments (YouTube Data API v3)
        └── E  Extract linked articles + related videos
```

---

## Database Schema

Five PostgreSQL tables, managed via Alembic migrations:

| Table | Purpose |
|---|---|
| `channels` | Registered YouTube channels (`channel_id`, `name`, `url`, `last_scraped_at`) |
| `videos` | Core video metadata + captions (JSONB), NAS path, processing status |
| `comments` | Threaded comments with `reply_to` for nested replies |
| `related_videos` | YouTube videos linked in descriptions or suggested in the sidebar |
| `linked_articles` | Non-YouTube URLs found in descriptions and pinned comments |

Each video gets a human-readable **internal ID** in the format:

```
{ChannelName}-{DDMMYYYY}-{HHMMSS}-{sequence}
e.g.  BBCNews-25032026-143022-1
```

---

## Prerequisites

- **Python 3.12+**
- **PostgreSQL** (running locally or remotely)
- **Redis** (used as Celery broker and result backend)
- **ffmpeg** (required by yt-dlp for merging video + audio streams)
- A **YouTube Data API v3** key (optional — needed for comment fetching)

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url> && cd youtube-video-scraper
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the example below into a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/youtube_db

# Redis
REDIS_URL=redis://localhost:6379/0

# Path where downloaded videos are stored
NAS_BASE_PATH=/Volumes/Downloaded YT Videos

# YouTube Data API key (optional — needed for comments)
YOUTUBE_API_KEY=

# Logging
LOG_LEVEL=INFO
```

### 4. Initialise the database

```bash
python main.py init
```

This creates the PostgreSQL database (if it doesn't exist) and runs all Alembic migrations.

---

## Usage

### Register a channel

```bash
python main.py add-channel \
  --channel-id UC16niRr50-MSBwiO3YDb3RA \
  --name "BBCNews" \
  --url "https://www.youtube.com/@BBCNews"
```

### Start a scrape

```bash
# Scrape all videos
python main.py scrape --channel-id UC16niRr50-MSBwiO3YDb3RA

# Scrape only the 10 most recent videos
python main.py scrape --channel-id UC16niRr50-MSBwiO3YDb3RA --limit 10
```

### Check processing status

```bash
python main.py status
```

Outputs per-channel totals for `processed`, `processing`, `failed`, and `pending` videos.

### Start the Celery worker

In a separate terminal (Redis must be running):

```bash
celery -A workers.celery_app worker --loglevel=info
```

---

## Project Structure

```
.
├── main.py                  # CLI entry point (init, add-channel, scrape, status)
├── config/
│   └── settings.py          # Environment variables & scraping config
├── db/
│   ├── database.py          # SQLAlchemy engine, session manager, init_db()
│   └── models.py            # ORM models (Channel, Video, Comment, etc.)
├── scraper/
│   ├── ytdlp.py             # yt-dlp wrappers (enumerate, metadata, captions, download)
│   ├── comments.py          # YouTube Data API v3 comment fetcher
│   └── articles.py          # URL extraction from descriptions & pinned comments
├── workers/
│   ├── celery_app.py        # Celery application config
│   └── tasks.py             # scrape_channel + process_video task definitions
├── alembic/                 # Alembic migration environment
│   ├── env.py
│   └── versions/            # Auto-generated migration scripts
├── alembic.ini
├── requirements.txt
├── .env                     # Environment variables (git-ignored)
└── .gitignore
```

---

## Configuration

All settings are loaded from environment variables (via `.env`) in `config/settings.py`:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL for Celery |
| `NAS_BASE_PATH` | `/volume1/youtube-archive` | Root directory for downloaded files |
| `YOUTUBE_API_KEY` | — | YouTube Data API v3 key (comment fetching) |
| `LOG_LEVEL` | `INFO` | Python logging level |

Hard-coded in `settings.py`:

| Setting | Value | Description |
|---|---|---|
| `REQUEST_DELAY_SECONDS` | `3` | Delay between yt-dlp network calls |
| `MAX_RETRIES` | `3` | Celery task retry limit |
| `VIDEO_QUALITY` | `1080` | Maximum video height to download |

---

## NAS Storage Layout

Downloaded files are organised by channel:

```
{NAS_BASE_PATH}/
  └── {youtube_channel_id}/
      ├── {video_id}.mp4          # Video file (≤1080p)
      ├── {video_id}.en.vtt       # Caption file (VTT format)
      └── {video_id}.info.json    # Raw yt-dlp metadata backup
```

---

## Key Design Decisions

- **Sync workers** — Celery with SQLAlchemy + psycopg2 (no async).
- **Captions stored as JSONB** on the `videos` table — no separate captions table, multi-language ready.
- **Human-readable IDs** — no SHA256 hashes or UUIDs; `internal_id` encodes channel, date, time, and sequence.
- **Idempotent scraping** — already-processed videos are skipped; incremental runs only process new uploads.
- **Graceful error handling** — partial DB records are deleted on failure so the next run retries cleanly; rate-limit errors (HTTP 429) trigger delayed retries.
- **YouTube Data API for comments** — preferred over `yt-dlp --write-comments` for cleaner data and quota management.

---

## Development

### Adding a new migration

```bash
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

> **Note:** Never use `Base.metadata.create_all()` — all schema changes go through Alembic.

### Running migrations manually

```bash
alembic upgrade head
```
